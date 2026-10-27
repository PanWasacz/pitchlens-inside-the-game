"""PitchLens server: the studio's static files and the /api/explain agents in one process.

    python api/server.py                # local API on http://localhost:7071 (Vite proxies /api here)

In production (Azure App Service, see docs/deploy.md) the deploy package puts the
built studio in ./static next to this file; the server then also serves the studio
(gzip-precompressed files when the browser accepts them) and listens on $PORT.
Model settings come from the environment (App Service settings) or from
api/local.settings.json (git-ignored); without them the agents answer from templates.
Standard library only.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pitchlens_agents.agents import explain  # noqa: E402
from pitchlens_agents.match import dataset_match, demo_match  # noqa: E402
from pitchlens_agents.request import BadRequest, dataset_key, parse_request  # noqa: E402
from pitchlens_agents.tools import build_match_report  # noqa: E402
from pitchlens_agents.report_tex import render_tex  # noqa: E402
from pitchlens_agents.report_pdf import render_pdf  # noqa: E402

STATIC = ROOT / "static"
ON_AZURE = bool(os.environ.get("WEBSITE_SITE_NAME"))
PORT = int(os.environ.get("PORT") or os.environ.get("WEBSITES_PORT") or (8000 if ON_AZURE else 7071))
HOST = "0.0.0.0" if ON_AZURE else "127.0.0.1"
MAX_BODY = 64 * 1024
TYPES = {".jsonl": "application/x-ndjson", ".js": "text/javascript", ".mjs": "text/javascript", ".webmanifest": "application/manifest+json"}

log = logging.getLogger("pitchlens")


def load_settings() -> None:
    path = ROOT / "local.settings.json"
    if path.exists():
        values = json.loads(path.read_text(encoding="utf-8")).get("Values", {})
        for k, v in values.items():
            if k.startswith("AZURE_OPENAI_") and v:
                os.environ.setdefault(k, str(v))


def log_run(result: dict, ms: int) -> None:
    """One structured line per request (App Service log stream / Application Insights)."""
    log.info("pitchlens.explain %s", json.dumps({
        "moment": result["moment"]["type"],
        "engine": result["engine"],
        "model": result["model"],
        "cached": result["cached"],
        "precomputed": result.get("precomputed", False),
        "model_calls": result["usage"]["model_calls"],
        "tokens": result["usage"]["tokens"],
        "ms": ms,
        "agents": [{"agent": s["agent"], "status": s["status"], "ms": s["ms"]} for s in result["trace"]],
    }))


class Handler(BaseHTTPRequestHandler):
    server_version = "PitchLens"

    def log_message(self, fmt, *args):  # keep the log for the agents' lines
        pass

    def do_POST(self):
        if urlsplit(self.path).path != "/api/explain":
            return self._json({"status": "error", "message": "not found"}, 404)
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_BODY:
            return self._json({"status": "error", "message": "body too large"}, 413)
        started = time.monotonic()
        try:
            body = json.loads(self.rfile.read(size) or b"null")
            match = dataset_match(dataset_key(body))
            result = explain(parse_request(body, match), match)
        except (json.JSONDecodeError, BadRequest) as e:
            return self._json({"status": "error", "message": str(e)}, 400)
        except Exception:  # never leak internals to the public endpoint
            log.exception("explain failed")
            return self._json({"status": "error", "message": "The analyst is unavailable right now."}, 500)
        log_run(result, round(1000 * (time.monotonic() - started)))
        self._json(result, 200)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/api/report":
            query = parse_qs(parsed.query)
            try:
                match = dataset_match(query.get("dataset", ["demo"])[0])
                return self._json(build_match_report(match), 200)
            except (ValueError, FileNotFoundError):
                return self._json({"status": "error", "message": "dataset is not available"}, 400)
        if parsed.path == "/api/report.tex":
            query = parse_qs(parsed.query)
            try:
                match = dataset_match(query.get("dataset", ["demo"])[0])
                dataset = query.get("dataset", ["demo"])[0]
                raw = render_tex(build_match_report(match)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/x-tex; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="pitchlens-{dataset}.tex"')
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)
                return
            except (ValueError, FileNotFoundError):
                return self._json({"status": "error", "message": "dataset is not available"}, 400)
        if parsed.path == "/api/report.pdf":
            query = parse_qs(parsed.query)
            try:
                match = dataset_match(query.get("dataset", ["demo"])[0])
                dataset = query.get("dataset", ["demo"])[0]
                raw = render_pdf(build_match_report(match))
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'attachment; filename="pitchlens-{dataset}.pdf"')
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)
                return
            except (ValueError, FileNotFoundError):
                return self._json({"status": "error", "message": "dataset is not available"}, 400)
        self._static(head=False)

    def do_HEAD(self):
        self._static(head=True)

    def _json(self, data: dict, status: int):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _static(self, head: bool):
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/api/"):
            return self._json({"status": "error", "message": "use POST"}, 405)
        if not STATIC.is_dir() or path.startswith("/local/"):
            return self._json({"status": "error", "message": "not found"}, 404)
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC.resolve() not in target.parents and target != STATIC.resolve():
            return self._json({"status": "error", "message": "not found"}, 404)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            if Path(path).suffix:  # a missing asset, not an app route
                return self._json({"status": "error", "message": "not found"}, 404)
            target = STATIC / "index.html"
        gz = target.with_name(target.name + ".gz")
        use_gz = gz.is_file() and "gzip" in (self.headers.get("Accept-Encoding") or "")
        file = gz if use_gz else target
        ctype = TYPES.get(target.suffix) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json", "application/x-ndjson"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(file.stat().st_size))
        if use_gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        immutable = "/assets/" in path
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "public, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head:
            with open(file, "rb") as f:
                while chunk := f.read(256 * 1024):
                    self.wfile.write(chunk)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_settings()
    demo_match()  # load the match once before the first request
    model = os.environ.get("AZURE_OPENAI_DEPLOYMENT") if os.environ.get("AZURE_OPENAI_API_KEY") else None
    studio = f"studio from {STATIC}" if STATIC.is_dir() else "API only (studio served by Vite)"
    log.info("PitchLens on http://%s:%s - %s - %s", HOST, PORT, studio, f"model {model}" if model else "template fallback (no model settings)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

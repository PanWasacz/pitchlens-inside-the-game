"""Local stand-in for the Azure Function, no Functions Core Tools needed.

    python api/local_server.py          # http://localhost:7071/api/explain

The Vite dev server proxies /api to this port. Model settings are read from the
environment or from api/local.settings.json (git-ignored); without them the
pipeline answers with its template fallback.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pitchlens_agents.agents import explain  # noqa: E402
from pitchlens_agents.match import demo_match  # noqa: E402
from pitchlens_agents.request import BadRequest, parse_request  # noqa: E402

PORT = 7071
MAX_BODY = 64 * 1024


def load_settings() -> None:
    path = ROOT / "local.settings.json"
    if path.exists():
        values = json.loads(path.read_text(encoding="utf-8")).get("Values", {})
        for k, v in values.items():
            if k.startswith("AZURE_OPENAI_") and v:
                os.environ.setdefault(k, str(v))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.split("?")[0] != "/api/explain":
            return self._send({"status": "error", "message": "not found"}, 404)
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_BODY:
            return self._send({"status": "error", "message": "body too large"}, 413)
        try:
            body = json.loads(self.rfile.read(size) or b"null")
            result = explain(parse_request(body, demo_match()))
        except (json.JSONDecodeError, BadRequest) as e:
            return self._send({"status": "error", "message": str(e)}, 400)
        self._send(result, 200)

    def _send(self, data: dict, status: int):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    load_settings()
    demo_match()  # load the match once before the first request
    mode = "Azure OpenAI deployment " + os.environ["AZURE_OPENAI_DEPLOYMENT"] if os.environ.get("AZURE_OPENAI_API_KEY") else "template fallback (no model settings)"
    print(f"PitchLens API on http://localhost:{PORT}/api/explain - {mode}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

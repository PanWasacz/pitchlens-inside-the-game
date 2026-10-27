"""Assemble the Azure App Service package in ./site from api/ and the built studio (web/dist).

    cd web && npm run build && cd ..
    python scripts/build_site.py
    python site/server.py            # same as production, on http://localhost:7071

Text assets are also stored gzip-compressed (*.gz) so the server can send the 16 MB
tracking file as about 1.6 MB.
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
COMPRESS = {".html", ".js", ".css", ".json", ".jsonl", ".svg", ".txt"}


def main() -> None:
    dist = REPO / "web" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit("web/dist is missing: run `npm run build` in web/ first")
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    api = REPO / "api"
    for name in ("server.py", "requirements.txt"):
        shutil.copy2(api / name, SITE / name)
    shutil.copytree(api / "pitchlens_agents", SITE / "pitchlens_agents", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(api / "data", SITE / "data")
    shutil.copytree(dist, SITE / "static")
    for f in (SITE / "static").rglob("*"):
        if f.is_file() and f.suffix in COMPRESS and f.stat().st_size > 1024:
            with open(f, "rb") as src, gzip.open(f.with_name(f.name + ".gz"), "wb", compresslevel=9) as dst:
                shutil.copyfileobj(src, dst)
    size = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file())
    print(f"site/ ready: {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

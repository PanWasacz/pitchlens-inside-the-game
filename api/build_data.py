"""Copy the synthetic demo match into api/data/ for the explain function.

frames.jsonl is gzipped (about 6x smaller) so the function package stays small.
Run after regenerating the demo:

    python api/build_data.py
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT.parent / "web" / "public" / "data" / "demo"
DST = ROOT / "data"


def main() -> None:
    DST.mkdir(exist_ok=True)
    for name in ("meta.json", "events.json"):
        shutil.copyfile(SRC / name, DST / name)
    with open(SRC / "frames.jsonl", "rb") as src, gzip.open(DST / "frames.jsonl.gz", "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)
    for p in sorted(DST.iterdir()):
        print(f"{p.name:20s} {p.stat().st_size / 1024:8.0f} kB")


if __name__ == "__main__":
    main()

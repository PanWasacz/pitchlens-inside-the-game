"""Build the match reports: LaTeX + PNG figures, compiled to report.pdf with pdflatex.

    pip install matplotlib
    python scripts/build_reports.py            # every available dataset -> web/public/reports/<key>/
    python scripts/build_reports.py --require-pdf   # CI: fail when a PDF cannot be compiled

Run before `npm run build` so the reports ship with the studio as static files.
The matches are fixed, so the reports are computed once at build time and the
production server keeps using the standard library only.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "api"))

from pitchlens_agents.match import DATASET_DIRS, dataset_match  # noqa: E402
from pitchlens_agents.report_figures import render_figures  # noqa: E402
from pitchlens_agents.report_tex import render_tex  # noqa: E402
from pitchlens_agents.tools import build_match_report  # noqa: E402

OUT = REPO / "web" / "public" / "reports"


def compile_pdf(folder: Path) -> bool:
    """pdflatex twice (for references); keeps only report.pdf next to the sources."""
    exe = shutil.which("pdflatex")
    if not exe:
        return False
    for _ in range(2):
        run = subprocess.run([exe, "-interaction=nonstopmode", "-halt-on-error", "report.tex"],
                             cwd=folder, capture_output=True, text=True)
        if run.returncode != 0:
            print(f"  pdflatex failed:\n{run.stdout[-1500:]}")
            return False
    for ext in (".aux", ".log", ".out", ".toc"):
        (folder / f"report{ext}").unlink(missing_ok=True)
    return (folder / "report.pdf").is_file()


def build(key: str) -> bool:
    """Returns False when the PDF could not be compiled."""
    try:
        m = dataset_match(key)
    except FileNotFoundError:
        print(f"{key}: data missing, skipped")
        return True
    folder = OUT / key
    if folder.exists():
        shutil.rmtree(folder)
    report = build_match_report(m)
    figures = render_figures(m, report, folder)
    (folder / "report.tex").write_text(render_tex(report, figures, date.today().isoformat()), encoding="utf-8")
    pdf = compile_pdf(folder)
    print(f"{key}: {report['match']['score']} -> {folder.relative_to(REPO)} (pdf: {'yes' if pdf else 'no'})")
    return pdf


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ok = all([build(key) for key in DATASET_DIRS])
    if not ok and "--require-pdf" in sys.argv:
        raise SystemExit("PDF reports could not be compiled (pdflatex missing or failed)")


if __name__ == "__main__":
    main()

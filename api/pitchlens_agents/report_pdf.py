"""Small dependency-free PDF renderer for PitchLens reports."""

from __future__ import annotations

from .report_tex import _tex


def _esc(value: object) -> str:
    return str(value).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def render_pdf(report: dict) -> bytes:
    home = report["match"]["home"]
    away = report["match"]["away"]
    pages: list[list[str]] = []
    page: list[str] = []

    def text(x: float, y: float, value: object, size: int = 10, color: tuple[float, float, float] = (0.1, 0.1, 0.1)) -> None:
        page.extend([f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg", f"BT /F1 {size} Tf {x:.1f} {y:.1f} Td ({_esc(value)}) Tj ET"])

    def line(x1: float, y1: float, x2: float, y2: float, color: tuple[float, float, float]) -> None:
        page.extend([f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG", f"{x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S"])

    def finish() -> None:
        pages.append(page.copy())
        page.clear()

    text(42, 790, f"{home['name']} - {away['name']}", 18)
    text(42, 765, report["match"]["score"], 14)
    text(42, 740, f"Formations: {home['formation']} / {away['formation']}", 10)
    text(42, 710, "Team statistics", 13)
    for i, key in enumerate(("possession_pct", "shots", "shots_on_target", "xg", "passes", "pass_accuracy_pct", "tackles_won", "interceptions", "offsides")):
        y = 685 - i * 18
        text(42, y, key.replace("_", " ").title(), 9)
        text(220, y, report["teams"]["home"].get(key, 0), 9)
        text(300, y, report["teams"]["away"].get(key, 0), 9)
    text(42, 505, "Momentum", 13)
    chart = report["momentum_chart"]["points"]
    line(42, 400, 550, 400, (0.7, 0.7, 0.7))
    line(42, 350, 550, 350, (0.85, 0.85, 0.85))
    home_color = _rgb(report["momentum_chart"]["home_color"])
    away_color = _rgb(report["momentum_chart"]["away_color"])
    for previous, current in zip(chart, chart[1:]):
        x1 = 42 + 508 * previous["t"] / max(1, report["match"]["duration_seconds"])
        x2 = 42 + 508 * current["t"] / max(1, report["match"]["duration_seconds"])
        y1 = 375 + 45 * previous["v"]
        y2 = 375 + 45 * current["v"]
        line(x1, y1, x2, y2, home_color if current["v"] >= 0 else away_color)
    text(42, 330, home["short"], 9, home_color)
    text(500, 330, away["short"], 9, away_color)
    finish()

    def pitch(title: str, items: list[tuple[float, float, str, tuple[float, float, float]]]) -> None:
        text(42, 790, title, 15)
        ox, oy, pw, ph = 42, 500, 508, 260
        line(ox, oy, ox + pw, oy, (0.1, 0.35, 0.15))
        line(ox, oy + ph, ox + pw, oy + ph, (0.1, 0.35, 0.15))
        line(ox, oy, ox, oy + ph, (0.1, 0.35, 0.15))
        line(ox + pw, oy, ox + pw, oy + ph, (0.1, 0.35, 0.15))
        line(ox + pw / 2, oy, ox + pw / 2, oy + ph, (0.5, 0.5, 0.5))
        for x, y, label, color in items:
            cx, cy = ox + pw * x / 105, oy + ph * y / 68
            page.extend([f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg", f"{cx - 3:.1f} {cy - 3:.1f} 6 6 re f"])
            text(cx + 5, cy, label, 6, color)
        finish()

    pitch("Shot map", [(shot["x"], shot["y"], shot.get("player", ""), home_color if shot["team"] == "home" else away_color) for shot in report["shots"]])
    pitch("Average positions", [(p["x"], p["y"], p["player"], home_color if p["team"] == home["short"] else away_color) for p in report["average_positions"]])
    return _build_pdf(pages)


def _build_pdf(pages: list[list[str]]) -> bytes:
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_refs = []
    for page in pages:
        stream = "\n".join(page).encode("latin-1", "replace")
        content_id = len(objects) + 1
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        page_id = len(objects) + 1
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode())
        page_refs.append(f"{page_id} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(page_refs)}] /Count {len(page_refs)} >>".encode()
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    body.extend("".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:]).encode())
    body.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(body)

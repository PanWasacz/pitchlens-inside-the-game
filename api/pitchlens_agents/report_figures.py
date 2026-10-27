"""PNG figures for the LaTeX match report: shot map, average formations, heat maps, momentum.

Build-time only (scripts/build_reports.py): needs matplotlib and numpy, which the
production server does not. Pitch orientation matches the studio: x along the
length (home attacks +x), y = 0 is the far touchline at the top.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Arc, Circle, Rectangle  # noqa: E402

from .match import Match, clock  # noqa: E402

GRASS = "#2e7d3a"
GRASS_DARK = "#2a7135"
LINE = "#f4f6f2"
DPI = 200


def _team_colour(m: Match, key: str) -> str:
    return m.team(key)["colors"]["primary"]


def _pitch(ax, m: Match, dim: float = 1.0) -> None:
    """Pitch markings in metres; `dim` < 1 fades the grass so data reads on top."""
    L, W = m.length, m.width
    ax.add_patch(Rectangle((-4, -4), L + 8, W + 8, color=GRASS_DARK, zorder=0))
    for i in range(14):
        if i % 2 == 0:
            ax.add_patch(Rectangle((i * L / 14, 0), L / 14, W, color=GRASS, zorder=0))
    if dim < 1:
        ax.add_patch(Rectangle((-4, -4), L + 8, W + 8, color="white", alpha=1 - dim, zorder=0.5))
    kw = dict(color=LINE, lw=1.4, zorder=1)
    ax.plot([0, L, L, 0, 0], [0, 0, W, W, 0], **kw)
    ax.plot([L / 2, L / 2], [0, W], **kw)
    ax.add_patch(Circle((L / 2, W / 2), 9.15, fill=False, ec=LINE, lw=1.4, zorder=1))
    arc = np.degrees(np.arccos(5.5 / 9.15))
    for gx, s in ((0, 1), (L, -1)):
        ax.plot([gx, gx + s * 16.5, gx + s * 16.5, gx], [W / 2 - 20.16, W / 2 - 20.16, W / 2 + 20.16, W / 2 + 20.16], **kw)
        ax.plot([gx, gx + s * 5.5, gx + s * 5.5, gx], [W / 2 - 9.16, W / 2 - 9.16, W / 2 + 9.16, W / 2 + 9.16], **kw)
        ax.plot([gx, gx - s * 1.6, gx - s * 1.6, gx], [W / 2 - 3.66, W / 2 - 3.66, W / 2 + 3.66, W / 2 + 3.66], **kw)
        ax.add_patch(Circle((gx + s * 11, W / 2), 0.35, color=LINE, zorder=1))
        theta = (-arc, arc) if s > 0 else (180 - arc, 180 + arc)
        ax.add_patch(Arc((gx + s * 11, W / 2), 18.3, 18.3, theta1=theta[0], theta2=theta[1], ec=LINE, lw=1.4, zorder=1))
    ax.add_patch(Circle((L / 2, W / 2), 0.35, color=LINE, zorder=1))
    ax.set_xlim(-4, L + 4)
    ax.set_ylim(W + 4, -4)  # y = 0 (far touchline) at the top, as in the studio
    ax.set_aspect("equal")
    ax.axis("off")


def _attack_arrows(ax, m: Match) -> None:
    for key in ("home", "away"):
        d = m.attack_dir(key)
        x0 = m.length / 2 - d * 14
        y = m.width + 2.6 if key == "home" else -2.6
        ax.annotate("", xy=(x0 + d * 28, y), xytext=(x0, y),
                    arrowprops=dict(arrowstyle="-|>", color=_team_colour(m, key), lw=2))
        ax.text(x0 + d * 30, y, f"{m.short(key)} attack", color=_team_colour(m, key), fontsize=8,
                va="center", ha="left" if d > 0 else "right", fontweight="bold")


def _figure():
    fig, ax = plt.subplots(figsize=(10, 6.9))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    return fig, ax


def shot_map(m: Match, path: Path) -> None:
    fig, ax = _figure()
    _pitch(ax, m)
    _attack_arrows(ax, m)
    style = {"goal": ("*", 1.0), "saved": ("o", 0.9), "blocked": ("X", 0.8), "off_target": ("o", 0.45)}
    labelled: list[tuple[float, float]] = []
    for e in (e for e in m.events if e["type"] == "shot"):
        colour = _team_colour(m, e["team"])
        marker, alpha = style.get(e.get("outcome"), ("o", 0.6))
        size = 90 + 900 * e.get("xg", 0.0) if marker != "*" else 520
        hollow = e.get("outcome") == "off_target"
        ax.scatter(e["x"], e["y"], s=size, marker=marker, zorder=4, alpha=alpha,
                   c="none" if hollow else colour, edgecolors=colour if hollow else "white", linewidths=1.6)
        if e.get("outcome") == "goal":
            # Goals scored from nearby spots get their labels stacked instead of overlapping.
            near = sum(1 for (x, y) in labelled if abs(x - e["x"]) < 12 and abs(y - e["y"]) < 6)
            labelled.append((e["x"], e["y"]))
            ax.annotate(f"{m.name(e['player'])}  {clock(e['t'])}", (e["x"], e["y"]), xytext=(0, -16 - 15 * near),
                        textcoords="offset points", ha="center", fontsize=8, color="white", fontweight="bold", zorder=5,
                        bbox=dict(boxstyle="round,pad=0.25", fc=colour, ec="none", alpha=0.95))
    handles = [
        plt.Line2D([], [], marker="*", ls="", ms=14, mfc="#bbbbbb", mec="white", label="Goal"),
        plt.Line2D([], [], marker="o", ls="", ms=9, mfc="#bbbbbb", mec="white", label="Saved"),
        plt.Line2D([], [], marker="X", ls="", ms=9, mfc="#bbbbbb", mec="white", label="Blocked"),
        plt.Line2D([], [], marker="o", ls="", ms=9, mfc="none", mec="#dddddd", label="Off target"),
    ]
    ax.legend(handles=handles, loc="lower center", ncol=4, frameon=True, fontsize=8, bbox_to_anchor=(0.5, 0.02),
              facecolor="#1b4d24", edgecolor="none", labelcolor="white")
    ax.text(m.length / 2, 2.2, "marker size = xG", color="white", fontsize=7, ha="center", alpha=0.8)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def average_positions(m: Match) -> dict[str, dict]:
    """Mean position over the frames each player is on the pitch, with their share of frames."""
    acc: dict[str, list[float]] = {pid: [0.0, 0.0, 0] for pid in m.players}
    for fr in m.frames:
        for p in fr["players"]:
            if p["id"] in acc:
                a = acc[p["id"]]
                a[0] += p["x"]
                a[1] += p["y"]
                a[2] += 1
    n = max(1, len(m.frames))
    return {pid: {"x": a[0] / a[2], "y": a[1] / a[2], "share": a[2] / n}
            for pid, a in acc.items() if a[2]}


def formation_map(m: Match, key: str, path: Path) -> None:
    fig, ax = _figure()
    _pitch(ax, m, dim=0.8)
    _attack_arrows(ax, m)
    colour = _team_colour(m, key)
    team = m.team(key)
    avg = average_positions(m)
    players = [p for p in team["players"] if p["id"] in avg and avg[p["id"]]["share"] > 0.2]
    # Link each line of the formation (defence, midfield, attack) across the pitch.
    for role in ("DF", "MF", "FW"):
        line = sorted((avg[p["id"]] for p in players if p.get("role") == role), key=lambda a: a["y"])
        if len(line) > 1:
            ax.plot([a["x"] for a in line], [a["y"] for a in line], color=colour, lw=2.5, alpha=0.55, zorder=2)
    for p in players:
        a = avg[p["id"]]
        gk = p.get("role") == "GK"
        fill = team["colors"]["goalkeeper"] if gk else colour
        ax.add_patch(Circle((a["x"], a["y"]), 2.3, fc=fill, ec="white", lw=1.8, zorder=3))
        ax.text(a["x"], a["y"], str(p.get("number") or ""), ha="center", va="center", fontsize=9,
                fontweight="bold", color="black" if gk else "white", zorder=4)
        label = f"{p.get('name') or p['id']}" + (f"  ({p['position']})" if p.get("position") else "")
        ax.text(a["x"], a["y"] + 4.2, label, ha="center", va="top", fontsize=7, color="white", zorder=4,
                bbox=dict(boxstyle="round,pad=0.2", fc="#0b1a10", ec="none", alpha=0.75))
    formation = team.get("formation") or ""
    ax.text(1, 2.5, f"{team['name']}  {formation}", fontsize=11, fontweight="bold", color="white", va="center",
            bbox=dict(boxstyle="round,pad=0.35", fc=colour, ec="none"))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def _blur(grid: np.ndarray, sigma: float) -> np.ndarray:
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    grid = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 0, grid)
    return np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 1, grid)


def heat_map(m: Match, key: str, path: Path) -> None:
    fig, ax = _figure()
    _pitch(ax, m, dim=0.55)
    _attack_arrows(ax, m)
    gk = {p["id"] for p in m.team(key)["players"] if p.get("role") == "GK"}
    xs, ys = [], []
    for fr in m.frames:
        for p in fr["players"]:
            if p["team"] == key and p["id"] not in gk:
                xs.append(p["x"])
                ys.append(p["y"])
    grid, _, _ = np.histogram2d(ys, xs, bins=(int(m.width), int(m.length)), range=((0, m.width), (0, m.length)))
    grid = _blur(grid, 2.5)
    grid = grid / grid.max() if grid.max() > 0 else grid
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
        "team", [(1, 1, 1, 0), (*matplotlib.colors.to_rgb(_team_colour(m, key)), 0.55), (1.0, 0.85, 0.2, 0.9)])
    ax.imshow(grid, extent=(0, m.length, m.width, 0), cmap=cmap, interpolation="bilinear", zorder=2, vmin=0, vmax=1)
    team = m.team(key)
    ax.text(1, 2.5, f"{team['name']}  time spent (outfield players)", fontsize=11, fontweight="bold",
            color="white", va="center", bbox=dict(boxstyle="round,pad=0.35", fc=_team_colour(m, key), ec="none"))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def momentum_chart(m: Match, report: dict, path: Path) -> None:
    pts = report["momentum_chart"]["points"]
    t = np.array([p["t"] for p in pts], float) / 60
    v = np.array([p["v"] for p in pts], float) * 100
    # The live 15 s window is too jumpy on paper: smooth to about a minute.
    smooth = 45
    if len(v) > smooth:
        k = np.ones(smooth) / smooth
        v = np.convolve(np.pad(v, smooth // 2, mode="edge"), k, mode="valid")[: len(t)]
    home, away = _team_colour(m, "home"), _team_colour(m, "away")
    fig, ax = plt.subplots(figsize=(10, 3.6))
    fig.subplots_adjust(left=0.07, right=0.99, top=0.9, bottom=0.17)
    ax.fill_between(t, 0, v, where=v >= 0, color=home, alpha=0.75, interpolate=True, lw=0)
    ax.fill_between(t, 0, v, where=v < 0, color=away, alpha=0.75, interpolate=True, lw=0)
    ax.plot(t, v, color="#333333", lw=0.8)
    ax.axhline(0, color="#555555", lw=0.8)
    for e in (e for e in m.events if e["type"] == "goal"):
        x = e["t"] / 60
        up = e["team"] == "home"
        ax.axvline(x, color="#222222", lw=0.9, ls="--", alpha=0.7)
        ax.text(x, 96 if up else -96, f" {m.name(e['scorer'])} {clock(e['t'])}", fontsize=7.5,
                va="top" if up else "bottom", ha="left", color=_team_colour(m, e["team"]), fontweight="bold")
    ax.set_ylim(-100, 100)
    ax.set_xlim(t[0], t[-1])
    ax.set_yticks([-100, -50, 0, 50, 100])
    ax.set_yticklabels([f"{m.short('away')} 100%", "50%", "0", "50%", f"{m.short('home')} 100%"], fontsize=8)
    ax.set_xlabel("Match time (minutes)", fontsize=9)
    ax.set_title(f"Momentum: possession balance, smoothed over about a minute "
                 f"({m.short('home')} up, {m.short('away')} down)", fontsize=10)
    ax.grid(axis="x", alpha=0.3)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def render_figures(m: Match, report: dict, out: Path) -> dict[str, str]:
    """Write every figure into `out`; returns {name: file name} for the LaTeX document."""
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "momentum": "momentum.png",
        "shots": "map_shots.png",
        "formation_home": "map_formation_home.png",
        "formation_away": "map_formation_away.png",
        "heat_home": "map_heat_home.png",
        "heat_away": "map_heat_away.png",
    }
    momentum_chart(m, report, out / files["momentum"])
    shot_map(m, out / files["shots"])
    formation_map(m, "home", out / files["formation_home"])
    formation_map(m, "away", out / files["formation_away"])
    heat_map(m, "home", out / files["heat_home"])
    heat_map(m, "away", out / files["heat_away"])
    return files

"""LaTeX export for deterministic PitchLens match reports."""

from __future__ import annotations

import json
from typing import Any


def _tex(value: Any) -> str:
    return str(value).replace("\\", r"\textbackslash{}").replace("&", r"\&").replace("%", r"\%").replace("_", r"\_").replace("#", r"\#").replace("{", r"\{").replace("}", r"\}")


def render_tex(report: dict) -> str:
    match = report["match"]
    home, away = match["home"], match["away"]
    teams = report["teams"]
    lines = [
        r"\documentclass[a4paper,10pt]{article}",
        r"\usepackage[margin=1.5cm]{geometry}",
        r"\usepackage{booktabs,graphicx,tikz,pgfplots,xcolor}",
        r"\pgfplotsset{compat=1.18}",
        r"\usetikzlibrary{patterns,positioning}",
        r"\title{" + _tex(f"{home['name']} - {away['name']}") + "}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
        r"\begin{center}\Large " + _tex(match["score"]) + r"\end{center}",
        r"\section*{Team statistics}",
        r"\begin{tabular}{lrr}\toprule Statistic & " + _tex(home["short"]) + " & " + _tex(away["short"]) + r"\\\midrule",
    ]
    labels = [("possession_pct", "Possession"), ("shots", "Shots"), ("shots_on_target", "On target"), ("xg", "xG"), ("passes", "Passes"), ("pass_accuracy_pct", "Pass accuracy"), ("tackles_won", "Tackles won"), ("interceptions", "Interceptions"), ("offsides", "Offsides")]
    for key, label in labels:
        suffix = r"\%" if key.endswith("_pct") else ""
        lines.append(f"{label} & {teams['home'].get(key, 0)}{suffix} & {teams['away'].get(key, 0)}{suffix}\\\\")
    lines += [
        r"\bottomrule\end{tabular}",
        r"\section*{Momentum}",
        r"\begin{tikzpicture}",
        r"\begin{axis}[width=\textwidth,height=6cm,ymin=0,ymax=100,xlabel={Match time},ylabel={Control (\%)},legend style={at={(0.5,-0.2)},anchor=north},grid=major]",
        r"\addplot coordinates {",
    ]
    for i, spell in enumerate(report["momentum"]["spells"]):
        x = i + 0.5
        keys = [key for key in spell if key.endswith("_control")]
        lines.append(f"({x},{spell.get(keys[0], 0) if keys else 0})")
    lines += [r"};\addlegendentry{" + _tex(home["short"]) + r"}", r"\addplot coordinates {"]
    for i, spell in enumerate(report["momentum"]["spells"]):
        x = i + 0.5
        keys = [key for key in spell if key.endswith("_control")]
        lines.append(f"({x},{spell.get(keys[1], 0) if len(keys) > 1 else 0})")
    lines += [r"};\addlegendentry{" + _tex(away["short"]) + r"}", r"\end{axis}\end{tikzpicture}"]
    lines += [r"\section*{Shot map}", r"\begin{tikzpicture}[x=0.1cm,y=0.1cm]", r"\draw[green!50!black,fill=green!8] (0,0) rectangle (105,68);", r"\draw (52.5,0)--(52.5,68);"]
    for shot in report["shots"]:
        color = "blue" if shot["team"] == "home" else "red"
        marker = "star" if shot["outcome"] == "goal" else "circle"
        lines.append(rf"\node[{color},fill={color}!20,draw,shape={marker},inner sep=1.5pt] at ({shot['x']},{shot['y']}) {{}};")
    lines += [r"\end{tikzpicture}", r"\section*{Average formations}", r"\begin{tikzpicture}[x=0.1cm,y=0.1cm]", r"\draw[green!50!black,fill=green!8] (0,0) rectangle (105,68);"]
    for position in report["average_positions"]:
        color = "blue" if position["team"] == home["short"] else "red"
        lines.append(rf"\fill[{color}] ({position['x']},{position['y']}) circle (1.2pt);")
        lines.append(rf"\node[font=\tiny,anchor=south] at ({position['x']},{position['y']}) {{{_tex(position['player'])}}};")
    lines += [r"\end{tikzpicture}", r"\section*{Position heat map}", r"\begin{tikzpicture}[x=0.1cm,y=0.1cm]", r"\draw[green!50!black,fill=green!8] (0,0) rectangle (105,68);"]
    heat = report["heatmap"]
    peak = max(max(row) for team in heat.values() for row in team) or 1
    for team, color in (("home", "blue"), ("away", "red")):
        for row, values in enumerate(heat[team]):
            for col, value in enumerate(values):
                opacity = 0.08 + 0.42 * value / peak
                lines.append(rf"\fill[{color}!{max(10, round(opacity * 100))}] ({col * 15},{row * 17}) rectangle ({(col + 1) * 15},{(row + 1) * 17});")
    lines += [r"\end{tikzpicture}", r"\section*{Key moments}", r"\begin{itemize}"]
    for event in report["key_moments"]:
        lines.append(r"\item " + _tex(f"{event.get('clock', '')} - {event.get('type', '')} - {event.get('player', '')}"))
    lines += [r"\end{itemize}", r"\end{document}", ""]
    return "\n".join(lines)

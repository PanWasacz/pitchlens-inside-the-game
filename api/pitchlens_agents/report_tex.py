"""LaTeX export for deterministic PitchLens match reports (PitchLens report template).

The document references PNG figures produced by report_figures.py
(scripts/build_reports.py writes both into one folder, ready for pdflatex or Overleaf).
"""

from __future__ import annotations

from datetime import date
from typing import Any

DEFAULT_FIGURES = {
    "momentum": "momentum.png",
    "shots": "map_shots.png",
    "formation_home": "map_formation_home.png",
    "formation_away": "map_formation_away.png",
    "heat_home": "map_heat_home.png",
    "heat_away": "map_heat_away.png",
}

PREAMBLE = r"""\UseRawInputEncoding
\documentclass[12pt, a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[polish]{babel}
\usepackage[a4paper, left=2.5cm, right=2.5cm, top=2.5cm, bottom=2.5cm]{geometry}
\usepackage{graphicx,subcaption}
\usepackage{float}
\usepackage{listings}
\usepackage{xcolor}

\definecolor{codegray}{gray}{0.95}
\definecolor{codegreen}{rgb}{0,0.6,0}
\definecolor{codeblue}{rgb}{0,0,0.8}
\definecolor{codered}{rgb}{0.6,0,0}

\lstdefinestyle{mystyle}{
backgroundcolor=\color{codegray},
commentstyle=\color{codegreen},
keywordstyle=\color{codeblue}\bfseries,
numberstyle=\tiny\color{gray},
stringstyle=\color{codered},
basicstyle=\ttfamily\footnotesize,
frame=single,
numbers=left,
numbersep=6pt,
breaklines=true,
showstringspaces=false,
}

\lstset{style=mystyle,language=C++}
"""


def _tex(value: Any) -> str:
    text = str(value)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#"),
                 ("{", r"\{"), ("}", r"\}"), ("$", r"\$"), ("^", r"\^{}"), ("~", r"\~{}")):
        text = text.replace(a, b)
    return text


def _figure(file: str, caption: str, width: str = "0.95") -> list[str]:
    return [
        r"\begin{figure}[H]",
        r"\centering",
        rf"\includegraphics[width={width}\textwidth]{{{file}}}",
        rf"\caption{{{caption}}}",
        r"\end{figure}",
        "",
    ]


def render_tex(report: dict, figures: dict[str, str] | None = None, generated: str | None = None) -> str:
    figures = figures or DEFAULT_FIGURES
    match = report["match"]
    home, away = match["home"], match["away"]
    teams = report["teams"]
    hs, as_ = _tex(home["short"]), _tex(away["short"])
    lines = [
        PREAMBLE,
        rf"\title{{MATCH RAPORT {_tex(home['name'])} vs {_tex(away['name'])}}}",
        r"\author{PitchLens - The Boys AGH platform }",
        rf"\date{{{_tex(generated or date.today().isoformat())}}}",
        "",
        r"\begin{document}",
        r"\maketitle",
        "",
        r"\begin{center}",
        rf"{{\Huge\bfseries {_tex(match['score'])}}}\\[4pt]",
        rf"{_tex(home['name'])} ({_tex(home.get('formation') or '-')}) vs {_tex(away['name'])} ({_tex(away.get('formation') or '-')})"
        rf"\\ Match length: {_tex(match['duration'])}",
        r"\end{center}",
        "",
        r"\section{Statistics}",
        "",
        r"\subsection{Team statistics}",
        r"\begin{table}[H]",
        r"\centering",
        r"\begin{tabular}{lrr}",
        r"\hline",
        rf"\textbf{{Statistic}} & \textbf{{{hs}}} & \textbf{{{as_}}} \\",
        r"\hline",
    ]
    rows = [("possession_pct", "Possession", r"\%"), ("goals", "Goals", ""), ("shots", "Shots", ""),
            ("shots_on_target", "Shots on target", ""), ("xg", "Expected goals (xG)", ""), ("passes", "Passes", ""),
            ("pass_accuracy_pct", "Pass accuracy", r"\%"), ("tackles_won", "Tackles won", ""),
            ("interceptions", "Interceptions", ""), ("offsides", "Offsides", "")]
    for key, label, unit in rows:
        lines.append(rf"{label} & {_tex(teams['home'].get(key, 0))}{unit} & {_tex(teams['away'].get(key, 0))}{unit} \\")
    lines += [r"\hline", r"\end{tabular}", r"\caption{Team statistics for the whole match.}", r"\end{table}", ""]

    goals = report.get("goals") or []
    if goals:
        lines += [r"\subsection{Goals}", r"\begin{table}[H]", r"\centering", r"\begin{tabular}{llll}", r"\hline",
                  r"\textbf{Time} & \textbf{Team} & \textbf{Scorer} & \textbf{Assist} \\", r"\hline"]
        for g in goals:
            lines.append(rf"{_tex(g.get('clock', ''))} & {_tex(g.get('team', ''))} & {_tex(g.get('scorer', ''))} & {_tex(g.get('assist', '-'))} \\")
        lines += [r"\hline", r"\end{tabular}", r"\caption{Goals with scorers and assists.}", r"\end{table}", ""]

    players = report.get("players") or []
    if players:
        top = sorted(players, key=lambda p: (p.get("goals", 0), p.get("shots", 0), p.get("distance_km", 0)), reverse=True)[:12]
        lines += [r"\subsection{Players}", r"\begin{table}[H]", r"\centering", r"\small", r"\setlength{\tabcolsep}{4pt}",
                  r"\begin{tabular}{llrrrrrr}", r"\hline",
                  r"\textbf{Player} & \textbf{Team} & \textbf{km} & \textbf{Top km/h} & \textbf{Sprints} & "
                  r"\textbf{Passes} & \textbf{Shots} & \textbf{Goals} \\", r"\hline"]
        for p in top:
            acc = p.get("pass_accuracy_pct")
            passes = f"{p.get('passes', 0)}" + (f" ({acc}\\%)" if acc is not None else "")
            lines.append(rf"{_tex(p.get('number', ''))} {_tex(p.get('player', ''))} ({_tex(p.get('position', ''))}) & "
                         rf"{_tex(p.get('team', ''))} & {p.get('distance_km', 0)} & {p.get('top_speed_kmh', 0)} & "
                         rf"{p.get('sprints', 0)} & {passes} & {p.get('shots', 0)} & {p.get('goals', 0)} \\")
        lines += [r"\hline", r"\end{tabular}",
                  r"\caption{Key players: goals, shots and work rate (distance, top speed, sprints).}", r"\end{table}", ""]

    lines += [r"\subsection{Momentum}", ""]
    lines += _figure(figures["momentum"],
                     rf"Momentum: possession balance, smoothed over about a minute. Above the axis {hs} controls the game, "
                     rf"below {as_}. Dashed lines mark the goals.", "1.0")

    lines += [r"\section{Maps}", ""]
    lines += _figure(figures["shots"],
                     "Shot map. Marker size shows the chance quality (xG); stars are goals, hollow markers missed the target.")
    lines += _figure(figures["formation_home"],
                     rf"{_tex(home['name'])}: average positions with shirt numbers, names and positions "
                     rf"(formation {_tex(home.get('formation') or '-')}).")
    lines += _figure(figures["formation_away"],
                     rf"{_tex(away['name'])}: average positions with shirt numbers, names and positions "
                     rf"(formation {_tex(away.get('formation') or '-')}).")
    lines += _figure(figures["heat_home"], rf"{_tex(home['name'])}: heat map of where the outfield players spent their time.")
    lines += _figure(figures["heat_away"], rf"{_tex(away['name'])}: heat map of where the outfield players spent their time.")

    moments = report.get("key_moments") or []
    goal_clocks = {e.get("clock") for e in moments if e.get("type") == "goal"}
    if moments:
        lines += [r"\section{Key moments}", r"\begin{itemize}"]
        for e in moments:
            if e.get("type") == "shot" and e.get("clock") in goal_clocks:
                continue  # the goal row tells the same story
            who = e.get("player") or e.get("scorer")
            kind = str(e.get("type", "")).replace("_", " ").upper()
            text = _tex(" - ".join(str(v) for v in (e.get("clock"), kind, who) if v))
            lines.append(r"\item " + (rf"\textbf{{{text}}}" if e.get("type") == "goal" else text))
        lines += [r"\end{itemize}", ""]

    lines += [r"\end{document}", ""]
    return "\n".join(lines)

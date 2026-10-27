"""Deterministic match tools. They compute every number the agents may use;
the language model never does arithmetic. Each result becomes a fact (f1, f2, ...)
in the shared session state, which later agents cite and the Verifier checks."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .match import Match, clock

SPRINT_MS = 7.0  # m/s (25.2 km/h)
SPRINT_MIN_S = 1.0
MAX_WINDOW_S = 60.0
MAX_EVENTS = 15


def r1(v: float) -> float:
    return round(float(v), 1)


# ---------------------------------------------------------------- fact store


@dataclass
class Fact:
    id: str
    tool: str
    args: dict
    data: dict
    label: str
    t: float | None = None

    def public(self) -> dict:
        return {"id": self.id, "tool": self.tool, "args": self.args, "data": self.data}


@dataclass
class FactStore:
    facts: list[Fact] = field(default_factory=list)

    def add(self, tool: str, args: dict, data: dict, label: str, t: float | None = None) -> Fact:
        fact = Fact(f"f{len(self.facts) + 1}", tool, args, data, label, t)
        self.facts.append(fact)
        return fact

    def get(self, fid: str) -> Fact | None:
        return next((f for f in self.facts if f.id == fid), None)

    def pick(self, ids: list[str]) -> list[Fact]:
        return [f for f in self.facts if f.id in set(ids)]


# ---------------------------------------------------------------- tools


def _event_row(m: Match, e: dict) -> dict:
    row = {
        "event_id": e["id"],
        "clock": clock(e["t"]),
        "type": e["type"],
        "team": m.short(e.get("team")),
        "player": m.name(e.get("player")),
    }
    kind = e["type"]
    if kind == "pass":
        row["receiver"] = m.name(e.get("receiver"))
        row["outcome"] = e.get("outcome")
        row["through_ball"] = bool(e.get("through_ball"))
        row["lofted"] = bool(e.get("lofted"))
        row["length_m"] = r1(math.hypot(e["end_x"] - e["x"], e["end_y"] - e["y"]))
    elif kind == "shot":
        row["outcome"] = e.get("outcome")
        row["xg"] = round(e["xg"], 2)
        row["xg_pct"] = round(100 * e["xg"])
        row["assist"] = m.name(e.get("assist"))
        row["distance_to_goal_m"] = r1(_goal_distance(m, e))
    elif kind == "goal":
        row["scorer"] = m.name(e.get("scorer"))
        row["assist"] = m.name(e.get("assist"))
        row["score"] = f"{m.short('home')} {e['score']['home']}-{e['score']['away']} {m.short('away')}"
    elif kind == "save":
        row["shooter"] = m.name(e.get("shooter"))
    elif kind == "tackle":
        row["opponent"] = m.name(e.get("opponent"))
        row["outcome"] = e.get("outcome")
    elif kind == "interception":
        row["passer"] = m.name(e.get("passer"))
    elif kind == "offside":
        row["passer"] = m.name(e.get("passer"))
    return {k: v for k, v in row.items() if v is not None}


def _goal_distance(m: Match, e: dict) -> float:
    gx = m.length if m.attack_dir(e["team"]) == 1 else 0.0
    return math.hypot(gx - e["x"], m.width / 2 - e["y"])


def match_context(m: Match, t: float) -> tuple[dict, str]:
    fr = m.frame_at(t)
    score = m.score_at(t)
    home, away = m.team("home"), m.team("away")
    data = {
        "clock": clock(t),
        "home": {"name": home["name"], "short": home["short"], "formation": home["formation"]},
        "away": {"name": away["name"], "short": away["short"], "formation": away["formation"]},
        "score": f"{home['short']} {score['home']}-{score['away']} {away['short']}",
        "in_possession": m.short(fr.get("possession")),
    }
    return data, f"{data['score']} at {data['clock']}"


def get_events(m: Match, t_from: float, t_to: float) -> tuple[dict, str]:
    t_from, t_to = sorted((float(t_from), float(t_to)))
    t_from = max(t_from, t_to - MAX_WINDOW_S)
    rows = [_event_row(m, e) for e in m.events if t_from <= e["t"] <= t_to and e["type"] != "possession_change"]
    data = {"from": clock(t_from), "to": clock(t_to), "events": rows[-MAX_EVENTS:]}
    return data, f"{len(data['events'])} events {data['from']}-{data['to']}"


def get_player_stats(m: Match, player_id: str, t: float) -> tuple[dict, str]:
    p = m.players.get(player_id)
    if p is None:
        raise ValueError(f"unknown player id {player_id!r}")
    last = m.frame_index(t)
    top = 0.0
    dist = 0.0
    sprints = 0
    run = 0.0
    step = 1.0 / m.fps
    for fr in m.frames[: last + 1]:
        me = next((q for q in fr["players"] if q["id"] == player_id), None)
        if me is None:
            continue
        top = max(top, me["speed"])
        dist = me["dist"]
        if me["speed"] >= SPRINT_MS:
            run += step
        else:
            if run >= SPRINT_MIN_S:
                sprints += 1
            run = 0.0
    if run >= SPRINT_MIN_S:
        sprints += 1
    passes = [e for e in m.events if e["type"] == "pass" and e.get("player") == player_id and e["t"] <= t]
    done = sum(1 for e in passes if e.get("outcome") == "complete")
    shots = [e for e in m.events if e["type"] == "shot" and e.get("player") == player_id and e["t"] <= t]
    elapsed = max(m.times[last], step)
    data = {
        "player": p["name"],
        "number": p["number"],
        "team": m.short(p["team"]),
        "position": p["position"],
        "until": clock(t),
        "distance_km": round(dist / 1000, 2),
        "top_speed_kmh": r1(top * 3.6),
        "avg_speed_kmh": r1(dist / elapsed * 3.6),
        "sprints": sprints,
        "passes": len(passes),
        "passes_completed": done,
        "pass_accuracy_pct": round(100 * done / len(passes)) if passes else None,
        "shots": len(shots),
        "goals": sum(1 for e in shots if e.get("outcome") == "goal"),
    }
    data = {k: v for k, v in data.items() if v is not None}
    return data, f"{p['name']}: {data['distance_km']} km, top {data['top_speed_kmh']} km/h"


def get_team_shape(m: Match, team: str, t: float) -> tuple[dict, str]:
    if team not in ("home", "away"):
        raise ValueError("team must be 'home' or 'away'")
    fr = m.frame_at(t)
    outfield = [q for q in fr["players"] if q["team"] == team and m.players[q["id"]]["role"] != "GK"]
    if len(outfield) < 3:
        raise ValueError("not enough players visible")
    depth = {q["id"]: m.depth_from_own_goal(team, q["x"]) for q in outfield}
    defenders = [q for q in outfield if m.players[q["id"]]["role"] == "DF"] or sorted(outfield, key=lambda q: depth[q["id"]])[:4]
    cx = sum(q["x"] for q in outfield) / len(outfield)
    cy = sum(q["y"] for q in outfield) / len(outfield)
    data = {
        "team": m.short(team),
        "clock": clock(t),
        "in_possession": fr.get("possession") == team,
        "defensive_line_m_from_own_goal": r1(sum(depth[q["id"]] for q in defenders) / len(defenders)),
        "block_length_m": r1(max(depth.values()) - min(depth.values())),
        "block_width_m": r1(max(q["y"] for q in outfield) - min(q["y"] for q in outfield)),
        "avg_distance_to_centre_m": r1(sum(math.hypot(q["x"] - cx, q["y"] - cy) for q in outfield) / len(outfield)),
    }
    return data, f"{data['team']} shape: line {data['defensive_line_m_from_own_goal']} m, block {data['block_length_m']}x{data['block_width_m']} m"


def get_offside_state(m: Match, t: float, defending: str | None = None) -> tuple[dict, str]:
    fr = m.frame_at(t)
    if defending not in ("home", "away"):
        poss = fr.get("possession")
        defending = m.other(poss) if poss else ("home" if fr["ball"]["x"] < m.length / 2 else "away")
    attacking = m.other(defending)
    goal_side = -m.attack_dir(defending)  # +1 when the defending goal is at x = length
    defs = sorted(
        (q for q in fr["players"] if q["team"] == defending), key=lambda q: q["x"] * goal_side, reverse=True
    )
    second_last = defs[1]
    line = second_last["x"] * goal_side
    reason = "second-last defender"
    if fr["ball"]["x"] * goal_side > line:
        line, reason = fr["ball"]["x"] * goal_side, "ball"
    if (m.length / 2) * goal_side > line:
        line, reason = (m.length / 2) * goal_side, "halfway line"
    goal_x = m.length if goal_side == 1 else 0.0
    attackers = sorted(
        (q for q in fr["players"] if q["team"] == attacking),
        key=lambda q: q["x"] * goal_side,
        reverse=True,
    )[:3]
    rows = [
        {
            "player": q["name"],
            "metres_beyond_line": r1(q["x"] * goal_side - line),
            "offside_position": q["x"] * goal_side - line > 0.05,
        }
        for q in attackers
    ]
    data = {
        "clock": clock(t),
        "defending": m.short(defending),
        "attacking": m.short(attacking),
        "line_set_by": reason,
        "second_last_defender": second_last["name"],
        "line_m_from_defending_goal": r1(abs(goal_x - line * goal_side)),
        "deepest_attackers": rows,
        "attackers_in_offside_position": sum(1 for r in rows if r["offside_position"]),
    }
    return data, f"Offside line at {data['clock']}: {data['line_m_from_defending_goal']} m from {data['defending']} goal"


def get_possession(m: Match, t_from: float, t_to: float) -> tuple[dict, str]:
    t_from, t_to = sorted((float(t_from), float(t_to)))
    a, b = m.frame_index(t_from), m.frame_index(t_to)
    counts = {"home": 0, "away": 0}
    for fr in m.frames[a : b + 1]:
        if fr.get("possession") in counts:
            counts[fr["possession"]] += 1
    total = counts["home"] + counts["away"]
    if not total:
        raise ValueError("no possession data in this window")
    data = {
        "from": clock(t_from),
        "to": clock(t_to),
        m.short("home") + "_pct": round(100 * counts["home"] / total),
        m.short("away") + "_pct": round(100 * counts["away"] / total),
    }
    return data, f"Possession {data['from']}-{data['to']}"


def get_zone_activity(m: Match, x0: float, y0: float, x1: float, y1: float, t_from: float, t_to: float) -> tuple[dict, str]:
    x0, x1 = sorted((float(x0), float(x1)))
    y0, y1 = sorted((float(y0), float(y1)))
    t_from, t_to = sorted((float(t_from), float(t_to)))
    a, b = m.frame_index(t_from), m.frame_index(t_to)
    frames = m.frames[a : b + 1]
    inside = lambda x, y: x0 <= x <= x1 and y0 <= y <= y1  # noqa: E731
    per_team = {"home": 0, "away": 0}
    ball = 0
    for fr in frames:
        for q in fr["players"]:
            if inside(q["x"], q["y"]):
                per_team[q["team"]] += 1
        if inside(fr["ball"]["x"], fr["ball"]["y"]):
            ball += 1
    n = max(1, len(frames))
    evs = [e for e in m.events if t_from <= e["t"] <= t_to and inside(e["x"], e["y"]) and e["type"] != "possession_change"]
    kinds: dict[str, int] = {}
    for e in evs:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    data = {
        "zone": {"x": [r1(x0), r1(x1)], "y": [r1(y0), r1(y1)]},
        "from": clock(t_from),
        "to": clock(t_to),
        "avg_players_" + m.short("home"): r1(per_team["home"] / n),
        "avg_players_" + m.short("away"): r1(per_team["away"] / n),
        "ball_time_pct": round(100 * ball / n),
        "events": kinds,
    }
    return data, f"Zone activity {data['from']}-{data['to']}"


TOOLS = {
    "get_events": get_events,
    "get_player_stats": get_player_stats,
    "get_team_shape": get_team_shape,
    "get_offside_state": get_offside_state,
    "get_possession": get_possession,
    "get_zone_activity": get_zone_activity,
}


def run_tool(m: Match, store: FactStore, name: str, args: dict, t: float | None = None) -> Fact:
    fn = TOOLS.get(name)
    if fn is None:
        raise ValueError(f"unknown tool {name!r}")
    data, label = fn(m, **args)
    return store.add(name, args, data, label, t)


def player_index(m: Match) -> list[dict]:
    """Compact roster the Analyst uses to pick player ids."""
    return [
        {"id": pid, "name": p["name"], "team": m.short(p["team"]), "position": p["position"]}
        for pid, p in m.players.items()
    ]


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_events",
            "description": "Match events (passes, shots, tackles, offsides...) between two times in seconds. Max 60 s window.",
            "parameters": {
                "type": "object",
                "properties": {"t_from": {"type": "number"}, "t_to": {"type": "number"}},
                "required": ["t_from", "t_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_player_stats",
            "description": "Distance, top and average speed, sprints, passes and shots of one player from kick-off until time t.",
            "parameters": {
                "type": "object",
                "properties": {"player_id": {"type": "string", "description": "e.g. H09 or A10"}, "t": {"type": "number"}},
                "required": ["player_id", "t"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_team_shape",
            "description": "Team shape at time t: defensive line height from own goal, block length and width, compactness.",
            "parameters": {
                "type": "object",
                "properties": {"team": {"type": "string", "enum": ["home", "away"]}, "t": {"type": "number"}},
                "required": ["team", "t"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_offside_state",
            "description": "Offside line at time t: second-last defender, line position and how far the deepest attackers are beyond it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "t": {"type": "number"},
                    "defending": {"type": "string", "enum": ["home", "away"]},
                },
                "required": ["t"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_possession",
            "description": "Possession share of both teams between two times in seconds.",
            "parameters": {
                "type": "object",
                "properties": {"t_from": {"type": "number"}, "t_to": {"type": "number"}},
                "required": ["t_from", "t_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_zone_activity",
            "description": "Players per team, ball time and events inside a pitch rectangle (metres, 105x68) between two times.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x0": {"type": "number"},
                    "y0": {"type": "number"},
                    "x1": {"type": "number"},
                    "y1": {"type": "number"},
                    "t_from": {"type": "number"},
                    "t_to": {"type": "number"},
                },
                "required": ["x0", "y0", "x1", "y1", "t_from", "t_to"],
            },
        },
    },
]

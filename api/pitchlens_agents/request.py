"""Validation of the /api/explain request body (it comes from the public internet)."""

from __future__ import annotations

from .match import Match

MODES = ("analyst", "fan")
TASKS = ("moment", "recap")
LANGS = ("en", "pl", "es")
MAX_ZONES = 3


class BadRequest(ValueError):
    pass


def _num(v, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise BadRequest(f"{name} must be a number")
    return float(v)


def parse_request(body, m: Match) -> dict:
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    t = min(max(_num(body.get("t"), "t"), 0.0), m.duration)
    event_id = body.get("event_id")
    if event_id is not None and (isinstance(event_id, bool) or not isinstance(event_id, int)):
        raise BadRequest("event_id must be an integer")
    task = body.get("task", "moment")
    if task not in TASKS:
        raise BadRequest(f"task must be one of {', '.join(TASKS)}")
    mode = body.get("mode", "analyst")
    lang = body.get("lang", "en")
    team = body.get("team") or None
    player = body.get("player") or None
    if mode not in MODES:
        raise BadRequest(f"mode must be one of {', '.join(MODES)}")
    if lang not in LANGS:
        raise BadRequest(f"lang must be one of {', '.join(LANGS)}")
    if team not in (None, "home", "away"):
        raise BadRequest("team must be home, away or null")
    if player is not None and player not in m.players:
        raise BadRequest("unknown player id")
    zones = []
    for z in (body.get("zones") or [])[:MAX_ZONES]:
        if not isinstance(z, dict):
            raise BadRequest("zones must be objects")
        x0, y0, x1, y1 = (_num(z.get(k), f"zone.{k}") for k in ("x0", "y0", "x1", "y1"))
        clamp_x = lambda v: round(min(max(v, 0.0), m.length), 1)  # noqa: E731
        clamp_y = lambda v: round(min(max(v, 0.0), m.width), 1)  # noqa: E731
        zones.append({"x0": clamp_x(x0), "y0": clamp_y(y0), "x1": clamp_x(x1), "y1": clamp_y(y1)})
    return {"task": task, "t": round(t, 1), "event_id": event_id, "mode": mode, "lang": lang, "team": team, "player": player, "zones": zones}

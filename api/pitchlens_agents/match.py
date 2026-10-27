"""Synthetic demo match loaded from api/data/ (same format as docs/schema.md)."""

from __future__ import annotations

import bisect
import gzip
import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

KEY_TYPES = ("shot", "offside")


def clock(t: float) -> str:
    s = max(0, int(t))
    return f"{s // 60:02d}:{s % 60:02d}"


class Match:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir.resolve()
        self.is_demo = self.data_dir == DATA_DIR.resolve()
        self.meta = json.loads((data_dir / "meta.json").read_text(encoding="utf-8"))
        self.events: list[dict] = json.loads((data_dir / "events.json").read_text(encoding="utf-8"))
        compressed = data_dir / "frames.jsonl.gz"
        frame_path = compressed if compressed.exists() else data_dir / "frames.jsonl"
        opener = gzip.open if frame_path.suffix == ".gz" else open
        with opener(frame_path, "rt", encoding="utf-8") as f:
            self.frames: list[dict] = [json.loads(line) for line in f if line.strip()]
        self.fps: float = self.meta["fps"]
        self.length: float = self.meta["pitch"]["length"]
        self.width: float = self.meta["pitch"]["width"]
        self.duration: float = self.meta["duration"]
        self.times = [fr["t"] for fr in self.frames]
        self.players: dict[str, dict] = {}
        for team in ("home", "away"):
            for p in self.meta["teams"][team]["players"]:
                self.players[p["id"]] = {**p, "team": team}

    # ------------------------------------------------------------ lookups

    def team(self, key: str) -> dict:
        return self.meta["teams"][key]

    def short(self, key: str | None) -> str | None:
        return self.team(key)["short"] if key else None

    @staticmethod
    def other(key: str) -> str:
        return "away" if key == "home" else "home"

    def attack_dir(self, key: str) -> int:
        return 1 if self.team(key)["attacks"] == "+x" else -1

    def depth_from_own_goal(self, key: str, x: float) -> float:
        """Metres from the team's own goal line along the pitch."""
        return x if self.attack_dir(key) == 1 else self.length - x

    def name(self, pid: str | None) -> str | None:
        return self.players[pid]["name"] if pid in self.players else None

    def frame_index(self, t: float) -> int:
        i = bisect.bisect_left(self.times, t)
        if i <= 0:
            return 0
        if i >= len(self.times):
            return len(self.times) - 1
        return i if self.times[i] - t < t - self.times[i - 1] else i - 1

    def frame_at(self, t: float) -> dict:
        return self.frames[self.frame_index(t)]

    def score_at(self, t: float) -> dict:
        score = {"home": 0, "away": 0}
        for e in self.events:
            if e["type"] == "goal" and e["t"] <= t:
                score = dict(e["score"])
        return score

    def event(self, eid: int) -> dict | None:
        if 0 <= eid < len(self.events) and self.events[eid]["id"] == eid:
            return self.events[eid]
        return next((e for e in self.events if e["id"] == eid), None)

    def key_moments(self) -> list[dict]:
        return [e for e in self.events if e["type"] in KEY_TYPES]

    def offside_pass(self, offside: dict) -> dict | None:
        """The pass that produced an offside call (the last offside-outcome pass before it)."""
        best = None
        for e in self.events:
            if e["t"] > offside["t"]:
                break
            if e["type"] == "pass" and e.get("outcome") == "offside":
                best = e
        return best


@lru_cache(maxsize=1)
def demo_match() -> Match:
    return Match()


SCENARIOS_DIR = DATA_DIR / "scenarios"
if not SCENARIOS_DIR.is_dir():
    SCENARIOS_DIR = DATA_DIR.parent.parent / "web" / "public" / "data" / "scenarios"

DATASET_DIRS = {
    "demo": DATA_DIR,
    "possession-battle": SCENARIOS_DIR / "scenario-01-possession-battle",
    "offside-attack": SCENARIOS_DIR / "scenario-02-offside-attack",
    "transition-attack": SCENARIOS_DIR / "scenario-03-transition-attack",
}


@lru_cache(maxsize=8)
def dataset_match(key: str) -> Match:
    data_dir = DATASET_DIRS.get(key)
    if data_dir is None:
        raise ValueError("unknown dataset")
    if not (data_dir / "meta.json").is_file():
        raise FileNotFoundError(f"dataset data is missing: {key}")
    return Match(data_dir)

"""CLI: generate a synthetic match in the PitchLens data format.

    python -m pitchlens_synth --duration 600 --hz 10 --seed 7 --out web/public/data/demo
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from . import __version__
from .engine import MatchSim
from .pitch import PITCH_LENGTH, PITCH_WIDTH
from .teams import AWAY, HOME


def build_meta(sim: MatchSim, seed: int) -> dict:
    teams = {}
    for k, team in enumerate(sim.teams):
        teams[team.key] = {
            "name": team.name,
            "short": team.short,
            "formation": team.formation,
            "colors": team.colors,
            "attacks": "+x" if k == 0 else "-x",
            "players": [
                {
                    "id": team.player_id(i),
                    "number": p.number,
                    "name": p.name,
                    "position": team.slots[i].code,
                    "role": team.slots[i].role,
                }
                for i, p in enumerate(team.players)
            ],
        }
    return {
        "source": "synthetic",
        "generator": f"pitchlens_synth {__version__}",
        "seed": seed,
        "pitch": {"length": PITCH_LENGTH, "width": PITCH_WIDTH},
        "fps": sim.out_hz,
        "duration": sim.duration,
        "frame_count": len(sim.frames),
        "teams": teams,
        "final_score": {"home": sim.score[0], "away": sim.score[1]},
    }


def write_outputs(sim: MatchSim, out: Path, seed: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "frames.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for frame in sim.frames:
            fh.write(json.dumps(frame, separators=(",", ":")) + "\n")
    with open(out / "events.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(sim.events, fh, separators=(",", ":"))
    with open(out / "meta.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(build_meta(sim, seed), fh, indent=2)


def summarize(sim: MatchSim) -> str:
    types = Counter(e["type"] for e in sim.events)
    passes = [e for e in sim.events if e["type"] == "pass"]
    done = sum(e["outcome"] == "complete" for e in passes)
    poss = Counter(f["possession"] for f in sim.frames)
    total = max(poss["home"] + poss["away"], 1)
    speeds = np.array([[p["speed"] for p in f["players"]] for f in sim.frames])
    dist_km = [round(p["dist"] / 1000, 2) for p in sim.frames[-1]["players"]]
    lines = [
        f"score            {sim.teams[0].short} {sim.score[0]} - {sim.score[1]} {sim.teams[1].short}",
        f"frames           {len(sim.frames)} @ {sim.out_hz} Hz",
        f"events           {dict(types)}",
        f"pass completion  {done}/{len(passes)} ({100 * done / max(len(passes), 1):.0f}%)",
        f"possession       home {100 * poss['home'] / total:.0f}% / away {100 * poss['away'] / total:.0f}%",
        f"speed m/s        mean {speeds.mean():.2f}, p95 {np.percentile(speeds, 95):.2f}, max {speeds.max():.2f}",
        f"distance km      min {min(dist_km)}, max {max(dist_km)}",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duration", type=float, default=600.0, help="match seconds to simulate")
    ap.add_argument("--hz", type=int, default=10, choices=[10, 25, 50], help="output frame rate")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=Path("web/public/data/demo"))
    args = ap.parse_args()

    sim = MatchSim(HOME, AWAY, seed=args.seed, duration=args.duration, out_hz=args.hz)
    sim.run()
    write_outputs(sim, args.out, args.seed)
    print(summarize(sim))
    print(f"written to       {args.out}")


if __name__ == "__main__":
    main()

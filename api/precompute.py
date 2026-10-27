"""Generate the AI analyst's answers ahead of time with the real model.

Runs every key moment (and a recap every 30 s) through the full four-agent
pipeline for each style and language, keeps only answers that really came from
the model, and writes them to api/data/precomputed.json. The function serves
them instantly, with their original agent trace, and still runs the agents live
for anything else (favourite player, drawn zones, other times).

    # model settings in the environment or api/local.settings.json
    python api/precompute.py                 # neutral viewer
    python api/precompute.py --teams         # also NBR fan / KBA fan variants
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from local_server import load_settings  # noqa: E402
from pitchlens_agents.agents import RECAP_STEP_S, explain, moment_key, recap_moment, resolve_moment  # noqa: E402
from pitchlens_agents.llm import LLM  # noqa: E402
from pitchlens_agents.match import DATA_DIR, demo_match  # noqa: E402

MODES = ("analyst", "fan")
LANGS = ("en", "pl", "es")


def requests(teams: bool) -> list[dict]:
    m = demo_match()
    team_opts = [None, "home", "away"] if teams else [None]
    times = [("moment", e["t"]) for e in m.key_moments()]
    times += [("recap", float(t)) for t in range(RECAP_STEP_S, int(m.duration) + 1, RECAP_STEP_S)]
    out = []
    for task, t in times:
        for mode in MODES:
            for lang in LANGS:
                for team in team_opts:
                    out.append({"task": task, "t": t, "event_id": None, "mode": mode, "lang": lang, "team": team, "player": None, "zones": []})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--teams", action="store_true", help="also precompute favourite-team variants")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    load_settings()
    if not LLM().available:
        sys.exit("Model settings missing: set AZURE_OPENAI_* or fill api/local.settings.json")
    m = demo_match()
    reqs = requests(args.teams)
    print(f"{len(reqs)} answers to generate with {args.workers} workers...")
    path = DATA_DIR / "precomputed.json"
    done: dict = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    failed = 0

    def run(req: dict):
        moment = recap_moment(m, req["t"]) if req["task"] == "recap" else resolve_moment(m, req["t"])
        key = moment_key(req, moment)
        if key in done:
            return key, None
        return key, explain(req, m, LLM(), use_precomputed=False)

    with ThreadPoolExecutor(args.workers) as pool:
        for i, fut in enumerate(as_completed(pool.submit(run, r) for r in reqs), 1):
            key, res = fut.result()
            if res is None:
                continue
            # Keep only real model answers; template fallbacks are produced live anyway.
            if res["engine"] == "foundry" and not any(s["status"] == "fallback" for s in res["trace"]):
                done[key] = {**res, "cached": False}
            else:
                failed += 1
            if i % 10 == 0:
                print(f"  {i}/{len(reqs)}")
    path.write_text(json.dumps(done, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Saved {len(done)} answers to {path} ({path.stat().st_size // 1024} kB); {failed} skipped (fallback).")


if __name__ == "__main__":
    main()

"""Generate the AI analyst's answers ahead of time with the real model.

Runs every key moment (and a recap every 30 s) through the full four-agent
pipeline for each style and language, keeps only answers that really came from
the model, and writes them to api/data/precomputed.json. The function serves
them instantly, with their original agent trace, and still runs the agents live
for anything else (favourite player, drawn zones, other times).

    # model settings in the environment or api/local.settings.json
    python api/precompute.py                 # neutral viewer
    python api/precompute.py --teams         # also NBR fan / KBA fan variants

    # or let the deployed site run the agents (no keys on this machine)
    python api/precompute.py --url https://<app>.azurewebsites.net

Runs are idempotent: answers already in the file are kept, so a run interrupted by
rate limits can simply be repeated.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server import load_settings  # noqa: E402
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
    ap.add_argument("--url", help="deployed PitchLens site that runs the agents instead of this machine")
    ap.add_argument("--recap-every", type=int, default=RECAP_STEP_S, help="seconds between precomputed recaps")
    args = ap.parse_args()
    load_settings()
    if not args.url and not LLM().available:
        sys.exit("Model settings missing: set AZURE_OPENAI_* or fill api/local.settings.json, or pass --url")
    m = demo_match()
    reqs = [r for r in requests(args.teams) if r["task"] != "recap" or r["t"] % args.recap_every == 0]
    # The demo video's personalisation: the 03:32 offside for an away fan in PL and ES.
    offside = next(e["t"] for e in m.key_moments() if e["type"] == "offside")
    video = [{"task": "moment", "t": offside, "event_id": None, "mode": "fan", "lang": lang, "team": "away", "player": None, "zones": []} for lang in ("pl", "es")]
    first = lambda r: (r["t"] == offside and r["task"] == "moment") or (r["task"] == "recap" and r["t"] == m.duration)  # noqa: E731
    reqs = video + [r for r in reqs if first(r)] + [r for r in reqs if not first(r)]
    print(f"{len(reqs)} answers to generate with {args.workers} workers...")
    path = DATA_DIR / "precomputed.json"
    done: dict = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    failed = 0

    def run(req: dict):
        moment = recap_moment(m, req["t"]) if req["task"] == "recap" else resolve_moment(m, req["t"])
        key = moment_key(req, moment)
        if key in done:
            return key, None
        if args.url:
            body = json.dumps({k: req[k] for k in ("task", "t", "mode", "lang", "team")}).encode()
            http = urllib.request.Request(args.url.rstrip("/") + "/api/explain", data=body, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(http, timeout=90) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
            except OSError as e:
                print(f"  {key}: {e}")
                return key, {"engine": "error", "trace": []}
            return key, None if res.get("precomputed") else res
        return key, explain(req, m, LLM(), use_precomputed=False)

    with ThreadPoolExecutor(args.workers) as pool:
        for i, fut in enumerate(as_completed(pool.submit(run, r) for r in reqs), 1):
            key, res = fut.result()
            if res is None:
                continue
            # Keep only real model answers; template fallbacks are produced live anyway.
            if res.get("engine") == "foundry" and not any(s["status"] in ("fallback", "error") for s in res["trace"]):
                done[key] = {**res, "cached": False, "precomputed": False}
            else:
                failed += 1
            if i % 10 == 0:
                print(f"  {i}/{len(reqs)}")
    path.write_text(json.dumps(done, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Saved {len(done)} answers to {path} ({path.stat().st_size // 1024} kB); {failed} skipped (fallback).")


if __name__ == "__main__":
    main()

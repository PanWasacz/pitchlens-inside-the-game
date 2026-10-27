# PitchLens: Inside the Game

Broadcast telestration studio for football pundits, built for the Microsoft x
Premier League **Inside the Game** hackathon (challenge: *The Synthetic Match
Insights Engine for Premier League Studio*).

> Work in progress. The demo runs on **synthetic data only**: fictional teams
> and players, no real clubs, crests or names.

## What it does

- **Telestration studio**: TV, tactical and 3D views; click players for rings, trails and
  speed/distance cards; formation lines, offside line, distances; arrows, circles and zones
  that stay on the grass in every view.
- **AI analyst (four agents on Microsoft Foundry)**: *Explain this moment* and *Recap so far*.
  The Analyst calls fact tools, the Explainer says why it matters citing fact ids, the
  Verifier checks every number, time and name in code and the logic with the model (one
  revision, then unsupported sentences are dropped), the Personalizer adapts it for an
  analyst or a fan, a favourite club and player, in English, Polish or Spanish.
  Every answer lists its evidence and the trace of how it was produced.
- **Control vs chaos**: a momentum strip above the timeline (control index from possession,
  territory and chance quality) and a `get_momentum` tool the agents use to explain swings.
- **Live feed**: cards while the match plays: goals, saves, offsides, long through balls with
  a pass difficulty rating, sprint alerts above 30 km/h, distance milestones, momentum swings.
- **Player focus**: the camera follows one player, with a live stat card and a feed of their moments.

## Repository layout

| path | what |
|---|---|
| `pitchlens_synth/` | synthetic match generator: 22 players + ball, formations, passes, shots, tackles |
| `web/` | broadcast UI (Vite + TypeScript + canvas). Demo data lives in `web/public/data/demo/` |
| `pitchlens_cv/` | CV pipeline: detection + tracking, team colours, pitch homography, export (local video only) |
| `api/` | Azure Function `/api/explain`: four agents (Analyst, Explainer, Verifier, Personalizer) on Microsoft Foundry, with fact tools and a template fallback |
| `docs/schema.md` | shared data format (`meta.json`, `frames.jsonl`, `events.json`) |

## Generate a synthetic match

```bash
pip install -r pitchlens_synth/requirements.txt
python -m pitchlens_synth --seed 20 --duration 600 --hz 10 --out web/public/data/demo
```

## Run the studio locally

```bash
python api/local_server.py   # AI analyst API on :7071 (optional, stdlib only)
cd web
npm install
npm run dev        # http://localhost:5173
```

Deployment to Azure Static Web Apps and Microsoft Foundry: see `docs/deploy.md`.

Controls: click/tap a player to track them (several at once), toggle team shapes,
offside line and distances in the top bar, draw with the tools on the left
(arrow, circle, zone, eraser, undo, clear). Space plays/pauses, arrow keys skip 5 s,
Shift+arrow jumps between key moments, 1/2 switch TV and tactical views.

When `match/out/cv_demo/` exists (built with the CV pipeline, see `docs/schema.md`),
the dev server also offers **Broadcast video (local)**: the same overlays drawn on
the original footage through the per-frame homography. That footage is never
published.

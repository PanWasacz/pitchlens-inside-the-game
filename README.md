# PitchLens Studio

**Telestration and explainable match intelligence for TV pundits and fans.**
Built for the Microsoft x Premier League **Inside the Game** hackathon
(challenge: *The Synthetic Match Insights Engine for Premier League Studio*).

**Live demo:** [pitchlens-studio-5169.azurewebsites.net](https://pitchlens-studio-5169.azurewebsites.net) · **Video:** [youtu.be/P8NhUwjZ3bE](https://youtu.be/P8NhUwjZ3bE)

> Everything shown runs on **synthetic, football-realistic data** that we generate
> ourselves: fictional teams (Northbridge Rovers vs Kestrel Bay Athletic), fictional
> players, no real clubs, crests, names or footage.

![Broadcast view with tracked players](docs/img/tv-tracking.png)

## The problem

A studio pundit has seconds to explain a moment: who was offside and by how much,
why the back line was caught, who controlled the build-up. Today that means
switching between stats tools and a telestrator, and the explanation reaches every
viewer the same way, whether they are a data-hungry analyst or a casual fan.

## What PitchLens does

It follows the challenge's pipeline end to end: **ingest** synthetic events as the
match plays, **interpret** them into statistics, **explain** why a moment matters,
**render** it on screen next to the match, and **personalize** it per viewer.

| | |
|---|---|
| ![Offside line](docs/img/offside.png) | ![Tactical view with team shapes and drawings](docs/img/tactical-shapes.png) |
| **Telestration studio.** TV, tactical and 3D views with smooth transitions. Click players for rings, trails and speed/distance cards; formation lines, offside line, distances; arrows, circles and zones stay on the grass in every view. | **Tactics at a glance.** Both teams' shapes, the pundit's own drawings, and a minimap of what the camera shows. |
| ![Player focus and live feed](docs/img/focus-feed.png) | ![AI analyst with evidence and agent trace](docs/img/ai-analyst.png) |
| **Live feed and player focus.** Cards while the match plays: goals, saves, offsides, through balls with a 1-5 pass difficulty rating, sprint alerts above 30 km/h, distance milestones, momentum swings. Player focus makes the camera follow one player with a live stat card. | **AI analyst.** *Explain this moment* and *Recap so far*, answered by four agents on Microsoft Foundry, with the evidence behind every sentence and the trace of how it was produced. |
| ![Same moment for a Polish fan](docs/img/ai-fan-pl.png) | ![Match recap](docs/img/ai-recap.png) |
| **Personalized.** The same verified facts for an analyst or a fan, a favourite club and player, in English, Polish or Spanish. | **Recaps and control vs chaos.** A momentum strip above the timeline shows who controlled each spell (possession, territory, chance quality); the agents use the same tool to explain swings. |

## How the AI analyst works

Four specialised agents share one session state, a store of numbered facts.
Deterministic tools compute **every** number; the model never does arithmetic.

```mermaid
flowchart LR
    UI["Studio<br/>Explain / Recap"] -->|POST /api/explain| A
    subgraph Fn["Azure App Service: python server.py"]
        A["Analyst<br/>calls tools, picks key facts"] --> E["Explainer<br/>why it matters, cites fact ids"]
        E --> V{"Verifier<br/>code: numbers, times, names<br/>model: logic"}
        V -->|issues, once| E
        V --> P["Personalizer<br/>analyst/fan, club, player, EN/PL/ES"]
        T[("Fact tools<br/>events, player stats, team shape,<br/>offside, possession, zones,<br/>momentum, match summary")]
        A <--> T
    end
    A & E & V & P <-->|chat completions,<br/>tool calling, JSON| F["Microsoft Foundry<br/>model deployment"]
    P --> R["Answer + evidence + agent trace"]
```

- **Analyst**: calls up to six tools (offside state at the pass, the defending
  team's shape before a shot, momentum of the build-up, zones the pundit drew...)
  and selects the 3 to 6 facts that matter. It writes no narrative.
- **Explainer**: 2 to 4 sentences on *why* the moment matters (3 to 5 for a recap);
  every sentence cites the ids of its facts.
- **Verifier**: code checks that every number, clock time and player name appears
  in the cited facts, then the model checks the logic (wrong team, a tackle called
  an interception...). Problems go back to the Explainer once; sentences that are
  still unsupported are dropped.
- **Personalizer**: rewrites the verified text for the viewer without adding facts,
  and its output is checked again.

**Reliability.** Each step falls back to fact-backed templates if the model fails,
so the endpoint always answers. A 38 s budget bounds every request, answers are
cached, and key moments can be precomputed with the real
model (`api/precompute.py`) for instant, repeatable results. Every request logs the
agents' status and timing for Application Insights.

**Responsible AI.** The model only receives structured parameters (time, style,
language, player id), never free text from the public, the deployment uses Azure AI
Content Safety filters, and every claim on screen is traceable to a computed fact.

## Microsoft technologies

| | |
|---|---|
| **Microsoft Foundry** (Azure OpenAI) | model deployment behind the four agents: tool calling and JSON outputs |
| **Azure App Service** (Linux, Python 3.11) | one standard-library server for the studio and `/api/explain` (agents, tools, verifier) |
| **Application Insights** | per-request agent trace (status, timing, model calls, tokens) |
| **GitHub Actions** | tests the agents, builds the studio and deploys to App Service on every push |

## Data

Organisers distribute no match data, so we built our own (`pitchlens_synth/`): 22
players and the ball simulated at 50 Hz and recorded at 10 Hz, formations that
shift with the ball, walking to sprinting, offside-aware runs, passes (through and
lofted), shots with xG, saves, tackles, interceptions, offsides, restarts and
officials. The demo match (seed 20, 10 minutes, 2-2) is reproducible from its seed.
All sources share one format, documented in [`docs/schema.md`](docs/schema.md).

Our CV pipeline (`pitchlens_cv/`: YOLOv8 detection, ByteTrack tracking, team colours,
camera calibration) produces the same format from broadcast video. It was tested
locally on publicly available sample clips
([roboflow/sports](https://github.com/roboflow/sports)); that footage is never
published, deployed or shown in the demo.

## Run it locally

```bash
python api/server.py            # AI analyst API on :7071 (standard library only)
cd web
npm install
npm run dev                     # studio on http://localhost:5173
```

On Windows, `start.bat` starts both. Without model settings the analyst answers
from its templates; to use the model, copy `api/local.settings.example.json` to
`api/local.settings.json` and fill in the Foundry endpoint, key and deployment.

Tests (no Azure needed; a scripted model exercises the Verifier's revision loop):

```bash
cd api
python -m unittest discover -s tests -v
```

Deployment to Azure: [`docs/deploy.md`](docs/deploy.md). Screenshots and the demo
video are scripted in `scripts/demo/`.

**Shortcuts:** Space play/pause · ←/→ 5 s · Shift+←/→ key moments · 1/2 views ·
V A C Z E tools · O offside · D distances · L live feed · F player focus · ? help.

## Repository layout

| path | what |
|---|---|
| `pitchlens_synth/` | synthetic match generator |
| `web/` | studio (Vite + TypeScript + canvas 2D, no framework) |
| `api/` | `server.py` (studio + `/api/explain`), agents, tools, verifier, templates, tests |
| `pitchlens_cv/` | CV pipeline for local video (detection, tracking, calibration, export) |
| `scripts/` | `build_site.py` (App Service package), `demo/` scripted screenshots and video (Playwright, ffmpeg) |
| `docs/` | data format, deployment guide, screenshots |

## Known limitations

- The synthetic match models behaviour, not physics: no dribbles or fouls, few corners.
- Events are replayed from a file in real time; the format is ready for a live stream.
- Recaps are computed as of whole half-minutes so they can be precomputed.

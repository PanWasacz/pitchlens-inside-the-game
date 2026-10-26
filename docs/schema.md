# PitchLens data format

Every match source (the synthetic generator and the CV pipeline) writes the same
three files into one folder, which the frontend loads as-is:

```
<match>/
├─ meta.json      teams, rosters, frame rate, pitch size
├─ frames.jsonl   one tracking frame per line
└─ events.json    array of match events
```

## Coordinate system

- Units are **metres** on a **105 × 68** pitch.
- `x` runs along the length, from 0 (home goal line) to 105 (away goal line).
- `y` runs across the width, from 0 (far touchline, top of the main camera
  image) to 68 (near touchline).
- The home team attacks toward `+x` (`meta.teams.home.attacks = "+x"`).
- Ball height `z` is in metres above the grass.

Because drawings and overlays are stored in these coordinates, they stay attached
to the grass in every camera view.

## `meta.json`

```json
{
  "source": "synthetic",            // "synthetic" | "cv"
  "generator": "pitchlens_synth 0.1.0",
  "seed": 20,
  "pitch": { "length": 105.0, "width": 68.0 },
  "fps": 10,                        // frames per second in frames.jsonl
  "duration": 600.0,                // seconds
  "frame_count": 6001,
  "teams": {
    "home": {
      "name": "Northbridge Rovers", "short": "NBR", "formation": "4-3-3",
      "colors": { "primary": "#E63946", "secondary": "#FFFFFF", "goalkeeper": "#FFD23F" },
      "attacks": "+x",
      "players": [
        { "id": "H01", "number": 1, "name": "E. Marrowby", "position": "GK", "role": "GK" }
      ]
    },
    "away": { "...": "same shape" }
  },
  "final_score": { "home": 1, "away": 3 }
}
```

`role` is one of `GK`, `DF`, `MF`, `FW`. `position` is the formation slot
(`LB`, `RCB`, `DM`, `ST`, …).

## `frames.jsonl`

One JSON object per line, ordered by `frame`. Frame `i` is at time `i / fps`.

```json
{
  "frame": 1234,
  "t": 123.4,
  "possession": "home",             // "home" | "away" | null
  "ball": { "x": 61.2, "y": 30.05, "z": 0.0, "owner": "H08" },
  "players": [
    { "id": "H08", "team": "home", "number": 8, "name": "J. Vantreight",
      "x": 60.71, "y": 29.84, "speed": 4.83, "dist": 1032.4 }
  ]
}
```

| field | meaning |
|---|---|
| `players[].id` | stable player id, also used in `meta.json` and `events.json` |
| `players[].speed` | instantaneous speed, m/s |
| `players[].dist` | cumulative distance covered since the start, m |
| `ball.owner` | id of the player controlling the ball, `null` in flight / loose / dead |
| `officials` | optional: `[{id, role, x, y, speed}]`, `role` is `referee` or `assistant`; ids are listed in `meta.officials` |

The CV pipeline may omit players that are not visible in a frame. Consumers
should match players by `id`, not by array index.

### Fields specific to `source: "cv"`

| field | meaning |
|---|---|
| `camera.R`, `camera.C`, `camera.f`, `camera.cx`, `camera.cy`, `camera.k1` | calibrated broadcast camera for this frame, in the right-handed world (x, −y, z): `pixel = (cx, cy) + f · d · (Xc / Zc, Yc / Zc)` with `(Xc, Yc, Zc) = R · (X − C)` and radial distortion `d = 1 + k1 · r²`. Position `C` and lens `k1` are shared by all frames (fixed camera), `R` (row-major) and `f` change per frame |
| `camera.H` | the same camera as a 3×3 pitch → pixel homography without lens distortion (row-major), for consumers that only need a planar approximation |
| `ball` | `null` when the ball is not detected; `z` is always 0 (no height estimate) |
| `players[].number`, `players[].name` | `null` (tracks are anonymous, ids are `T<track>`) |
| `possession` | always `null` |

`meta.json` adds `"video": {"file", "width", "height"}`, and `events.json` is an
empty array.

## `events.json`

An array ordered by time. Common fields:

| field | meaning |
|---|---|
| `id` | sequential integer |
| `type` | see below |
| `t` | time in seconds |
| `frame` | nearest frame index (`round(t * fps)`) |
| `team` | `"home"` / `"away"` / `null` |
| `player` | acting player id or `null` |
| `x`, `y` | where it happened, pitch metres |

Event types and their extra fields:

| type | extra fields |
|---|---|
| `pass` | `end_x`, `end_y`, `receiver` (intended), `received_by`, `through_ball`, `lofted`, `outcome`: `complete` / `intercepted` / `out_of_play` / `unresolved` |
| `shot` | `end_x`, `end_y`, `xg`, `assist`, `outcome`: `goal` / `saved` / `blocked` / `off_target` |
| `goal` | `scorer`, `assist`, `score` `{home, away}` |
| `save` | `shooter` |
| `tackle` | `opponent`, `outcome`: `won` / `lost` |
| `interception` | `passer` |
| `possession_change` | (`player` is the one who won the ball; `null` after a ball out of play) |
| `offside` | `player` is the receiver flagged offside (position at the moment of the pass), `passer`; the pass gets `outcome: offside` |
| `kickoff`, `goal_kick`, `throw_in`, `corner`, `free_kick` | restart taken by `player` |

The frontend's key moments are the `shot` (incl. goals and saves) and `offside` events.

## Building data from video (local only)

```bash
python -m pitchlens_cv.track --weights <detector.pt>      # players, keepers, referees, ball + teams
python -m pitchlens_cv.calibrate                          # per-frame pitch homography
python -m pitchlens_cv.export --out match/out/cv_demo     # pitch metres in this format
```

Data derived from real broadcast footage stays in the git-ignored `match/` folder.

## Regenerating the synthetic demo

```bash
pip install -r pitchlens_synth/requirements.txt
python -m pitchlens_synth --seed 20 --duration 600 --hz 10 --out web/public/data/demo
```

`--hz` accepts 10, 25 or 50. The same seed always produces the same match.

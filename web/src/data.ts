// Loading and sampling of a PitchLens match (docs/schema.md).

export type TeamKey = "home" | "away";

const CAM = 16; // numbers per frame in the video camera model

export interface PlayerMeta {
  id: string;
  number: number | null;
  name: string | null;
  position: string | null;
  role: string | null;
}

export interface TeamMeta {
  name: string;
  short: string;
  formation: string | null;
  colors: { primary: string; secondary: string; goalkeeper: string };
  attacks: "+x" | "-x" | null;
  players: PlayerMeta[];
}

export interface Meta {
  source: "synthetic" | "cv";
  pitch: { length: number; width: number };
  fps: number;
  duration: number;
  frame_count: number;
  teams: Record<TeamKey, TeamMeta>;
  video?: { file: string; width: number; height: number };
  officials?: { id: string; role: string }[];
}

export interface MatchEvent {
  id: number;
  type: string;
  t: number;
  frame: number;
  team: TeamKey | null;
  player: string | null;
  x: number;
  y: number;
  [extra: string]: unknown;
}

export interface Player extends PlayerMeta {
  index: number;
  team: TeamKey;
  isGK: boolean;
  label: string;
}

/** Interpolated state at one moment; arrays are indexed by Player.index. */
export interface Snapshot {
  t: number;
  x: Float32Array;
  y: Float32Array;
  speed: Float32Array;
  dist: Float32Array;
  visible: Uint8Array;
  ball: { x: number; y: number; z: number; visible: boolean };
  possession: TeamKey | null;
  /** Match officials (referee, assistants), same indexing as Match.officials. */
  officials: { x: Float32Array; y: Float32Array; visible: Uint8Array };
  /** Team defending its goal right now (opposite of possession; ball half for CV data). */
  defending: TeamKey | null;
  /** Video camera (CV only): R (9, row-major), C (3), f, cx, cy, k1 in the world frame (x, -y, z). */
  camera: Float64Array | null;
}

interface FrameJson {
  frame: number;
  possession: TeamKey | null;
  ball: { x: number; y: number; z: number; owner: string | null } | null;
  players: { id: string; x: number; y: number; speed: number; dist: number }[];
  officials?: { id: string; role: string; x: number; y: number }[];
  camera?: { R: number[]; C: number[]; f: number; cx: number; cy: number; k1: number } | null;
}

export class Match {
  readonly players: Player[];
  readonly officials: { id: string; role: string }[];
  readonly frames: number;
  readonly duration: number;
  private readonly P: number;
  private readonly px: Float32Array;
  private readonly py: Float32Array;
  private readonly spd: Float32Array;
  private readonly dst: Float32Array;
  private readonly present: Uint8Array;
  private readonly bx: Float32Array;
  private readonly by: Float32Array;
  private readonly bz: Float32Array;
  private readonly bPresent: Uint8Array;
  private readonly poss: Int8Array;
  private readonly cam: Float64Array | null;
  private readonly camPresent: Uint8Array;
  private readonly ox: Float32Array;
  private readonly oy: Float32Array;
  private readonly oPresent: Uint8Array;
  private readonly dirs: Record<TeamKey, 1 | -1>;
  private readonly def: Int8Array;
  private readonly snap: Snapshot;

  constructor(readonly meta: Meta, readonly events: MatchEvent[], lines: string[]) {
    this.players = [];
    for (const team of ["home", "away"] as TeamKey[]) {
      for (const p of meta.teams[team].players) {
        this.players.push({
          ...p,
          index: this.players.length,
          team,
          isGK: p.role === "GK",
          label: p.name ?? `Track ${p.id.replace(/^T0*/, "")}`,
        });
      }
    }
    const byId = new Map(this.players.map((p) => [p.id, p.index]));
    this.officials = meta.officials ?? [];
    const officialById = new Map(this.officials.map((o, i) => [o.id, i]));
    const O = this.officials.length;
    const n = lines.length;
    const P = (this.P = this.players.length);
    this.frames = n;
    this.duration = (n - 1) / meta.fps;
    this.px = new Float32Array(n * P);
    this.py = new Float32Array(n * P);
    this.spd = new Float32Array(n * P);
    this.dst = new Float32Array(n * P);
    this.present = new Uint8Array(n * P);
    this.bx = new Float32Array(n);
    this.by = new Float32Array(n);
    this.bz = new Float32Array(n);
    this.bPresent = new Uint8Array(n);
    this.poss = new Int8Array(n).fill(-1);
    this.cam = meta.source === "cv" ? new Float64Array(n * CAM) : null;
    this.camPresent = new Uint8Array(n);
    this.ox = new Float32Array(n * O);
    this.oy = new Float32Array(n * O);
    this.oPresent = new Uint8Array(n * O);

    lines.forEach((line, f) => {
      const fr = JSON.parse(line) as FrameJson;
      for (const p of fr.players) {
        const i = byId.get(p.id);
        if (i === undefined) continue;
        const k = f * P + i;
        this.px[k] = p.x;
        this.py[k] = p.y;
        this.spd[k] = p.speed;
        this.dst[k] = p.dist;
        this.present[k] = 1;
      }
      if (fr.ball) {
        this.bx[f] = fr.ball.x;
        this.by[f] = fr.ball.y;
        this.bz[f] = fr.ball.z;
        this.bPresent[f] = 1;
      }
      if (fr.possession) this.poss[f] = fr.possession === "home" ? 0 : 1;
      for (const o of fr.officials ?? []) {
        const i = officialById.get(o.id);
        if (i === undefined) continue;
        this.ox[f * O + i] = o.x;
        this.oy[f * O + i] = o.y;
        this.oPresent[f * O + i] = 1;
      }
      if (this.cam && fr.camera) {
        const c = fr.camera;
        this.cam.set([...c.R, ...c.C, c.f, c.cx, c.cy, c.k1], f * CAM);
        this.camPresent[f] = 1;
      }
    });

    this.dirs = this.attackDirections();
    this.def = this.defendingPerFrame();

    this.snap = {
      t: 0,
      x: new Float32Array(P),
      y: new Float32Array(P),
      speed: new Float32Array(P),
      dist: new Float32Array(P),
      visible: new Uint8Array(P),
      ball: { x: 0, y: 0, z: 0, visible: false },
      possession: null,
      officials: { x: new Float32Array(O), y: new Float32Array(O), visible: new Uint8Array(O) },
      defending: null,
      camera: this.cam ? new Float64Array(CAM) : null,
    };
  }

  /** Interpolated state at time t (seconds). The returned object is reused. */
  sample(t: number): Snapshot {
    const s = this.snap;
    const fpos = Math.min(Math.max(t * this.meta.fps, 0), this.frames - 1);
    const f0 = Math.floor(fpos);
    const f1 = Math.min(f0 + 1, this.frames - 1);
    const a = fpos - f0;
    const P = this.P;
    s.t = t;
    for (let i = 0; i < P; i++) {
      const k0 = f0 * P + i;
      const k1 = f1 * P + i;
      const p0 = this.present[k0];
      const p1 = this.present[k1];
      if (p0 && p1) {
        s.x[i] = this.px[k0] + (this.px[k1] - this.px[k0]) * a;
        s.y[i] = this.py[k0] + (this.py[k1] - this.py[k0]) * a;
        s.speed[i] = this.spd[k0] + (this.spd[k1] - this.spd[k0]) * a;
        s.dist[i] = this.dst[k0] + (this.dst[k1] - this.dst[k0]) * a;
      } else if (p0 || p1) {
        const k = p0 ? k0 : k1;
        s.x[i] = this.px[k];
        s.y[i] = this.py[k];
        s.speed[i] = this.spd[k];
        s.dist[i] = this.dst[k];
      }
      s.visible[i] = p0 || p1 ? 1 : 0;
    }
    const b0 = this.bPresent[f0];
    const b1 = this.bPresent[f1];
    if (b0 && b1) {
      s.ball.x = this.bx[f0] + (this.bx[f1] - this.bx[f0]) * a;
      s.ball.y = this.by[f0] + (this.by[f1] - this.by[f0]) * a;
      s.ball.z = this.bz[f0] + (this.bz[f1] - this.bz[f0]) * a;
    } else if (b0 || b1) {
      const f = b0 ? f0 : f1;
      s.ball.x = this.bx[f];
      s.ball.y = this.by[f];
      s.ball.z = this.bz[f];
    }
    s.ball.visible = Boolean(b0 || b1);
    const pv = this.poss[a < 0.5 ? f0 : f1];
    s.possession = pv < 0 ? null : pv === 0 ? "home" : "away";
    const O = this.officials.length;
    for (let i = 0; i < O; i++) {
      const p0 = this.oPresent[f0 * O + i];
      const p1 = this.oPresent[f1 * O + i];
      const g0 = p0 ? f0 : f1;
      const g1 = p1 ? f1 : f0;
      s.officials.x[i] = this.ox[g0 * O + i] + (this.ox[g1 * O + i] - this.ox[g0 * O + i]) * a;
      s.officials.y[i] = this.oy[g0 * O + i] + (this.oy[g1 * O + i] - this.oy[g0 * O + i]) * a;
      s.officials.visible[i] = p0 || p1 ? 1 : 0;
    }
    const dv = this.def[a < 0.5 ? f0 : f1];
    s.defending = dv < 0 ? null : dv === 0 ? "home" : "away";
    if (this.cam && s.camera) {
      const c0 = this.camPresent[f0] ? f0 : f1;
      const c1 = this.camPresent[f1] ? f1 : f0;
      if (this.camPresent[c0]) {
        for (let j = 0; j < CAM; j++) {
          s.camera[j] = this.cam[c0 * CAM + j] + (this.cam[c1 * CAM + j] - this.cam[c0 * CAM + j]) * a;
        }
      }
    }
    return s;
  }

  /** Recent ground positions of one player, oldest first. */
  trail(i: number, t: number, seconds: number): [number, number][] {
    const fps = this.meta.fps;
    const end = Math.min(Math.floor(t * fps), this.frames - 1);
    const start = Math.max(0, end - Math.round(seconds * fps));
    const step = Math.max(1, Math.round(fps / 10));
    const out: [number, number][] = [];
    for (let f = start; f <= end; f += step) {
      const k = f * this.P + i;
      if (this.present[k]) out.push([this.px[k], this.py[k]]);
    }
    return out;
  }

  /** Which way a team attacks (+1 towards x = 105). Fixed for the whole clip. */
  attackDir(team: TeamKey): 1 | -1 {
    return this.dirs[team];
  }

  /**
   * Attack directions: declared for synthetic data; for CV data from where each
   * goalkeeper stands over the whole clip (teams do not swap ends within a clip).
   * A momentary guess per frame flips when a team pushes into the other half.
   */
  private attackDirections(): Record<TeamKey, 1 | -1> {
    const half = this.meta.pitch.length / 2;
    const guess: Partial<Record<TeamKey, 1 | -1>> = {};
    for (const team of ["home", "away"] as TeamKey[]) {
      const declared = this.meta.teams[team].attacks;
      if (declared) {
        guess[team] = declared === "+x" ? 1 : -1;
        continue;
      }
      const xs: number[] = [];
      for (const p of this.players) {
        if (p.team !== team || !p.isGK) continue;
        for (let f = 0; f < this.frames; f++) if (this.present[f * this.P + p.index]) xs.push(this.px[f * this.P + p.index]);
      }
      if (xs.length) {
        xs.sort((a, b) => a - b);
        guess[team] = xs[xs.length >> 1] < half ? 1 : -1;
      }
    }
    const home = guess.home ?? (guess.away ? (-guess.away as 1 | -1) : 1);
    return { home, away: guess.away ?? (-home as 1 | -1) };
  }

  /**
   * Defending team per frame. With possession data it is simply the other team.
   * CV data has no possession, so the team whose half the ball is in defends, with a
   * 4 m hysteresis around halfway and the last known ball position when it is not
   * detected, so the line does not flicker between teams.
   */
  private defendingPerFrame(): Int8Array {
    const def = new Int8Array(this.frames).fill(-1);
    const half = this.meta.pitch.length / 2;
    const leftDefender = this.dirs.home === 1 ? 0 : 1; // team whose goal is at x = 0
    let state = -1;
    let ballX = half;
    for (let f = 0; f < this.frames; f++) {
      if (this.poss[f] >= 0) {
        state = 1 - this.poss[f];
      } else if (this.meta.source === "cv") {
        if (this.bPresent[f]) ballX = this.bx[f];
        if (ballX < half - 4) state = leftDefender;
        else if (ballX > half + 4) state = 1 - leftDefender;
        else if (state < 0) state = ballX < half ? leftDefender : 1 - leftDefender;
      }
      def[f] = state;
    }
    return def;
  }
}

export interface Dataset {
  key: string;
  label: string;
  base: string; // folder with meta.json / frames.jsonl / events.json
  video?: string;
}

export const DATASETS: Dataset[] = [
  { key: "demo", label: "Synthetic match", base: "data/demo/" },
  { key: "possession-battle", label: "Harbour City FC - Redwood Athletic", base: "data/scenarios/scenario-01-possession-battle/" },
  { key: "offside-attack", label: "Silverlake United - Eastgate Borough", base: "data/scenarios/scenario-02-offside-attack/" },
  { key: "transition-attack", label: "Pinecrest Wanderers - Golden Vale SC", base: "data/scenarios/scenario-03-transition-attack/" },
  // Served by the dev server from the git-ignored match/ folder only.
  { key: "cv", label: "Real match (sample)", base: "/local/out/cv_demo/", video: "/local/sample_match.mp4" },
];

export async function datasetAvailable(ds: Dataset): Promise<boolean> {
  try {
    const r = await fetch(ds.base + "meta.json", { method: "HEAD" });
    return r.ok && (r.headers.get("content-type") ?? "").includes("json");
  } catch {
    return false;
  }
}

export async function loadMatch(ds: Dataset, onProgress: (fraction: number) => void): Promise<Match> {
  const [meta, events] = await Promise.all([
    fetch(ds.base + "meta.json").then((r) => r.json() as Promise<Meta>),
    fetch(ds.base + "events.json").then((r) => r.json() as Promise<MatchEvent[]>),
  ]);
  const res = await fetch(ds.base + "frames.jsonl");
  if (!res.ok || !res.body) throw new Error(`Cannot load ${ds.base}frames.jsonl`);
  const total = Number(res.headers.get("content-length")) || 0;
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.length;
    if (total) onProgress(Math.min(received / total, 1));
  }
  const text = await new Blob(chunks as BlobPart[]).text();
  const lines = text.split("\n").filter((l) => l.length > 0);
  return new Match(meta, events, lines);
}

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
  /** Video camera (CV only): R (9, row-major), C (3), f, cx, cy, k1 in the world frame (x, -y, z). */
  camera: Float64Array | null;
}

interface FrameJson {
  frame: number;
  possession: TeamKey | null;
  ball: { x: number; y: number; z: number; owner: string | null } | null;
  players: { id: string; x: number; y: number; speed: number; dist: number }[];
  camera?: { R: number[]; C: number[]; f: number; cx: number; cy: number; k1: number } | null;
}

export class Match {
  readonly players: Player[];
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
      if (this.cam && fr.camera) {
        const c = fr.camera;
        this.cam.set([...c.R, ...c.C, c.f, c.cx, c.cy, c.k1], f * CAM);
        this.camPresent[f] = 1;
      }
    });

    this.snap = {
      t: 0,
      x: new Float32Array(P),
      y: new Float32Array(P),
      speed: new Float32Array(P),
      dist: new Float32Array(P),
      visible: new Uint8Array(P),
      ball: { x: 0, y: 0, z: 0, visible: false },
      possession: null,
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

  /** Which way a team attacks; inferred from its goalkeeper for CV data. */
  attackDir(team: TeamKey, s: Snapshot): 1 | -1 {
    const declared = this.meta.teams[team].attacks;
    if (declared) return declared === "+x" ? 1 : -1;
    const gk = this.players.find((p) => p.team === team && p.isGK && s.visible[p.index]);
    if (gk) return s.x[gk.index] < this.meta.pitch.length / 2 ? 1 : -1;
    let sum = 0;
    let n = 0;
    for (const p of this.players) {
      if (p.team === team && s.visible[p.index]) {
        sum += s.x[p.index];
        n++;
      }
    }
    return n && sum / n < this.meta.pitch.length / 2 ? 1 : -1;
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
  // Served by the dev server from the git-ignored match/ folder only.
  { key: "cv", label: "Broadcast video (local)", base: "/local/out/cv_demo/", video: "/local/sample_match.mp4" },
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

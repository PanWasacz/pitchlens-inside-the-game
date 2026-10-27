// Tactical overlays: formation lines, offside line and player distances.

import type { Camera } from "./camera";
import type { Match, Player, Snapshot, TeamKey } from "./data";
import { L, W, type Pt } from "./pitch";
import { groundPath, hexAlpha, pill } from "./render";

export const OFFSIDE_COLOR = "#FF4FD8";

/** Outfield players of a team split into defence / midfield / attack lines. */
export function formationLines(match: Match, s: Snapshot, team: TeamKey): Player[][] {
  const outfield = match.players.filter((p) => p.team === team && !p.isGK && s.visible[p.index]);
  if (outfield.length < 3) return [];
  const known = outfield.every((p) => p.role === "DF" || p.role === "MF" || p.role === "FW");
  if (known) {
    return (["DF", "MF", "FW"] as const).map((r) => outfield.filter((p) => p.role === r));
  }
  // No roles (CV tracks): 1-D k-means (k = 3) on depth along the attacking direction.
  const dir = match.attackDir(team);
  const depth = outfield.map((p) => s.x[p.index] * dir);
  const sorted = [...depth].sort((a, b) => a - b);
  let centers = [0.15, 0.5, 0.85].map((q) => sorted[Math.floor(q * (sorted.length - 1))]);
  let groups: number[] = [];
  for (let iter = 0; iter < 10; iter++) {
    groups = depth.map((d) => {
      let best = 0;
      for (let c = 1; c < 3; c++) if (Math.abs(d - centers[c]) < Math.abs(d - centers[best])) best = c;
      return best;
    });
    centers = centers.map((c, k) => {
      const members = depth.filter((_, i) => groups[i] === k);
      return members.length ? members.reduce((a, b) => a + b, 0) / members.length : c;
    });
  }
  return [0, 1, 2].map((k) => outfield.filter((_, i) => groups[i] === k));
}

export function drawFormation(ctx: CanvasRenderingContext2D, cam: Camera, match: Match, s: Snapshot, team: TeamKey) {
  const color = match.meta.teams[team].colors.primary;
  const mid = cam.project(L / 2, W / 2, 0);
  ctx.save();
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (const line of formationLines(match, s, team)) {
    if (line.length < 2) continue;
    const pts: Pt[] = line.map((p) => [s.x[p.index], s.y[p.index]] as Pt).sort((a, b) => a[1] - b[1]);
    ctx.shadowColor = color;
    ctx.shadowBlur = 10;
    ctx.strokeStyle = "rgba(255,255,255,0.9)";
    ctx.lineWidth = Math.max(4, 0.42 * mid.scale);
    if (groundPath(ctx, cam, pts)) ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(2.5, 0.26 * mid.scale);
    if (groundPath(ctx, cam, pts)) ctx.stroke();
    for (const [x, y] of pts) {
      const p = cam.project(x, y, 0);
      if (p.scale <= 0) continue;
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(3, 0.35 * p.scale), 0, 2 * Math.PI);
      ctx.fill();
    }
  }
  ctx.restore();
}

export interface OffsideLine {
  x: number;
  defending: TeamKey;
  /** +1 when the defending team's goal is at x = 105, -1 when at x = 0. */
  goalSide: 1 | -1;
  offside: Player[];
}

export function offsideLine(match: Match, s: Snapshot): OffsideLine | null {
  const defending = s.defending;
  if (!defending) return null;
  const goalSide = (match.attackDir(defending) === 1 ? -1 : 1) as 1 | -1;
  const visible = match.players.filter((p) => p.team === defending && s.visible[p.index]);
  const depth = visible.map((p) => s.x[p.index] * goalSide).sort((a, b) => b - a);
  // The keeper normally is the last defender. When the camera does not show them
  // (CV data), the deepest visible defender already is the second-last one.
  const keeperSeen = visible.some((p) => p.isGK);
  const secondLast = keeperSeen || match.meta.source !== "cv" ? depth[1] : depth[0];
  if (secondLast === undefined) return null;
  // An attacker is offside when nearer the goal line than both the second-last
  // defender and the ball, and inside the opponents' half.
  let line = secondLast;
  if (s.ball.visible) line = Math.max(line, s.ball.x * goalSide);
  line = Math.max(line, (L / 2) * goalSide);
  const x = line * goalSide;
  const offside = match.players.filter(
    (p) => p.team !== defending && s.visible[p.index] && s.x[p.index] * goalSide > line + 0.05,
  );
  return { x, defending, goalSide, offside };
}

export function drawOffside(ctx: CanvasRenderingContext2D, cam: Camera, match: Match, s: Snapshot, time: number) {
  const o = offsideLine(match, s);
  if (!o) return;
  const goalX = o.goalSide === 1 ? L : 0;
  const mid = cam.project(o.x, W / 2, 0);
  ctx.save();
  ctx.fillStyle = hexAlpha(OFFSIDE_COLOR, 0.12);
  if (groundPath(ctx, cam, [[o.x, 0], [goalX, 0], [goalX, W], [o.x, W]], true)) ctx.fill();
  ctx.shadowColor = OFFSIDE_COLOR;
  ctx.shadowBlur = 14;
  ctx.strokeStyle = OFFSIDE_COLOR;
  ctx.lineWidth = Math.max(3, 0.3 * mid.scale);
  const line: Pt[] = [];
  for (let y = 0; y <= W; y += 2) line.push([o.x, y]);
  if (groundPath(ctx, cam, line)) ctx.stroke();
  ctx.shadowBlur = 0;
  for (const p of o.offside) {
    ctx.strokeStyle = OFFSIDE_COLOR;
    ctx.lineWidth = 2.5;
    ctx.globalAlpha = 0.7 + 0.3 * Math.sin(time * 6);
    if (groundPath(ctx, cam, ring(s.x[p.index], s.y[p.index], 1.0), true)) ctx.stroke();
  }
  ctx.globalAlpha = 1;
  const label = cam.project(o.x, W + 2.5, 0);
  if (label.scale > 0) pill(ctx, "OFFSIDE LINE", label.x, label.y, "#ffffff", hexAlpha(OFFSIDE_COLOR, 0.9));
  ctx.restore();
}

function ring(x: number, y: number, r: number): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i <= 32; i++) out.push([x + r * Math.cos((i / 32) * 2 * Math.PI), y + r * Math.sin((i / 32) * 2 * Math.PI)]);
  return out;
}

/**
 * Distances between consecutive selected players; with a single selection, to the
 * nearest opponent (how much space the player has).
 */
export function drawDistances(ctx: CanvasRenderingContext2D, cam: Camera, match: Match, s: Snapshot, selected: number[]) {
  const pairs: [number, number][] = [];
  const vis = selected.filter((i) => s.visible[i]);
  if (vis.length === 1) {
    const me = match.players[vis[0]];
    let best = -1;
    let bestD = Infinity;
    for (const p of match.players) {
      if (p.team === me.team || !s.visible[p.index]) continue;
      const d = Math.hypot(s.x[p.index] - s.x[me.index], s.y[p.index] - s.y[me.index]);
      if (d < bestD) {
        bestD = d;
        best = p.index;
      }
    }
    if (best >= 0) pairs.push([me.index, best]);
  } else {
    for (let i = 1; i < vis.length; i++) pairs.push([vis[i - 1], vis[i]]);
  }
  ctx.save();
  for (const [a, b] of pairs) {
    const ax = s.x[a], ay = s.y[a], bx = s.x[b], by = s.y[b];
    const d = Math.hypot(bx - ax, by - ay);
    const n = Math.max(2, Math.ceil(d / 2));
    const pts: Pt[] = [];
    for (let k = 0; k <= n; k++) pts.push([ax + ((bx - ax) * k) / n, ay + ((by - ay) * k) / n]);
    ctx.setLineDash([10, 7]);
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2.5;
    if (groundPath(ctx, cam, pts)) ctx.stroke();
    ctx.setLineDash([]);
    const m = cam.project((ax + bx) / 2, (ay + by) / 2, 0);
    if (m.scale > 0) pill(ctx, `${d.toFixed(1)} m`, m.x, m.y);
  }
  ctx.restore();
}

export interface Spell {
  t0: number;
  t1: number;
  /** Control index 0-100 per team (same formula as the API's get_momentum tool). */
  home: number;
  away: number;
}

export interface MomentumPoint {
  t: number;
  /** Home possession share minus away, in [-1, 1]. */
  v: number;
}

/** Rolling window and sample step used by the possession-dynamics chart.
 *  15 s / 1 s on the 10-minute demo is proportional to a 60 s / 5 s half-length chart. */
export const MOMENTUM_WINDOW_S = 15;
export const MOMENTUM_STEP_S = 1;

/**
 * Control vs chaos per spell: 50% possession, 30% territory (ball in the opponents'
 * half), 20% share of chance quality (xG). Empty when the source has no possession.
 */
export function momentumSpells(match: Match, step = 30): Spell[] {
  const out: Spell[] = [];
  const shots = match.events.filter((e) => e.type === "shot" && typeof e.xg === "number");
  const homeDir = match.attackDir("home");
  let anyPossession = false;
  for (let t0 = 0; t0 < match.duration - 1e-6; t0 += step) {
    const t1 = Math.min(t0 + step, match.duration);
    const poss = { home: 0, away: 0 };
    const terr = { home: 0, away: 0 };
    for (let t = t0; t < t1; t += 0.5) {
      const s = match.sample(t);
      if (s.possession) {
        poss[s.possession]++;
        anyPossession = true;
      }
      if (s.ball.visible) terr[(s.ball.x - L / 2) * homeDir > 0 ? "home" : "away"]++;
    }
    const xg = { home: 0, away: 0 };
    for (const e of shots) if (e.t >= t0 && e.t < t1 && e.team) xg[e.team] += e.xg as number;
    const pt = Math.max(1, poss.home + poss.away);
    const tt = Math.max(1, terr.home + terr.away);
    const xt = xg.home + xg.away;
    const ctrl = (k: TeamKey) => 0.5 * (100 * poss[k]) / pt + 0.3 * (100 * terr[k]) / tt + 0.2 * (xt > 0 ? (100 * xg[k]) / xt : 50);
    out.push({ t0, t1, home: ctrl("home"), away: ctrl("away") });
  }
  return anyPossession ? out : [];
}

/**
 * Rolling possession share for the area chart: +1 full home control, −1 full
 * away. Empty when the source has no possession. Trailing `window` seconds,
 * sampled every `step` seconds (defaults match a 60 s / ~5 s studio chart).
 */
export function momentumSeries(match: Match, window = MOMENTUM_WINDOW_S, step = MOMENTUM_STEP_S): MomentumPoint[] {
  const dt = 0.5;
  const n = Math.floor(match.duration / dt) + 1;
  const home = new Uint8Array(n);
  const away = new Uint8Array(n);
  let any = false;
  for (let i = 0; i < n; i++) {
    const p = match.sample(i * dt).possession;
    if (p === "home") {
      home[i] = 1;
      any = true;
    } else if (p === "away") {
      away[i] = 1;
      any = true;
    }
  }
  if (!any) return [];

  const hPre = new Int32Array(n + 1);
  const aPre = new Int32Array(n + 1);
  for (let i = 0; i < n; i++) {
    hPre[i + 1] = hPre[i] + home[i];
    aPre[i + 1] = aPre[i] + away[i];
  }

  const w = Math.max(1, Math.round(window / dt));
  const out: MomentumPoint[] = [];
  const push = (t: number) => {
    const i1 = Math.max(1, Math.min(n, Math.round(t / dt) + 1));
    const i0 = Math.max(0, i1 - w);
    const h = hPre[i1] - hPre[i0];
    const a = aPre[i1] - aPre[i0];
    const tot = h + a;
    out.push({ t, v: tot ? (h - a) / tot : 0 });
  };
  for (let t = 0; t < match.duration - 1e-6; t += step) push(t);
  if (!out.length || out[out.length - 1].t < match.duration - 1e-6) push(match.duration);
  return out;
}

/**
 * Biggest possession peaks worth marking: local extrema by |v|, spaced apart,
 * skipping the trailing-window ramp at kick-off.
 */
export function momentumPeaks(series: MomentumPoint[], limit = 8): MomentumPoint[] {
  if (series.length < 8) return [];
  const step = series.length > 1 ? series[1].t - series[0].t : 1;
  const radius = Math.max(2, Math.round(12 / Math.max(step, 0.5)));
  const t0 = MOMENTUM_WINDOW_S;
  const t1 = series[series.length - 1].t - 8;
  const cands: MomentumPoint[] = [];
  for (let i = radius; i < series.length - radius; i++) {
    const p = series[i];
    if (p.t < t0 || p.t > t1) continue;
    const v = p.v;
    if (Math.abs(v) < 0.4) continue;
    let extreme = true;
    let drop = 0;
    for (let k = i - radius; k <= i + radius; k++) {
      if (k === i) continue;
      const u = series[k].v;
      drop = Math.max(drop, Math.abs(v - u));
      if (v >= 0 && u > v) extreme = false;
      if (v < 0 && u < v) extreme = false;
    }
    if (extreme && drop >= 0.22) cands.push(p);
  }
  cands.sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
  const picked: MomentumPoint[] = [];
  const minSep = 20;
  for (const p of cands) {
    if (picked.every((q) => Math.abs(q.t - p.t) >= minSep)) picked.push(p);
    if (picked.length >= limit) break;
  }
  return picked.sort((a, b) => a.t - b.t);
}

/** Linear interpolation of the series at time t. */
export function momentumAt(series: MomentumPoint[], t: number): number {
  if (!series.length) return 0;
  if (t <= series[0].t) return series[0].v;
  const last = series[series.length - 1];
  if (t >= last.t) return last.v;
  let lo = 0;
  let hi = series.length - 1;
  while (hi - lo > 1) {
    const m = (lo + hi) >> 1;
    if (series[m].t <= t) lo = m;
    else hi = m;
  }
  const a = series[lo];
  const b = series[hi];
  const span = b.t - a.t;
  return span ? a.v + ((b.v - a.v) * (t - a.t)) / span : a.v;
}

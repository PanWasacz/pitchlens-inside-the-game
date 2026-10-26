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
  const dir = match.attackDir(team, s);
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
  let defending: TeamKey;
  if (s.possession) {
    defending = s.possession === "home" ? "away" : "home";
  } else {
    // No possession data (CV): the team defending the half the ball is in.
    const ballX = s.ball.visible ? s.ball.x : L / 2;
    const homeGoalSide = match.attackDir("home", s) === 1 ? -1 : 1;
    const ballSide = ballX < L / 2 ? -1 : 1;
    defending = homeGoalSide === ballSide ? "home" : "away";
  }
  const goalSide = (match.attackDir(defending, s) === 1 ? -1 : 1) as 1 | -1;
  const depth = match.players
    .filter((p) => p.team === defending && s.visible[p.index])
    .map((p) => s.x[p.index] * goalSide)
    .sort((a, b) => b - a);
  if (depth.length < 2) return null;
  // An attacker is offside when nearer the goal line than both the second-last
  // defender and the ball, and inside the opponents' half.
  let line = depth[1];
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

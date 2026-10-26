// Canvas drawing of the pitch, players, ball and broadcast overlays.

import type { Camera } from "./camera";
import type { Match, Player, Snapshot } from "./data";
import { circlePoints, densify, GOAL_H, GOAL_HALF, L, MARKINGS, SPOTS, W, type Pt } from "./pitch";

export const ACCENT = "#2BF5B6";
export const FONT = '"Barlow Condensed", "Arial Narrow", system-ui, sans-serif';
const SKIN = ["#f1c7a5", "#d9a074", "#a8724c", "#6e4a33"];

export function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/** Path through the visible projections of ground points. */
export function groundPath(ctx: CanvasRenderingContext2D, cam: Camera, pts: Pt[], close = false): boolean {
  let started = false;
  ctx.beginPath();
  for (const [x, y] of pts) {
    const p = cam.project(x, y, 0);
    if (p.scale <= 0) continue;
    if (started) ctx.lineTo(p.x, p.y);
    else {
      ctx.moveTo(p.x, p.y);
      started = true;
    }
  }
  if (started && close) ctx.closePath();
  return started;
}

export function drawBackdrop(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, "#05080f");
  g.addColorStop(0.45, "#0b1424");
  g.addColorStop(1, "#05080f");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
}

/** Far-side stand and advertising boards; only meaningful for the 3D broadcast camera. */
function drawStadium(ctx: CanvasRenderingContext2D, cam: Camera) {
  if (!cam.hasHeight) return;
  const quad = (pts: [number, number, number][]) => {
    ctx.beginPath();
    for (const [i, [x, y, z]] of pts.entries()) {
      const p = cam.project(x, y, z);
      if (p.scale <= 0) return false;
      if (i) ctx.lineTo(p.x, p.y);
      else ctx.moveTo(p.x, p.y);
    }
    ctx.closePath();
    return true;
  };
  // Tiers of the stand, rising away from the far touchline.
  const tiers = 6;
  for (let i = 0; i < tiers; i++) {
    const y0 = -9 - i * 3.2;
    const z0 = 1.5 + i * 2.6;
    if (quad([[-25, y0, z0], [L + 25, y0, z0], [L + 25, y0 - 3.2, z0 + 2.6], [-25, y0 - 3.2, z0 + 2.6]])) {
      ctx.fillStyle = i % 2 ? "#121b2c" : "#162135";
      ctx.fill();
    }
  }
  if (quad([[-25, -9, 0], [L + 25, -9, 0], [L + 25, -9, 1.5], [-25, -9, 1.5]])) {
    ctx.fillStyle = "#0d1422";
    ctx.fill();
  }
  // LED boards with a thin accent stripe.
  if (quad([[-6, -4, 0], [L + 6, -4, 0], [L + 6, -4, 0.9], [-6, -4, 0.9]])) {
    ctx.fillStyle = "#0a1020";
    ctx.fill();
  }
  if (quad([[-6, -4, 0.55], [L + 6, -4, 0.55], [L + 6, -4, 0.62], [-6, -4, 0.62]])) {
    ctx.fillStyle = ACCENT;
    ctx.fill();
  }
}

export function drawPitch(ctx: CanvasRenderingContext2D, cam: Camera, w: number, h: number) {
  drawStadium(ctx, cam);
  // Surround, then mowing stripes.
  ctx.fillStyle = "#1d5a2c";
  groundPath(ctx, cam, densify([[-6, -5], [L + 6, -5], [L + 6, W + 6], [-6, W + 6], [-6, -5]], 4), true);
  ctx.fill();
  const stripes = 20;
  for (let i = 0; i < stripes; i++) {
    const x0 = (L * i) / stripes;
    const x1 = (L * (i + 1)) / stripes;
    ctx.fillStyle = i % 2 ? "#2f8a3e" : "#2a7d38";
    groundPath(ctx, cam, densify([[x0, 0], [x1, 0], [x1, W], [x0, W], [x0, 0]], 6), true);
    ctx.fill();
  }
  // Soft light falloff toward the edges of the screen.
  const v = ctx.createRadialGradient(w / 2, h * 0.45, h * 0.2, w / 2, h * 0.45, Math.max(w, h) * 0.75);
  v.addColorStop(0, "rgba(255,255,255,0.05)");
  v.addColorStop(1, "rgba(0,0,0,0.35)");
  ctx.fillStyle = v;
  ctx.fillRect(0, 0, w, h);

  const mid = cam.project(L / 2, W / 2, 0);
  ctx.strokeStyle = "rgba(255,255,255,0.85)";
  ctx.lineWidth = Math.max(1.3, 0.12 * mid.scale);
  ctx.lineJoin = "round";
  for (const line of MARKINGS) {
    if (groundPath(ctx, cam, line)) ctx.stroke();
  }
  ctx.fillStyle = "rgba(255,255,255,0.9)";
  for (const [x, y] of SPOTS) {
    const p = cam.project(x, y, 0);
    if (p.scale <= 0) continue;
    ctx.beginPath();
    ctx.arc(p.x, p.y, Math.max(1.2, 0.11 * p.scale), 0, 2 * Math.PI);
    ctx.fill();
  }
  drawGoals(ctx, cam);
}

function drawGoals(ctx: CanvasRenderingContext2D, cam: Camera) {
  ctx.lineWidth = 2;
  for (const [gx, s] of [[0, -1], [L, 1]] as const) {
    const back = gx + s * 2;
    const posts: [number, number, number][][] = [
      [[gx, W / 2 - GOAL_HALF, 0], [gx, W / 2 - GOAL_HALF, GOAL_H], [gx, W / 2 + GOAL_HALF, GOAL_H], [gx, W / 2 + GOAL_HALF, 0]],
    ];
    const net: [number, number, number][][] = [
      [[gx, W / 2 - GOAL_HALF, GOAL_H], [back, W / 2 - GOAL_HALF, GOAL_H * 0.8], [back, W / 2 - GOAL_HALF, 0]],
      [[gx, W / 2 + GOAL_HALF, GOAL_H], [back, W / 2 + GOAL_HALF, GOAL_H * 0.8], [back, W / 2 + GOAL_HALF, 0]],
      [[back, W / 2 - GOAL_HALF, GOAL_H * 0.8], [back, W / 2 + GOAL_HALF, GOAL_H * 0.8]],
    ];
    for (const [lines, style] of [[net, "rgba(255,255,255,0.35)"], [posts, "#ffffff"]] as const) {
      ctx.strokeStyle = style;
      for (const line of lines) {
        // Off-screen goals project as hidden points; never connect to them.
        const pts = line.map(([x, y, z]) => cam.project(x, y, cam.hasHeight ? z : 0));
        if (pts.some((p) => p.scale <= 0)) continue;
        ctx.beginPath();
        pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
        ctx.stroke();
      }
    }
  }
}

export interface TeamColors {
  shirt: string;
  trim: string;
}

export function teamColors(match: Match, p: Player): TeamColors {
  const c = match.meta.teams[p.team].colors;
  return { shirt: p.isGK ? c.goalkeeper : c.primary, trim: c.secondary };
}

/** Players and ball, back to front. Top-down cameras draw discs, 3D cameras figures. */
export function drawPeople(ctx: CanvasRenderingContext2D, cam: Camera, match: Match, s: Snapshot) {
  type Item = { depth: number; draw: () => void };
  const items: Item[] = [];
  for (const p of match.players) {
    if (!s.visible[p.index]) continue;
    const x = s.x[p.index];
    const y = s.y[p.index];
    const foot = cam.project(x, y, 0);
    if (foot.scale <= 0) continue;
    const col = teamColors(match, p);
    if (cam.hasHeight) {
      const head = cam.project(x, y, 1.82);
      const phase = s.dist[p.index] * 2.2 + hash(p.id);
      const stride = Math.min(s.speed[p.index] / 3, 1);
      items.push({ depth: foot.depth, draw: () => drawFigure(ctx, foot, head, col, SKIN[hash(p.id) % SKIN.length], phase, stride) });
    } else {
      items.push({ depth: foot.depth, draw: () => drawDisc(ctx, foot.x, foot.y, Math.max(5, 0.95 * foot.scale), col) });
    }
  }
  if (s.ball.visible) {
    const b = s.ball;
    const shadow = cam.project(b.x, b.y, 0);
    const ball = cam.project(b.x, b.y, cam.hasHeight ? b.z + 0.11 : 0);
    if (ball.scale > 0) {
      items.push({
        depth: shadow.depth - 0.01,
        draw: () => {
          const r = Math.max(3, 0.13 * ball.scale);
          ctx.fillStyle = "rgba(0,0,0,0.35)";
          ctx.beginPath();
          ctx.ellipse(shadow.x, shadow.y, r * 1.1, r * (cam.hasHeight ? 0.45 : 1.1), 0, 0, 2 * Math.PI);
          ctx.fill();
          ctx.fillStyle = "#ffffff";
          ctx.strokeStyle = "#111";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(ball.x, ball.y, r, 0, 2 * Math.PI);
          ctx.fill();
          ctx.stroke();
        },
      });
    }
  }
  items.sort((a, b) => b.depth - a.depth);
  for (const it of items) it.draw();
}

function drawFigure(
  ctx: CanvasRenderingContext2D,
  foot: { x: number; y: number },
  head: { x: number; y: number },
  col: TeamColors,
  skin: string,
  phase: number,
  stride: number,
) {
  const h = foot.y - head.y;
  if (h < 3) return;
  const w = h * 0.3;
  const x = foot.x;
  const y = foot.y;
  ctx.fillStyle = "rgba(0,0,0,0.3)";
  ctx.beginPath();
  ctx.ellipse(x, y, w * 0.8, w * 0.22, 0, 0, 2 * Math.PI);
  ctx.fill();
  // Legs swing with distance covered, so running players visibly stride.
  const swing = Math.sin(phase) * w * 0.28 * stride;
  ctx.strokeStyle = "#1a1a1a";
  ctx.lineCap = "round";
  ctx.lineWidth = Math.max(1.5, w * 0.24);
  ctx.beginPath();
  ctx.moveTo(x - w * 0.14, y - h * 0.45);
  ctx.lineTo(x - w * 0.14 + swing, y - h * 0.02);
  ctx.moveTo(x + w * 0.14, y - h * 0.45);
  ctx.lineTo(x + w * 0.14 - swing, y - h * 0.02);
  ctx.stroke();
  ctx.fillStyle = col.trim;
  ctx.fillRect(x - w * 0.38, y - h * 0.55, w * 0.76, h * 0.13);
  ctx.fillStyle = col.shirt;
  roundRect(ctx, x - w * 0.5, y - h * 0.84, w, h * 0.31, w * 0.18);
  ctx.fill();
  ctx.strokeStyle = "rgba(0,0,0,0.35)";
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.fillStyle = skin;
  ctx.beginPath();
  ctx.arc(x, y - h * 0.92, Math.max(1.5, h * 0.08), 0, 2 * Math.PI);
  ctx.fill();
}

function drawDisc(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, col: TeamColors) {
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  ctx.beginPath();
  ctx.arc(x + 1.5, y + 2, r, 0, 2 * Math.PI);
  ctx.fill();
  ctx.fillStyle = col.shirt;
  ctx.strokeStyle = col.trim;
  ctx.lineWidth = Math.max(1.5, r * 0.22);
  ctx.beginPath();
  ctx.arc(x, y, r, 0, 2 * Math.PI);
  ctx.fill();
  ctx.stroke();
}

export function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

// ---------------------------------------------------------------- selection

export function drawTrail(ctx: CanvasRenderingContext2D, cam: Camera, pts: Pt[], color: string) {
  if (pts.length < 2) return;
  const mid = cam.project(pts[pts.length - 1][0], pts[pts.length - 1][1], 0);
  const width = Math.max(2, 0.35 * mid.scale);
  ctx.lineCap = "round";
  ctx.strokeStyle = color;
  for (let i = 1; i < pts.length; i++) {
    const a = cam.project(pts[i - 1][0], pts[i - 1][1], 0);
    const b = cam.project(pts[i][0], pts[i][1], 0);
    if (a.scale <= 0 || b.scale <= 0) continue;
    ctx.globalAlpha = 0.85 * (i / pts.length) ** 1.5;
    ctx.lineWidth = width * (0.4 + 0.6 * (i / pts.length));
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

export function drawSelectionRing(ctx: CanvasRenderingContext2D, cam: Camera, x: number, y: number, color: string, time: number) {
  const pulse = 0.5 + 0.5 * Math.sin(time * 4);
  ctx.save();
  ctx.shadowColor = color;
  ctx.shadowBlur = 16;
  ctx.fillStyle = hexAlpha(color, 0.22);
  groundPath(ctx, cam, circlePoints(x, y, 1.2), true);
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.stroke();
  ctx.globalAlpha = 0.6 * (1 - pulse);
  ctx.lineWidth = 2;
  groundPath(ctx, cam, circlePoints(x, y, 1.4 + pulse * 1.2), true);
  ctx.stroke();
  ctx.restore();
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

const overlaps = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** Broadcast name card above a selected player; moves up past cards already in `placed`. */
export function drawPlayerCard(
  ctx: CanvasRenderingContext2D,
  cam: Camera,
  match: Match,
  p: Player,
  s: Snapshot,
  placed: Rect[],
) {
  const x = s.x[p.index];
  const y = s.y[p.index];
  const top = cam.project(x, y, cam.hasHeight ? 2.1 : 0);
  if (top.scale <= 0) return;
  const anchorY = cam.hasHeight ? top.y : top.y - Math.max(8, top.scale * 1.4);
  const team = match.meta.teams[p.team];
  const badge = p.number !== null ? String(p.number) : p.isGK ? "GK" : "•";
  const name = p.label.toUpperCase();
  const kmh = (s.speed[p.index] * 3.6).toFixed(1);
  const km = (s.dist[p.index] / 1000).toFixed(2);
  const stats = `${kmh} km/h   ${km} km`;

  ctx.save();
  ctx.font = `700 17px ${FONT}`;
  const nameW = ctx.measureText(name).width;
  ctx.font = `600 14px ${FONT}`;
  const statW = ctx.measureText(stats).width;
  const bw = 34;
  const w = bw + Math.max(nameW, statW) + 20;
  const h = 44;
  const cx = top.x - w / 2;
  let cy = anchorY - h - 16;
  while (placed.some((r) => overlaps(r, { x: cx, y: cy, w, h }))) cy -= h + 6;
  placed.push({ x: cx, y: cy, w, h });

  ctx.strokeStyle = "rgba(255,255,255,0.7)";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(top.x, anchorY - 2);
  ctx.lineTo(top.x, cy + h);
  ctx.stroke();

  ctx.shadowColor = "rgba(0,0,0,0.5)";
  ctx.shadowBlur = 12;
  ctx.fillStyle = "rgba(8,12,22,0.88)";
  roundRect(ctx, cx, cy, w, h, 6);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.fillStyle = p.isGK ? team.colors.goalkeeper : team.colors.primary;
  roundRect(ctx, cx, cy, bw, h, 6);
  ctx.fill();
  ctx.fillRect(cx + bw - 6, cy, 6, h);
  ctx.fillStyle = ACCENT;
  ctx.fillRect(cx + bw, cy + h - 3, w - bw - 6, 3);

  ctx.fillStyle = readableOn(p.isGK ? team.colors.goalkeeper : team.colors.primary);
  ctx.font = `800 19px ${FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(badge, cx + bw / 2, cy + h / 2 + 1);
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#ffffff";
  ctx.font = `700 17px ${FONT}`;
  ctx.fillText(name, cx + bw + 10, cy + 19);
  ctx.fillStyle = "rgba(255,255,255,0.75)";
  ctx.font = `600 14px ${FONT}`;
  ctx.fillText(stats, cx + bw + 10, cy + 36);
  ctx.restore();
}

export function hexAlpha(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

export function readableOn(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  const lum = 0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255);
  return lum > 150 ? "#0b1020" : "#ffffff";
}

/** Text in a dark pill, centred on (x, y). */
export function pill(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color = "#ffffff", bg = "rgba(8,12,22,0.85)") {
  ctx.save();
  ctx.font = `700 14px ${FONT}`;
  const w = ctx.measureText(text).width + 14;
  ctx.fillStyle = bg;
  roundRect(ctx, x - w / 2, y - 11, w, 22, 11);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y + 1);
  ctx.restore();
}

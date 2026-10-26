// Telestration shapes. Everything is stored in pitch metres so drawings stay on
// the grass when the camera moves or the view changes.

import type { Camera } from "./camera";
import { circlePoints, type Pt } from "./pitch";
import { groundPath, hexAlpha } from "./render";

export type Tool = "select" | "arrow" | "circle" | "zone" | "eraser";

export type Shape =
  | { kind: "arrow"; a: Pt; b: Pt; color: string }
  | { kind: "circle"; c: Pt; r: number; color: string }
  | { kind: "zone"; pts: Pt[]; color: string };

export class Drawings {
  shapes: Shape[] = [];
  draft: Shape | null = null;
  private history: Shape[][] = [];

  private commit(next: Shape[]) {
    this.history.push(this.shapes);
    if (this.history.length > 100) this.history.shift();
    this.shapes = next;
  }

  begin(tool: Tool, p: Pt, color: string) {
    if (tool === "arrow") this.draft = { kind: "arrow", a: p, b: p, color };
    else if (tool === "circle") this.draft = { kind: "circle", c: p, r: 0, color };
    else if (tool === "zone") this.draft = { kind: "zone", pts: [p], color };
    else if (tool === "eraser") this.erase(p);
  }

  move(tool: Tool, p: Pt) {
    const d = this.draft;
    if (tool === "eraser") this.erase(p);
    if (!d) return;
    if (d.kind === "arrow") d.b = p;
    else if (d.kind === "circle") d.r = Math.hypot(p[0] - d.c[0], p[1] - d.c[1]);
    else {
      const last = d.pts[d.pts.length - 1];
      if (Math.hypot(p[0] - last[0], p[1] - last[1]) > 0.6) d.pts.push(p);
    }
  }

  end() {
    const d = this.draft;
    this.draft = null;
    if (!d) return;
    const big =
      (d.kind === "arrow" && Math.hypot(d.b[0] - d.a[0], d.b[1] - d.a[1]) > 1.5) ||
      (d.kind === "circle" && d.r > 0.8) ||
      (d.kind === "zone" && d.pts.length > 3);
    if (big) this.commit([...this.shapes, d]);
  }

  cancel() {
    this.draft = null;
  }

  erase(p: Pt) {
    const keep = this.shapes.filter((s) => !hit(s, p));
    if (keep.length !== this.shapes.length) this.commit(keep);
  }

  clear() {
    if (this.shapes.length) this.commit([]);
  }

  undo() {
    const prev = this.history.pop();
    if (prev) this.shapes = prev;
  }

  draw(ctx: CanvasRenderingContext2D, cam: Camera) {
    for (const s of this.shapes) drawShape(ctx, cam, s);
    if (this.draft) drawShape(ctx, cam, this.draft);
  }
}

function hit(s: Shape, [x, y]: Pt): boolean {
  if (s.kind === "arrow") return segDist(x, y, s.a, s.b) < 1.8;
  if (s.kind === "circle") return Math.hypot(x - s.c[0], y - s.c[1]) < s.r + 1.2;
  return inside(s.pts, x, y) || s.pts.some((p, i) => segDist(x, y, p, s.pts[(i + 1) % s.pts.length]) < 1.5);
}

function segDist(x: number, y: number, a: Pt, b: Pt): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / len2)) : 0;
  return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy));
}

function inside(pts: Pt[], x: number, y: number): boolean {
  let c = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i];
    const [xj, yj] = pts[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}

/** Arrow outline on the ground: shaft and head built in metres, then projected. */
function arrowPolygon(a: Pt, b: Pt): Pt[] {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy);
  const ux = dx / len;
  const uy = dy / len;
  const nx = -uy;
  const ny = ux;
  const head = Math.min(2.8, len * 0.45);
  const hw = head * 0.55;
  const sw = 0.38;
  const bx = b[0] - ux * head;
  const by = b[1] - uy * head;
  const pts: Pt[] = [];
  const steps = Math.max(2, Math.ceil((len - head) / 2));
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    pts.push([a[0] + (bx - a[0]) * t + nx * sw, a[1] + (by - a[1]) * t + ny * sw]);
  }
  pts.push([bx + nx * hw, by + ny * hw], [b[0], b[1]], [bx - nx * hw, by - ny * hw]);
  for (let i = steps; i >= 0; i--) {
    const t = i / steps;
    pts.push([a[0] + (bx - a[0]) * t - nx * sw, a[1] + (by - a[1]) * t - ny * sw]);
  }
  return pts;
}

function drawShape(ctx: CanvasRenderingContext2D, cam: Camera, s: Shape) {
  ctx.save();
  ctx.shadowColor = s.color;
  ctx.shadowBlur = 12;
  ctx.lineJoin = "round";
  if (s.kind === "arrow") {
    if (Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]) > 0.3) {
      ctx.fillStyle = hexAlpha(s.color, 0.92);
      ctx.strokeStyle = "rgba(0,0,0,0.45)";
      ctx.lineWidth = 1.5;
      if (groundPath(ctx, cam, arrowPolygon(s.a, s.b), true)) {
        ctx.fill();
        ctx.stroke();
      }
    }
  } else if (s.kind === "circle") {
    const outer = circlePoints(s.c[0], s.c[1], s.r, 64);
    ctx.fillStyle = hexAlpha(s.color, 0.16);
    if (groundPath(ctx, cam, outer, true)) ctx.fill();
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 4;
    if (groundPath(ctx, cam, outer, true)) ctx.stroke();
  } else {
    ctx.fillStyle = hexAlpha(s.color, 0.2);
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 3.5;
    if (groundPath(ctx, cam, s.pts, true)) {
      ctx.fill();
      ctx.stroke();
    }
  }
  ctx.restore();
}

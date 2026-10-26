// Pitch markings as polylines in pitch metres (105 x 68, y = 0 is the far touchline).

export const L = 105;
export const W = 68;
export const GOAL_HALF = 3.66;
export const GOAL_H = 2.44;

export type Pt = [number, number];

function arc(cx: number, cy: number, r: number, a0: number, a1: number, n = 48): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i <= n; i++) {
    const a = a0 + ((a1 - a0) * i) / n;
    out.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return out;
}

function rect(x0: number, y0: number, x1: number, y1: number): Pt[] {
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
}

/** Split long straight segments so they survive non-linear projections (blended views). */
export function densify(line: Pt[], step = 2): Pt[] {
  const out: Pt[] = [line[0]];
  for (let i = 1; i < line.length; i++) {
    const [ax, ay] = line[i - 1];
    const [bx, by] = line[i];
    const n = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / step));
    for (let k = 1; k <= n; k++) out.push([ax + ((bx - ax) * k) / n, ay + ((by - ay) * k) / n]);
  }
  return out;
}

function markings(): Pt[][] {
  const lines: Pt[][] = [rect(0, 0, L, W), [[L / 2, 0], [L / 2, W]], arc(L / 2, W / 2, 9.15, 0, 2 * Math.PI, 72)];
  for (const [gx, s] of [[0, 1], [L, -1]] as const) {
    lines.push(rect(gx, W / 2 - 20.16, gx + s * 16.5, W / 2 + 20.16));
    lines.push(rect(gx, W / 2 - 9.16, gx + s * 5.5, W / 2 + 9.16));
    // Penalty arc: the part of the 9.15 m circle around the spot outside the box.
    const a = Math.acos((16.5 - 11) / 9.15);
    lines.push(s > 0 ? arc(gx + 11, W / 2, 9.15, -a, a, 24) : arc(gx - 11, W / 2, 9.15, Math.PI - a, Math.PI + a, 24));
  }
  for (const [cx, cy, a0] of [[0, 0, 0], [L, 0, Math.PI / 2], [L, W, Math.PI], [0, W, (3 * Math.PI) / 2]] as const) {
    lines.push(arc(cx, cy, 1, a0, a0 + Math.PI / 2, 8));
  }
  return lines.map((l) => densify(l));
}

export const MARKINGS = markings();
export const SPOTS: Pt[] = [[L / 2, W / 2], [11, W / 2], [L - 11, W / 2]];

export function circlePoints(cx: number, cy: number, r: number, n = 48): Pt[] {
  return arc(cx, cy, r, 0, 2 * Math.PI, n);
}

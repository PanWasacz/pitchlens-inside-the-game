// Projections from pitch metres (x, y, height z) to canvas pixels.
//
// TvCamera is a fixed broadcast camera on the near side that pans, tilts and zooms
// (own perspective matrix). TopCamera is the tactical view. VideoCamera uses the
// per-frame homography of the CV pipeline. BlendCamera animates between two.

import { L, W } from "./pitch";

export interface Projected {
  x: number;
  y: number;
  /** Pixels per metre at that point; <= 0 when the point is not visible. */
  scale: number;
  /** Distance from the camera, for back-to-front sorting. */
  depth: number;
}

export interface Camera {
  project(x: number, y: number, z?: number): Projected;
  /** Like project, but continuous for points outside the picture (used while animating views). */
  projectLoose?(x: number, y: number, z?: number): Projected;
  /** Canvas pixel -> point on the grass, or null if the ray misses the ground. */
  unproject(sx: number, sy: number): [number, number] | null;
  /** True when height can be shown (3D cameras). */
  readonly hasHeight: boolean;
}

const HIDDEN: Projected = { x: 0, y: 0, scale: 0, depth: Infinity };

type V3 = [number, number, number];
const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (a: V3): V3 => {
  const n = Math.hypot(a[0], a[1], a[2]);
  return [a[0] / n, a[1] / n, a[2] / n];
};
// Pitch (x right, y towards the near side, z up) is left-handed; flip y for the world frame.
const world = (x: number, y: number, z: number): V3 => [x, -y, z];

export class TvCamera implements Camera {
  readonly hasHeight = true;
  /** Camera position: halfway line, 32 m behind the near touchline, 21 m up. */
  eye: V3 = world(L / 2, W + 32, 21);
  target: V3 = world(L / 2, W / 2, 0);
  /** Pitch width (m) visible across the screen at the target. */
  span = 58;
  private r: V3 = [1, 0, 0];
  private u: V3 = [0, 0, 1];
  private f: V3 = [0, 1, 0];
  private focal = 1000;
  private cx = 0;
  private cy = 0;

  /** Smoothly follow a point on the pitch; snap after jumps. */
  follow(px: number, py: number, dt: number, snap = false) {
    const tx = Math.min(Math.max(px, 14), L - 14);
    const ty = W / 2 + (py - W / 2) * 0.4;
    const goal = world(tx, ty, 0);
    const k = snap ? 1 : 1 - Math.exp(-dt / 0.55);
    this.target = [this.target[0] + (goal[0] - this.target[0]) * k, this.target[1] + (goal[1] - this.target[1]) * k, 0];
  }

  update(width: number, height: number) {
    this.f = unit(sub(this.target, this.eye));
    this.r = unit(cross(this.f, [0, 0, 1]));
    this.u = cross(this.r, this.f);
    const d = Math.hypot(...sub(this.target, this.eye));
    // Portrait screens: zoom by height instead and crop the sides, like a tighter shot.
    const frameWidth = Math.max(width, height * 1.45);
    this.focal = frameWidth / 2 / (this.span / 2 / d);
    this.cx = width / 2;
    this.cy = height * 0.44; // slightly above centre: less sky, more grass
  }

  project(x: number, y: number, z = 0): Projected {
    const d = sub(world(x, y, z), this.eye);
    const zc = dot(d, this.f);
    if (zc < 1) return HIDDEN;
    const k = this.focal / zc;
    return { x: this.cx + dot(d, this.r) * k, y: this.cy - dot(d, this.u) * k, scale: k, depth: zc };
  }

  unproject(sx: number, sy: number): [number, number] | null {
    const a = (sx - this.cx) / this.focal;
    const b = -(sy - this.cy) / this.focal;
    const dir: V3 = [
      this.f[0] + this.r[0] * a + this.u[0] * b,
      this.f[1] + this.r[1] * a + this.u[1] * b,
      this.f[2] + this.r[2] * a + this.u[2] * b,
    ];
    if (dir[2] >= -1e-6) return null;
    const s = -this.eye[2] / dir[2];
    return [this.eye[0] + dir[0] * s, -(this.eye[1] + dir[1] * s)];
  }
}

export class TopCamera implements Camera {
  readonly hasHeight = false;
  private s = 1;
  private ox = 0;
  private oy = 0;

  /** Fit the pitch (plus margin) into the area left free by the UI. */
  update(width: number, height: number, inset = { top: 70, bottom: 120, left: 80, right: 24 }) {
    const m = 4;
    const aw = width - inset.left - inset.right;
    const ah = height - inset.top - inset.bottom;
    this.s = Math.min(aw / (L + 2 * m), ah / (W + 2 * m));
    this.ox = inset.left + (aw - L * this.s) / 2;
    this.oy = inset.top + (ah - W * this.s) / 2;
  }

  project(x: number, y: number): Projected {
    return { x: this.ox + x * this.s, y: this.oy + y * this.s, scale: this.s, depth: y };
  }

  unproject(sx: number, sy: number): [number, number] {
    return [(sx - this.ox) / this.s, (sy - this.oy) / this.s];
  }
}

/**
 * Calibrated broadcast camera for overlays on the original video: fixed position,
 * per-frame rotation and focal length, one radial distortion term (see
 * pitchlens_cv/calibrate.py). Works in the right-handed world (x, -y, z).
 */
export class VideoCamera implements Camera {
  readonly hasHeight = true;
  // R (9, row-major), C (3), f, cx, cy, k1
  private m: Float64Array = new Float64Array([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 10, 1000, 960, 540, 0]);
  private k = 1;
  private ox = 0;
  private oy = 0;
  private w = 1;
  private h = 1;
  /** Virtual zoom on top of the broadcast framing (3D view only): screen = p * zoom + t. */
  zoom = 1;
  private tx = 0;
  private ty = 0;
  private fx = 0;
  private fy = 0;

  /** Video frame (vw x vh) letterboxed into the canvas, like object-fit: contain. */
  update(width: number, height: number, vw: number, vh: number, camera: Float64Array | null) {
    this.w = width;
    this.h = height;
    this.k = Math.min(width / vw, height / vh);
    this.ox = (width - vw * this.k) / 2;
    this.oy = (height - vh * this.k) / 2;
    if (camera) this.m = camera;
  }

  /** Zoom factor 1x..4x. At 1x the framing is exactly the broadcast one. */
  setZoom(zoom: number) {
    this.zoom = Math.min(4, Math.max(1, zoom));
    this.reframe();
  }

  /**
   * Point (unzoomed screen coordinates, usually the ball) the zoom is centred on.
   * It slides to the middle of the screen as the zoom grows, like the TV camera.
   */
  setFocus(fx: number, fy: number) {
    this.fx = fx;
    this.fy = fy;
    this.reframe();
  }

  private reframe() {
    const z = this.zoom;
    const a = Math.min(1, (z - 1) / 0.5);
    this.tx = this.fx + (this.w / 2 - this.fx) * a - this.fx * z;
    this.ty = this.fy + (this.h * 0.55 - this.fy) * a - this.fy * z;
  }

  project(x: number, y: number, z = 0): Projected {
    return this.projectWith(x, y, z, false);
  }

  projectLoose(x: number, y: number, z = 0): Projected {
    return this.projectWith(x, y, z, true);
  }

  private projectWith(x: number, y: number, z: number, loose: boolean): Projected {
    const m = this.m;
    const dx = x - m[9];
    const dy = -y - m[10];
    const dz = z - m[11];
    const xc = m[0] * dx + m[1] * dy + m[2] * dz;
    const yc = m[3] * dx + m[4] * dy + m[5] * dz;
    let zc = m[6] * dx + m[7] * dy + m[8] * dz;
    if (zc < 0.5) {
      if (!loose) return HIDDEN;
      zc = 0.5;
    }
    const xn = xc / zc;
    const yn = yc / zc;
    let r2 = xn * xn + yn * yn;
    const k1 = m[15];
    // Beyond this radius the distortion polynomial folds back into the picture.
    const limit = k1 ? 0.9 / (3 * Math.abs(k1)) : Infinity;
    if (r2 > limit) {
      if (!loose) return HIDDEN;
      r2 = limit;
    }
    const d = 1 + k1 * r2;
    const f = m[12];
    const u = f * xn * d + m[13];
    const v = f * yn * d + m[14];
    const zm = this.zoom;
    return {
      x: (this.ox + u * this.k) * zm + this.tx,
      y: (this.oy + v * this.k) * zm + this.ty,
      scale: ((f * d) / zc) * this.k * zm,
      depth: zc,
    };
  }

  unproject(sx: number, sy: number): [number, number] | null {
    const m = this.m;
    const f = m[12];
    const xd = (((sx - this.tx) / this.zoom - this.ox) / this.k - m[13]) / f;
    const yd = (((sy - this.ty) / this.zoom - this.oy) / this.k - m[14]) / f;
    // Undistort by fixed-point iteration.
    let xn = xd;
    let yn = yd;
    for (let i = 0; i < 8; i++) {
      const d = 1 + m[15] * (xn * xn + yn * yn);
      xn = xd / d;
      yn = yd / d;
    }
    // Ray in world coordinates: R^T * (xn, yn, 1).
    const rx = m[0] * xn + m[3] * yn + m[6];
    const ry = m[1] * xn + m[4] * yn + m[7];
    const rz = m[2] * xn + m[5] * yn + m[8];
    if (rz >= -1e-9) return null;
    const s = -m[11] / rz;
    return [m[9] + rx * s, -(m[10] + ry * s)];
  }
}

/** Interpolates screen positions between two cameras for animated view changes. */
export class BlendCamera implements Camera {
  constructor(private from: Camera, private to: Camera, private a: number) {}

  get hasHeight() {
    return this.a < 0.5 ? this.from.hasHeight : this.to.hasHeight;
  }

  project(x: number, y: number, z = 0): Projected {
    const p = this.from.projectLoose ? this.from.projectLoose(x, y, z) : this.from.project(x, y, z);
    const q = this.to.projectLoose ? this.to.projectLoose(x, y, z) : this.to.project(x, y, z);
    if (p.scale <= 0) return q;
    if (q.scale <= 0) return p;
    const a = this.a;
    return {
      x: p.x + (q.x - p.x) * a,
      y: p.y + (q.y - p.y) * a,
      scale: p.scale + (q.scale - p.scale) * a,
      depth: a < 0.5 ? p.depth : q.depth,
    };
  }

  unproject(sx: number, sy: number) {
    return (this.a < 0.5 ? this.from : this.to).unproject(sx, sy);
  }
}

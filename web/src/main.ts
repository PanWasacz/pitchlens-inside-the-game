import { drawDistances, drawFormation, drawOffside } from "./analysis";
import { BlendCamera, TopCamera, TvCamera, VideoCamera, type Camera } from "./camera";
import { DATASETS, datasetAvailable, loadMatch, type Dataset, type Match, type MatchEvent, type TeamKey } from "./data";
import { Drawings, type Tool } from "./drawings";
import { L, MARKINGS, W, type Pt } from "./pitch";
import {
  ACCENT,
  drawBackdrop,
  drawPeople,
  drawPitch,
  drawPlayerCard,
  drawSelectionRing,
  drawTrail,
  hexAlpha,
  type Rect,
} from "./render";

const $ = <T extends HTMLElement = HTMLElement>(sel: string) => document.querySelector(sel) as T;
const $$ = <T extends HTMLElement = HTMLElement>(sel: string) => [...document.querySelectorAll(sel)] as T[];

type View = "main" | "recon" | "top";
type Toggle = "shapeHome" | "shapeAway" | "offside" | "distances";

const DRAW_COLORS = ["#FFE14D", "#FFFFFF", "#2BF5B6", "#FF5A5F"];
const VIEW_ANIM_MS = 650;
const PLAY_ICON = "M7 4l13 8-13 8z";
const PAUSE_ICON = "M7 4h4v16H7zM13 4h4v16h-4z";

function fmtClock(t: number): string {
  const s = Math.max(0, Math.floor(t));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

const ease = (a: number) => (a < 0.5 ? 2 * a * a : 1 - (-2 * a + 2) ** 2 / 2);

function segDist(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

class App {
  private readonly canvas = $<HTMLCanvasElement>("#canvas");
  private readonly ctx = this.canvas.getContext("2d")!;
  private readonly mini = $<HTMLCanvasElement>("#minimap");
  private readonly mctx = this.mini.getContext("2d")!;
  private readonly video: HTMLVideoElement | null;
  private readonly tv = new TvCamera();
  private readonly top = new TopCamera();
  private readonly vid = new VideoCamera();
  /** Same calibrated camera for the 3D view, which may additionally zoom. */
  private readonly recon = new VideoCamera();
  private readonly drawings = new Drawings();
  private readonly keyMoments: MatchEvent[];
  private readonly goals: MatchEvent[];

  private w = 0;
  private h = 0;
  private t = 0;
  private playing = false;
  private rate = 1;
  private view: View = "main";
  private viewFrom: View = "main";
  private viewStart = -Infinity;
  private selected: number[] = [];
  private toggles: Record<Toggle, boolean> = { shapeHome: false, shapeAway: false, offside: false, distances: false };
  private tool: Tool = "select";
  private color = DRAW_COLORS[0];
  private drawing = false;
  private pointers = new Map<number, [number, number]>();
  private pinch: { dist: number; span: number; zoom: number } | null = null;
  private focus: [number, number] | null = null; // smoothed ball position for the 3D zoom
  private snapCamera = true;
  private lastNow = performance.now();
  private bannerTimer = 0;
  private scoreSecond = -1;

  constructor(private readonly match: Match, ds: Dataset) {
    this.video = ds.video ? $<HTMLVideoElement>("#video") : null;
    if (this.video && ds.video) this.video.src = ds.video;
    const ev = match.events;
    this.keyMoments = ev.filter((e) => e.type === "shot" || e.type === "offside").sort((a, b) => a.t - b.t);
    this.goals = ev.filter((e) => e.type === "goal");
    this.setupUi();
    if (this.video) {
      this.view = this.viewFrom = "recon";
      for (const b of $$("[data-view]")) b.setAttribute("aria-pressed", String(b.dataset.view === "recon"));
    }
    this.resize();
    addEventListener("resize", () => this.resize());
    requestAnimationFrame((now) => this.frame(now));
  }

  // ------------------------------------------------------------------ UI

  private setupUi() {
    const teams = this.match.meta.teams;
    $('[data-toggle="shapeHome"]').textContent = `${teams.home.short} shape`;
    $('[data-toggle="shapeAway"]').textContent = `${teams.away.short} shape`;
    if (this.video) {
      $('[data-view="main"]').textContent = "Video";
      $('[data-view="recon"]').hidden = false;
    }

    for (const b of $$<HTMLButtonElement>("[data-view]")) b.onclick = () => this.setView(b.dataset.view as View);
    for (const b of $$<HTMLButtonElement>("[data-toggle]")) {
      b.onclick = () => this.toggle(b.dataset.toggle as Toggle);
    }
    for (const b of $$<HTMLButtonElement>("[data-tool]")) b.onclick = () => this.setTool(b.dataset.tool as Tool);
    for (const b of $$<HTMLButtonElement>("[data-rate]")) b.onclick = () => this.setRate(Number(b.dataset.rate));

    const sw = $("#swatches");
    for (const c of DRAW_COLORS) {
      const b = document.createElement("button");
      b.style.background = c;
      b.title = "Drawing colour";
      b.setAttribute("aria-pressed", String(c === this.color));
      b.onclick = () => {
        this.color = c;
        for (const o of sw.children) o.setAttribute("aria-pressed", String(o === b));
      };
      sw.append(b);
    }
    $("#undo").onclick = () => this.drawings.undo();
    $("#clear").onclick = () => this.drawings.clear();
    $("#play").onclick = () => this.togglePlay();
    $("#prevMoment").onclick = () => this.jumpMoment(-1);
    $("#nextMoment").onclick = () => this.jumpMoment(1);
    $("#insightsBtn").onclick = () => {
      const panel = $("#insights");
      panel.hidden = !panel.hidden;
      $("#insightsBtn").setAttribute("aria-pressed", String(!panel.hidden));
    };
    $("#explain").onclick = () => this.explain();
    $("#helpBtn").onclick = () => ($("#help").hidden = !$("#help").hidden);
    $("#help").onclick = () => ($("#help").hidden = true);
    this.buildMoments();

    this.buildTimeline();
    this.setupPointer();
    this.setupKeys();
    this.updateScorebug();
  }

  private setView(v: View) {
    if (v === this.view) return;
    this.viewFrom = this.view;
    this.view = v;
    this.viewStart = performance.now();
    for (const b of $$("[data-view]")) b.setAttribute("aria-pressed", String(b.dataset.view === v));
  }

  private toggle(k: Toggle) {
    this.toggles[k] = !this.toggles[k];
    $(`[data-toggle="${k}"]`).setAttribute("aria-pressed", String(this.toggles[k]));
  }

  private setTool(t: Tool) {
    this.tool = t;
    this.canvas.dataset.tool = t;
    for (const b of $$("[data-tool]")) b.setAttribute("aria-pressed", String(b.dataset.tool === t));
  }

  private setRate(r: number) {
    this.rate = r;
    if (this.video) this.video.playbackRate = r;
    for (const b of $$("[data-rate]")) b.setAttribute("aria-pressed", String(Number(b.dataset.rate) === r));
  }

  private togglePlay() {
    if (this.video) {
      if (this.video.paused) void this.video.play();
      else this.video.pause();
    } else {
      if (!this.playing && this.t >= this.match.duration) this.seek(0);
      this.playing = !this.playing;
    }
  }

  private pause() {
    if (this.video) this.video.pause();
    this.playing = false;
  }

  private seek(t: number) {
    this.t = Math.min(Math.max(t, 0), this.match.duration);
    if (this.video) this.video.currentTime = this.t;
    this.snapCamera = true;
  }

  private jumpMoment(dir: 1 | -1) {
    // Land a few seconds before the shot so the build-up is visible.
    const pre = 5;
    const list = this.keyMoments;
    const target =
      dir > 0 ? list.find((e) => e.t - pre > this.t + 0.5) : [...list].reverse().find((e) => e.t - pre < this.t - 1);
    if (target) this.seek(target.t - pre);
  }

  private playerName(id: unknown): string {
    const p = this.match.players.find((q) => q.id === id);
    return p ? p.label : "";
  }

  private buildMoments() {
    const list = $("#moments");
    if (!this.keyMoments.length) {
      list.innerHTML = `<p class="muted">No events for this source.</p>`;
      return;
    }
    for (const e of this.keyMoments) {
      const outcome = e.type === "offside" ? "offside" : String(e.outcome ?? "");
      const team = e.team ? this.match.meta.teams[e.team].short : "";
      const tag = outcome === "goal" ? "GOAL" : outcome === "saved" ? "SAVE" : outcome === "offside" ? "OFFSIDE" : "SHOT";
      const b = document.createElement("button");
      b.className = "moment";
      b.innerHTML =
        `<span class="mt">${fmtClock(e.t)}</span>` +
        `<span class="mk ${outcome === "goal" ? "goal" : ""}">${tag}</span>` +
        `<span class="who">${this.playerName(e.player)} · ${team}</span>`;
      b.onclick = () => this.seek(e.t - 5);
      list.append(b);
    }
  }

  private buildTimeline() {
    const markers = $("#markers");
    const dur = this.match.duration;
    for (const e of this.keyMoments) {
      const m = document.createElement("div");
      const outcome = e.type === "offside" ? "offside" : String(e.outcome ?? "");
      m.className = `m ${outcome === "goal" ? "goal" : outcome === "saved" ? "" : outcome === "offside" ? "offside" : "miss"}`;
      m.style.left = `${(e.t / dur) * 100}%`;
      if (outcome === "goal" && e.team) m.style.background = this.match.meta.teams[e.team].colors.primary;
      const xg = typeof e.xg === "number" ? `, xG ${e.xg.toFixed(2)}` : "";
      m.title =
        outcome === "offside"
          ? `${fmtClock(e.t)}  OFFSIDE - ${this.playerName(e.player)}`
          : `${fmtClock(e.t)}  ${outcome === "goal" ? "GOAL" : "Shot"} - ${this.playerName(e.player)} (${outcome.replace("_", " ")}${xg})`;
      markers.append(m);
    }
    const tl = $("#timeline");
    const seekTo = (ev: PointerEvent) => {
      const r = $("#track").getBoundingClientRect();
      this.seek(((ev.clientX - r.left) / r.width) * dur);
    };
    tl.onpointerdown = (ev) => {
      tl.setPointerCapture(ev.pointerId);
      seekTo(ev);
      tl.onpointermove = seekTo;
    };
    tl.onpointerup = tl.onpointercancel = () => {
      tl.onpointermove = null;
    };
  }

  private updateScorebug() {
    const { home, away } = this.match.meta.teams;
    const synthetic = this.match.meta.source === "synthetic";
    const score = { home: 0, away: 0 };
    for (const g of this.goals) if (g.t <= this.t && g.team) score[g.team as TeamKey]++;
    const team = (k: TeamKey) =>
      `<div class="team"><span class="chip" style="background:${this.match.meta.teams[k].colors.primary}"></span>${this.match.meta.teams[k].short}</div>`;
    $("#scorebug").innerHTML =
      team("home") +
      `<div class="score">${synthetic ? `${score.home} - ${score.away}` : "vs"}</div>` +
      team("away") +
      `<div class="time">${fmtClock(this.t)}</div>`;
    $("#scorebug").title = `${home.name} vs ${away.name}`;
  }

  private showBanner(e: MatchEvent) {
    const team = e.team ? this.match.meta.teams[e.team] : null;
    const b = $("#banner");
    const goal = e.type === "goal";
    const who = this.playerName(goal ? e.scorer : e.player).toUpperCase();
    b.innerHTML = `<div class="tag${goal ? "" : " flag"}">${goal ? "GOAL" : "OFFSIDE"}</div><div class="who">${who}${team ? ` · ${team.short}` : ""}</div>`;
    b.classList.add("show");
    clearTimeout(this.bannerTimer);
    this.bannerTimer = window.setTimeout(() => b.classList.remove("show"), 4000);
  }

  private async explain() {
    const out = $("#explainOut");
    out.textContent = "Asking the analyst…";
    const body = {
      source: this.match.meta.source,
      t: this.t,
      selected: this.selected.map((i) => this.match.players[i].id),
      events: this.match.events.filter((e) => Math.abs(e.t - this.t) < 10),
    };
    try {
      const r = await fetch("/api/explain", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = (await r.json().catch(() => null)) as { message?: string; text?: string } | null;
      out.textContent = r.ok && data?.text ? data.text : (data?.message ?? "Agent explanations are not connected yet.");
    } catch {
      out.textContent = "Agent explanations are not connected yet.";
    }
  }

  // ------------------------------------------------------------- input

  private mainCamera(): Camera {
    return this.video ? this.vid : this.tv;
  }

  private currentCamera(now: number): Camera {
    const a = Math.min(1, (now - this.viewStart) / VIEW_ANIM_MS);
    // "recon" redraws the tracked match through the calibrated broadcast camera.
    const cam = (v: View) => (v === "top" ? this.top : v === "recon" ? this.recon : this.mainCamera());
    return a < 1 ? new BlendCamera(cam(this.viewFrom), cam(this.view), ease(a)) : cam(this.view);
  }

  private pickPlayer(cam: Camera, sx: number, sy: number): number {
    const s = this.match.sample(this.t);
    let best = -1;
    let bestD = Infinity;
    for (const p of this.match.players) {
      if (!s.visible[p.index]) continue;
      const foot = cam.project(s.x[p.index], s.y[p.index], 0);
      if (foot.scale <= 0) continue;
      const head = cam.hasHeight ? cam.project(s.x[p.index], s.y[p.index], 1.8) : foot;
      const d = segDist(sx, sy, foot.x, foot.y, head.x, head.y);
      if (d < Math.max(16, foot.scale * 1.0) && d < bestD) {
        bestD = d;
        best = p.index;
      }
    }
    return best;
  }

  private setupPointer() {
    const c = this.canvas;
    const local = (e: MouseEvent): [number, number] => {
      const r = c.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    const pinchDist = () => {
      const [a, b] = [...this.pointers.values()];
      return Math.hypot(a[0] - b[0], a[1] - b[1]);
    };
    c.onpointerdown = (e) => {
      const [x, y] = local(e);
      this.pointers.set(e.pointerId, [x, y]);
      if (this.pointers.size === 2) {
        // Second finger: pinch-zoom the TV camera instead of drawing.
        this.drawings.cancel();
        this.drawing = false;
        if ((!this.video && this.view === "main") || this.view === "recon") {
          this.pinch = { dist: pinchDist(), span: this.tv.span, zoom: this.recon.zoom };
        }
        return;
      }
      if (this.pointers.size > 2) return;
      const cam = this.currentCamera(performance.now());
      if (this.tool === "select") {
        const i = this.pickPlayer(cam, x, y);
        if (i < 0) this.selected = [];
        else if (this.selected.includes(i)) this.selected = this.selected.filter((j) => j !== i);
        else this.selected = [...this.selected, i];
        return;
      }
      const g = cam.unproject(x, y);
      if (!g) return;
      c.setPointerCapture(e.pointerId);
      this.drawing = true;
      this.drawings.begin(this.tool, g, this.color);
      if (this.tool !== "eraser") this.pause(); // telestration happens on a still picture
    };
    c.onpointermove = (e) => {
      const [x, y] = local(e);
      if (this.pointers.has(e.pointerId)) this.pointers.set(e.pointerId, [x, y]);
      if (this.pinch && this.pointers.size === 2) {
        const ratio = Math.max(pinchDist(), 1) / this.pinch.dist;
        if (this.view === "recon") this.recon.setZoom(this.pinch.zoom * ratio);
        else this.tv.span = Math.min(110, Math.max(24, this.pinch.span / ratio));
        return;
      }
      if (!this.drawing) return;
      const g = this.currentCamera(performance.now()).unproject(x, y);
      if (g) this.drawings.move(this.tool, g);
    };
    c.onpointerup = c.onpointercancel = (e) => {
      this.pointers.delete(e.pointerId);
      if (this.pointers.size < 2) this.pinch = null;
      if (!this.drawing) return;
      this.drawing = false;
      this.drawings.end();
    };
    c.onwheel = (e) => {
      if (this.view === "recon") {
        e.preventDefault();
        this.recon.setZoom(this.recon.zoom * Math.exp(-e.deltaY * 0.0015));
        return;
      }
      if (this.video || this.view !== "main") return;
      e.preventDefault();
      this.tv.span = Math.min(110, Math.max(24, this.tv.span * Math.exp(e.deltaY * 0.001)));
    };
  }

  private setupKeys() {
    addEventListener("keydown", (e) => {
      if (e.target instanceof HTMLSelectElement) return;
      const k = e.key.toLowerCase();
      const step = 1 / this.match.meta.fps;
      if ((e.ctrlKey || e.metaKey) && k === "z") this.drawings.undo();
      else if (e.ctrlKey || e.metaKey || e.altKey) return;
      else if (k === " ") this.togglePlay();
      else if (k === "arrowleft") e.shiftKey ? this.jumpMoment(-1) : this.seek(this.t - 5);
      else if (k === "arrowright") e.shiftKey ? this.jumpMoment(1) : this.seek(this.t + 5);
      else if (k === ",") this.seek(this.t - step);
      else if (k === ".") this.seek(this.t + step);
      else if (k === "1") this.setView("main");
      else if (k === "2") this.setView("top");
      else if (k === "3" && this.video) this.setView("recon");
      else if (k === "v") this.setTool("select");
      else if (k === "a") this.setTool("arrow");
      else if (k === "c") this.setTool("circle");
      else if (k === "z") this.setTool("zone");
      else if (k === "e") this.setTool("eraser");
      else if (k === "o") this.toggle("offside");
      else if (k === "d") this.toggle("distances");
      else if (k === "delete" || k === "backspace") this.drawings.clear();
      else if (k === "escape") {
        this.selected = [];
        $("#help").hidden = true;
      } else if (k === "?" || k === "h") $("#help").hidden = !$("#help").hidden;
      else return;
      e.preventDefault();
    });
  }

  // ------------------------------------------------------------ frame loop

  private resize() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    this.w = innerWidth;
    this.h = innerHeight;
    this.canvas.width = Math.round(this.w * dpr);
    this.canvas.height = Math.round(this.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const mw = this.mini.clientWidth || 232;
    const mh = this.mini.clientHeight || 154;
    this.mini.width = Math.round(mw * dpr);
    this.mini.height = Math.round(mh * dpr);
    this.mctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.snapCamera = true;
  }

  private frame(now: number) {
    const dt = Math.min((now - this.lastNow) / 1000, 0.1);
    this.lastNow = now;
    const prevT = this.t;
    if (this.video) {
      this.t = this.video.currentTime;
      this.playing = !this.video.paused;
    } else if (this.playing) {
      this.t = Math.min(this.t + dt * this.rate, this.match.duration);
      if (this.t >= this.match.duration) this.playing = false;
    }
    if (this.playing && !this.snapCamera) {
      const hit = this.match.events.find((g) => (g.type === "goal" || g.type === "offside") && g.t > prevT && g.t <= this.t);
      if (hit) this.showBanner(hit);
    }
    this.render(now, dt);
    this.updateTransport();
    requestAnimationFrame((n) => this.frame(n));
  }

  private updateTransport() {
    const f = (this.t / this.match.duration) * 100;
    $("#progress").style.width = `${f}%`;
    $("#playhead").style.left = `${f}%`;
    $("#clock").textContent = fmtClock(this.t);
    $("#playIcon").innerHTML = `<path d="${this.playing ? PAUSE_ICON : PLAY_ICON}"/>`;
    if (Math.floor(this.t) !== this.scoreSecond) {
      this.scoreSecond = Math.floor(this.t);
      this.updateScorebug();
    }
  }

  private render(now: number, dt: number) {
    const { ctx, w, h, match } = this;
    const s = match.sample(this.t);
    const meta = match.meta;

    if (this.video && meta.video) {
      this.vid.update(w, h, meta.video.width, meta.video.height, s.camera);
      this.recon.update(w, h, meta.video.width, meta.video.height, s.camera);
      // The 3D zoom follows the ball (where the broadcast camera shows it), smoothed.
      if (s.ball.visible) {
        const b = this.vid.project(s.ball.x, s.ball.y, 0);
        if (b.scale > 0) {
          const k = this.snapCamera || !this.focus ? 1 : 1 - Math.exp(-dt / 0.4);
          const f = this.focus ?? [b.x, b.y];
          this.focus = [f[0] + (b.x - f[0]) * k, f[1] + (b.y - f[1]) * k];
        }
      }
      const f = this.focus ?? [w / 2, h / 2];
      this.recon.setFocus(f[0], f[1]);
    } else {
      const bx = s.ball.visible ? s.ball.x : L / 2;
      const by = s.ball.visible ? s.ball.y : W / 2;
      this.tv.follow(bx, by, dt, this.snapCamera);
      this.tv.update(w, h);
    }
    this.snapCamera = false;
    this.top.update(w, h);
    const cam = this.currentCamera(now);

    // Amount of drawn pitch vs. real video (video sources fade when going tactical).
    const a = ease(Math.min(1, (now - this.viewStart) / VIEW_ANIM_MS));
    const showsVideo = (v: View) => (this.video && v === "main" ? 1 : 0);
    const drawn = 1 - (showsVideo(this.viewFrom) + (showsVideo(this.view) - showsVideo(this.viewFrom)) * a);
    if (this.video) {
      this.video.style.display = drawn < 1 ? "block" : "none";
      this.video.style.opacity = String(1 - drawn);
    }

    ctx.clearRect(0, 0, w, h);
    if (drawn > 0) {
      ctx.globalAlpha = drawn;
      drawBackdrop(ctx, w, h);
      drawPitch(ctx, cam, w, h);
      ctx.globalAlpha = 1;
    }

    // Overlays sit on the grass, under the players.
    if (this.toggles.offside) drawOffside(ctx, cam, match, s, now / 1000);
    if (this.toggles.shapeHome) drawFormation(ctx, cam, match, s, "home");
    if (this.toggles.shapeAway) drawFormation(ctx, cam, match, s, "away");
    this.drawings.draw(ctx, cam);
    for (const i of this.selected) {
      if (!s.visible[i]) continue;
      const p = match.players[i];
      drawTrail(ctx, cam, match.trail(i, this.t, 5), meta.teams[p.team].colors.primary);
      drawSelectionRing(ctx, cam, s.x[i], s.y[i], ACCENT, now / 1000);
    }
    if (this.toggles.distances && this.selected.length) drawDistances(ctx, cam, match, s, this.selected);

    if (drawn > 0) {
      ctx.globalAlpha = drawn;
      drawPeople(ctx, cam, match, s);
      ctx.globalAlpha = 1;
    }
    const placed: Rect[] = [];
    for (const i of this.selected) if (s.visible[i]) drawPlayerCard(ctx, cam, match, match.players[i], s, placed);

    this.renderMinimap(s);
  }

  private renderMinimap(s: ReturnType<Match["sample"]>) {
    const c = this.mctx;
    const mw = this.mini.clientWidth;
    const mh = this.mini.clientHeight;
    if (!mw) return;
    const pad = 8;
    const k = Math.min((mw - 2 * pad) / L, (mh - 2 * pad) / W);
    const ox = (mw - L * k) / 2;
    const oy = (mh - W * k) / 2;
    const P = (x: number, y: number): Pt => [ox + x * k, oy + y * k];
    c.clearRect(0, 0, mw, mh);
    c.fillStyle = "#1f6b32";
    c.fillRect(ox, oy, L * k, W * k);
    c.strokeStyle = "rgba(255,255,255,0.55)";
    c.lineWidth = 1;
    for (const line of MARKINGS) {
      c.beginPath();
      line.forEach(([x, y], i) => (i ? c.lineTo(...P(x, y)) : c.moveTo(...P(x, y))));
      c.stroke();
    }
    // Area the main camera sees.
    if (this.view !== "top") {
      const cam = this.view === "recon" ? this.recon : this.mainCamera();
      const border: Pt[] = [];
      const n = 12;
      for (let i = 0; i <= n; i++) border.push([(this.w * i) / n, 0]);
      for (let i = 0; i <= n; i++) border.push([this.w, (this.h * i) / n]);
      for (let i = n; i >= 0; i--) border.push([(this.w * i) / n, this.h]);
      for (let i = n; i >= 0; i--) border.push([0, (this.h * i) / n]);
      const poly = border
        .map(([x, y]) => cam.unproject(x, y))
        .filter((g): g is [number, number] => g !== null)
        .map(([x, y]) => P(Math.min(Math.max(x, -4), L + 4), Math.min(Math.max(y, -4), W + 4)));
      if (poly.length > 2) {
        c.fillStyle = "rgba(255,255,255,0.12)";
        c.strokeStyle = "rgba(255,255,255,0.6)";
        c.beginPath();
        poly.forEach((p, i) => (i ? c.lineTo(...p) : c.moveTo(...p)));
        c.closePath();
        c.fill();
        c.stroke();
      }
    }
    for (const p of this.match.players) {
      if (!s.visible[p.index]) continue;
      const [x, y] = P(s.x[p.index], s.y[p.index]);
      const col = this.match.meta.teams[p.team].colors;
      c.fillStyle = p.isGK ? col.goalkeeper : col.primary;
      c.beginPath();
      c.arc(x, y, 3.2, 0, 2 * Math.PI);
      c.fill();
      if (this.selected.includes(p.index)) {
        c.strokeStyle = ACCENT;
        c.lineWidth = 2;
        c.beginPath();
        c.arc(x, y, 6, 0, 2 * Math.PI);
        c.stroke();
      }
    }
    this.match.officials.forEach((_, i) => {
      if (!s.officials.visible[i]) return;
      const [x, y] = P(s.officials.x[i], s.officials.y[i]);
      c.fillStyle = "#15171c";
      c.strokeStyle = "#FFD23F";
      c.lineWidth = 1;
      c.beginPath();
      c.arc(x, y, 2.6, 0, 2 * Math.PI);
      c.fill();
      c.stroke();
    });
    if (s.ball.visible) {
      const [x, y] = P(s.ball.x, s.ball.y);
      c.fillStyle = "#fff";
      c.strokeStyle = hexAlpha("#000000", 0.6);
      c.beginPath();
      c.arc(x, y, 2.6, 0, 2 * Math.PI);
      c.fill();
      c.stroke();
    }
  }
}

async function main() {
  const params = new URLSearchParams(location.search);
  const available: Dataset[] = [];
  for (const ds of DATASETS) if (ds.key === "demo" || (await datasetAvailable(ds))) available.push(ds);
  // Locally the reconstructed sample match opens first; the public build only has the synthetic demo.
  // The synthetic match is the demo; the real-match reconstruction stays opt-in (local only).
  const ds = available.find((d) => d.key === params.get("data")) ?? available[0];

  const select = $<HTMLSelectElement>("#dataset");
  for (const d of available) select.add(new Option(d.label, d.key));
  select.value = ds.key;
  select.hidden = available.length < 2;
  select.onchange = () => {
    params.set("data", select.value);
    location.search = params.toString();
  };

  try {
    const match = await loadMatch(ds, (f) => ($("#loadBar").style.width = `${f * 100}%`));
    new App(match, ds);
    $("#loading").classList.add("done");
  } catch (err) {
    $("#loadText").textContent = `Could not load the match: ${(err as Error).message}`;
  }
}

void main();

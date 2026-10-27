// Live insight feed: short on-screen cards triggered while the match plays.
// Everything is computed from the match data (no model), so it is instant and free;
// key moments offer a button that asks the AI analyst for the full explanation.

import type { Spell } from "./analysis";
import type { Match, MatchEvent, TeamKey } from "./data";

export const SPEED_ALERT_KMH = 30;
const SPEED_COOLDOWN_S = 120;
const LONG_THROUGH_BALL_M = 25;

export interface FeedItem {
  t: number;
  kind: "goal" | "save" | "offside" | "speed" | "distance" | "pass" | "momentum";
  title: string;
  text: string;
  color: string;
  /** Players involved (ids), for the player focus filter. */
  players: string[];
  /** Key moment the AI analyst can explain. */
  explainable: boolean;
}

const clock = (t: number) => {
  const s = Math.max(0, Math.floor(t));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

/** 1 (simple) to 5 (very hard): longer, through and lofted passes are harder to complete. */
export function passDifficulty(e: MatchEvent): number {
  const len = Math.hypot((e.end_x as number) - e.x, (e.end_y as number) - e.y);
  const score = 1 + len / 15 + (e.through_ball ? 1 : 0) + (e.lofted ? 0.5 : 0);
  return Math.max(1, Math.min(5, Math.round(score)));
}

export function buildFeed(match: Match, spells: Spell[]): FeedItem[] {
  const out: FeedItem[] = [];
  const teams = match.meta.teams;
  const name = (id: unknown) => match.players.find((p) => p.id === id)?.name ?? "";
  const color = (k: TeamKey | null) => (k ? teams[k].colors.primary : "#ffffff");
  const shots = new Map(match.events.filter((e) => e.type === "shot").map((e) => [e.t, e]));

  for (const e of match.events) {
    if (e.type === "goal") {
      const shot = [...shots.values()].find((s) => s.outcome === "goal" && Math.abs(s.t - e.t) < 3);
      const score = e.score as { home: number; away: number };
      const xg = shot && typeof shot.xg === "number" ? ` · xG ${shot.xg.toFixed(2)}` : "";
      out.push({
        t: e.t, kind: "goal", color: color(e.team), explainable: true,
        title: `Goal · ${teams[e.team as TeamKey].short} ${score.home}-${score.away}`,
        text: `${name(e.scorer)}${e.assist ? `, assist ${name(e.assist)}` : ""}${xg}`,
        players: [e.scorer as string, e.assist as string].filter(Boolean),
      });
    } else if (e.type === "save") {
      out.push({
        t: e.t, kind: "save", color: color(e.team), explainable: true,
        title: "Save", text: `${name(e.player)} denies ${name(e.shooter)}`,
        players: [e.player as string, e.shooter as string],
      });
    } else if (e.type === "offside") {
      out.push({
        t: e.t, kind: "offside", color: "#FF4FD8", explainable: true,
        title: "Offside", text: `${name(e.player)} caught beyond the line`,
        players: [e.player as string, e.passer as string].filter(Boolean),
      });
    } else if (e.type === "pass" && e.through_ball && e.outcome === "complete") {
      const len = Math.hypot((e.end_x as number) - e.x, (e.end_y as number) - e.y);
      if (len < LONG_THROUGH_BALL_M) continue;
      out.push({
        t: e.t, kind: "pass", color: color(e.team), explainable: false,
        title: `Through ball · difficulty ${passDifficulty(e)}/5`,
        text: `${name(e.player)} finds ${name(e.received_by)} over ${len.toFixed(0)} m`,
        players: [e.player as string, e.received_by as string].filter(Boolean),
      });
    }
  }

  // Threshold alerts: sprint speed (with a per-player cooldown) and distance milestones.
  const lastAlert = new Map<number, number>();
  let nextKm = 1;
  const step = 0.2;
  for (let t = 0; t <= match.duration; t += step) {
    const s = match.sample(t);
    let leader = -1;
    for (const p of match.players) {
      if (!s.visible[p.index]) continue;
      const kmh = s.speed[p.index] * 3.6;
      if (kmh >= SPEED_ALERT_KMH && t - (lastAlert.get(p.index) ?? -Infinity) > SPEED_COOLDOWN_S) {
        lastAlert.set(p.index, t);
        out.push({
          t, kind: "speed", color: color(p.team), explainable: false,
          title: `Sprint · ${kmh.toFixed(1)} km/h`, text: `${p.name} (${teams[p.team].short})`, players: [p.id],
        });
      }
      if (leader < 0 || s.dist[p.index] > s.dist[leader]) leader = p.index;
    }
    if (leader >= 0 && s.dist[leader] >= nextKm * 1000) {
      const p = match.players[leader];
      out.push({
        t, kind: "distance", color: color(p.team), explainable: false,
        title: `First to ${nextKm} km`, text: `${p.name} (${teams[p.team].short}) leads the running`, players: [p.id],
      });
      nextKm++;
    }
  }

  // Momentum swings: a team takes clear control after a spell without it.
  let prev = 0;
  for (const sp of spells) {
    const diff = sp.home - sp.away;
    const side: TeamKey | null = diff >= 25 ? "home" : diff <= -25 ? "away" : null;
    const before: TeamKey | null = prev >= 25 ? "home" : prev <= -25 ? "away" : null;
    if (side && side !== before) {
      out.push({
        t: sp.t1, kind: "momentum", color: color(side), explainable: false,
        title: `${teams[side].short} take control`,
        text: `Control index ${Math.round(side === "home" ? sp.home : sp.away)} from ${clock(sp.t0)} to ${clock(sp.t1)}`,
        players: [],
      });
    }
    prev = diff;
  }
  return out.sort((a, b) => a.t - b.t);
}

"""Synthetic match engine.

Players are steered toward formation targets that shift with the ball, while a
small possession state machine (carry -> pass / shot -> claim) drives the ball
and writes the event log. All coordinates are pitch metres: x along the length
(0..105, the home team attacks +x), y across the width (0..68).

The aim is broadcast-plausible movement for a telestration demo, not a
physically accurate football model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .pitch import GOAL_AREA_DEPTH, PITCH_LENGTH as L, PITCH_WIDTH as W
from .teams import TeamSpec

SIM_HZ = 50
DT = 1.0 / SIM_HZ
ACCEL = 5.5  # m/s^2, max change of a player's velocity
CONTROL_RADIUS = 1.1  # m, how close a player must be to take a loose ball
TEAM_KEYS = ("home", "away")


def _norm(v) -> float:
    return math.hypot(v[0], v[1])


def _unit(v) -> np.ndarray:
    n = _norm(v)
    return v / n if n > 1e-9 else np.zeros(2)


def _seg_dist(p, a, b) -> tuple[float, float]:
    """Distance from p to segment ab, and the projection parameter s in [0, 1]."""
    ab = b - a
    denom = float(ab @ ab)
    s = 0.0 if denom < 1e-9 else float(np.clip((p - a) @ ab / denom, 0.0, 1.0))
    return _norm(p - (a + s * ab)), s


def _clip_to_pitch(p, margin=0.5) -> np.ndarray:
    return np.array([np.clip(p[0], margin, L - margin), np.clip(p[1], margin, W - margin)])


@dataclass
class Flight:
    kind: str  # "pass" | "shot"
    start: np.ndarray
    end: np.ndarray
    t0: float
    duration: float
    height: float  # apex of the arc above the straight line, m
    end_z: float = 0.0
    team: int = 0
    claimant: int = -1  # player who takes the ball at the end, -1 = loose
    outcome: str = ""
    event: dict | None = None


@dataclass
class Restart:
    kind: str  # "kickoff" | "goal_kick" | "throw_in" | "corner"
    team: int
    spot: np.ndarray
    t_start: float
    t_end: float
    taker: int = -1


class MatchSim:
    def __init__(self, home: TeamSpec, away: TeamSpec, seed: int = 7,
                 duration: float = 600.0, out_hz: int = 10):
        if SIM_HZ % out_hz:
            raise ValueError(f"out_hz must divide {SIM_HZ}")
        self.teams = (home, away)
        self.rng = np.random.default_rng(seed)
        self.duration = duration
        self.out_hz = out_hz
        self.stride = SIM_HZ // out_hz

        slots = [s for team in self.teams for s in team.slots]
        self.n = len(slots)
        self.team_of = np.repeat([0, 1], 11)
        self.depth = np.array([s.depth for s in slots])
        self.lane = np.array([s.lane for s in slots])
        self.role = [s.role for s in slots]
        self.is_gk = np.array([s.role == "GK" for s in slots])
        self.fullback = np.array([s.fullback for s in slots], dtype=float)
        # Wide midfielders tuck inside when their fullback overlaps.
        self.tuck = np.array([0.0 if s.role != "MF" else
                              0.12 if s.lane < 0.2 else -0.12 if s.lane > 0.8 else 0.0
                              for s in slots])
        # How far behind the offside line each role holds when attacking (team-frame units).
        self.line_gap = np.array([{"FW": 0.004, "MF": 0.07, "DF": 0.16}.get(s.role, 0.0)
                                  for s in slots])
        self.ids = [team.player_id(i) for team in self.teams for i in range(11)]
        self.players = [p for team in self.teams for p in team.players]
        self.positions = [s.code for s in slots]
        self.gk_index = (0, 11)

        rng = self.rng
        self.vmax = np.where(self.is_gk, 6.8, rng.uniform(7.6, 9.3, self.n))
        # Slow per-player wobble so the shape never looks rigid (team-frame units).
        self.noise_amp = rng.uniform(0.006, 0.015, (self.n, 2))
        self.noise_freq = rng.uniform(0.03, 0.09, (self.n, 2)) * 2 * math.pi
        self.noise_phase = rng.uniform(0, 2 * math.pi, (self.n, 2))

        self.t = 0.0
        self.P = np.zeros((self.n, 2))
        self.V = np.zeros((self.n, 2))
        self.dist = np.zeros(self.n)
        self.tackle_ready = np.zeros(self.n)  # time from which a player may tackle again

        self.ball = np.array([L / 2, W / 2])
        self.ball_z = 0.0
        self.ball_v = np.zeros(2)
        self._ball_offset = np.zeros(2)
        self.owner = -1
        self.poss: int | None = None
        self.last_touch = 0
        self.flight: Flight | None = None
        self.restart: Restart | None = None
        self.loose_since = 0.0
        self.shape_ref = np.array([L / 2, W / 2])  # low-passed ball reference for team shape
        self.poss_w = np.array([0.5, 0.5])  # low-passed "in possession" weight per team

        self.hold_until = 0.0
        self.protect_until = 0.0
        self.carry_speed = 5.0
        self.carry_bias = 0.0
        self.pending_pass: dict | None = None
        self.last_pass: dict | None = None

        self.events: list[dict] = []
        self.frames: list[dict] = []
        self.score = [0, 0]

        self._start_restart("kickoff", 0, (L / 2, W / 2), delay=2.0)
        self.P = self._shape_targets()

    # ----------------------------------------------------------------- frames

    @staticmethod
    def _to_team(k: int, xy):
        xy = np.asarray(xy, float)
        u, v = xy[..., 0] / L, xy[..., 1] / W
        return (u, v) if k == 0 else (1 - u, 1 - v)

    @staticmethod
    def _to_field(k: int, u, v) -> np.ndarray:
        if k == 1:
            u, v = 1 - u, 1 - v
        return np.stack([np.asarray(u) * L, np.asarray(v) * W], -1)

    @staticmethod
    def _attack_goal(k: int) -> np.ndarray:
        return np.array([L if k == 0 else 0.0, W / 2])

    def _team_idx(self, k: int) -> range:
        return range(11 * k, 11 * k + 11)

    def _offside_u(self, k: int) -> float:
        """Offside line for attacking team k, in k's frame (0 = own goal line)."""
        opp_u, _ = self._to_team(k, self.P[self.team_of != k])
        second_last = np.sort(opp_u)[-2]
        ball_u, _ = self._to_team(k, self.ball)
        return float(max(second_last, ball_u, 0.5))

    # ---------------------------------------------------------------- targets

    def _ball_ref(self) -> np.ndarray:
        if self.flight is not None:
            return self.flight.end
        if self.restart is not None:
            return self.restart.spot
        return self.ball

    def _shape_targets(self) -> np.ndarray:
        T = np.empty((self.n, 2))
        ref = self.shape_ref
        kickoff = self.restart is not None and self.restart.kind == "kickoff"
        for k in (0, 1):
            sl = slice(11 * k, 11 * k + 11)
            bu, bv = (float(c) for c in self._to_team(k, ref))
            w = self.poss_w[k]
            if kickoff:
                line, span, width, shift, fb, w = 0.10, 0.33, 0.85, 0.0, 0.0, 0.0
            else:
                # Blend the attacking and defending shapes so transitions are gradual.
                attack = np.array([np.clip(0.08 + 0.48 * bu, 0.12, 0.56), 0.44, 1.0, 0.12, 0.16])
                defend = np.array([np.clip(0.02 + 0.40 * bu, 0.05, 0.42), 0.30, 0.62, 0.30, 0.0])
                line, span, width, shift, fb = w * attack + (1 - w) * defend
            noise = self.noise_amp[sl] * np.sin(self.noise_freq[sl] * self.t + self.noise_phase[sl])
            u = line + self.depth[sl] * span + fb * self.fullback[sl] + noise[:, 0]
            lane = self.lane[sl] + self.tuck[sl] * w
            v = 0.5 + (lane - 0.5) * width + (bv - 0.5) * shift + noise[:, 1]
            if kickoff:
                u = np.minimum(u, 0.47)
            elif self.poss == k:
                u = np.minimum(u, self._offside_u(k) - self.line_gap[sl])
            u[0] = 0.012 + 0.09 * np.clip(bu, 0, 1)
            v[0] = 0.5 + (bv - 0.5) * 0.3
            T[sl] = self._to_field(k, np.clip(u, 0.01, 0.985), np.clip(v, 0.03, 0.97))

        # Teammates drifting into each other spread out.
        for k in (0, 1):
            sl = slice(11 * k, 11 * k + 11)
            diff = self.P[sl, None, :] - self.P[None, sl, :]
            d = np.linalg.norm(diff, axis=-1) + np.eye(11) * 1e3
            push = np.clip(3.0 - d, 0, None) / np.maximum(d, 0.1)
            T[sl] += (diff * push[..., None]).sum(axis=1) * 0.6
        return T

    def _nearest(self, idx, point, exclude_gk=True) -> list[int]:
        cand = [i for i in idx if not (exclude_gk and self.is_gk[i])]
        return sorted(cand, key=lambda i: _norm(self.P[i] - point))

    def _targets(self) -> tuple[np.ndarray, np.ndarray]:
        T = self._shape_targets()
        gap = np.linalg.norm(T - self.P, axis=1)
        # Walk / jog / run / sprint depending on how far out of position a player is.
        vcap = np.select([gap > 18, gap > 10, gap > 4], [self.vmax * 0.85, 4.5, 3.0], 1.6)
        shape_vcap = vcap.copy()

        if self.restart is not None:
            r = self.restart
            if r.taker >= 0:
                back = _unit(self._attack_goal(r.team) - r.spot)
                T[r.taker] = r.spot - back * 0.5
                vcap[r.taker] = self.vmax[r.taker] * 0.8
        elif self.owner >= 0:
            o = self.owner
            T[o] = self._carry_target()
            vcap[o] = self.carry_speed
            k = 1 - self.team_of[o]
            near = self._nearest(self._team_idx(k), self.ball)
            own_goal = self._attack_goal(1 - k)
            T[near[0]] = self.ball
            vcap[near[0]] = self.vmax[near[0]] * 0.7
            T[near[1]] = self.ball + _unit(own_goal - self.ball) * 7.0
            vcap[near[1]] = self.vmax[near[1]] * 0.55
        elif self.flight is not None:
            f = self.flight
            if f.claimant >= 0:
                T[f.claimant] = f.end
                vcap[f.claimant] = self.vmax[f.claimant]
            if f.kind == "pass":
                for k in (0, 1):
                    if f.claimant >= 0 and self.team_of[f.claimant] == k:
                        continue
                    c = self._nearest(self._team_idx(k), f.end)[0]
                    T[c] = f.end
                    vcap[c] = self.vmax[c] * 0.9
        else:
            for k in (0, 1):
                c = self._nearest(self._team_idx(k), self.ball, exclude_gk=False)[0]
                T[c] = self.ball + self.ball_v * 0.3
                vcap[c] = self.vmax[c]
        urgent = vcap != shape_vcap  # players going for the ball
        return T, vcap, urgent

    def _carry_target(self) -> np.ndarray:
        o = self.owner
        k = self.team_of[o]
        u, v = (float(c) for c in self._to_team(k, self.P[o]))
        if u > 0.78:
            goal = self._attack_goal(k)
            aim = goal + _unit(self.P[o] - goal) * 11.0  # drive toward the penalty spot
        else:
            aim = self._to_field(k, u + 0.12, v + self.carry_bias * 0.08 + (0.5 - v) * 0.1)
        opp = list(self._team_idx(1 - k))
        d = np.linalg.norm(self.P[opp] - self.P[o], axis=1)
        q = opp[int(np.argmin(d))]
        if d.min() < 5:
            aim = aim + _unit(self.P[o] - self.P[q]) * (5 - d.min()) * 1.2
        return _clip_to_pitch(aim, margin=1.5)

    # --------------------------------------------------------------- dynamics

    def _move(self, T: np.ndarray, vcap: np.ndarray, urgent: np.ndarray) -> None:
        delta = T - self.P
        d = np.linalg.norm(delta, axis=1)
        # Off-ball players have a small dead zone so they stand still between shifts;
        # players going for the ball attack it directly.
        speed = np.minimum(vcap, np.where(urgent, 2.0 * d, 0.7 * np.maximum(d - 0.8, 0.0)))
        desired = delta * (speed / np.maximum(d, 1e-6))[:, None]
        dv = desired - self.V
        m = np.linalg.norm(dv, axis=1)
        self.V += dv * np.minimum(1.0, ACCEL * DT / np.maximum(m, 1e-9))[:, None]
        self.P += self.V * DT
        self.dist += np.linalg.norm(self.V, axis=1) * DT

    def _update_ball(self) -> None:
        if self.owner >= 0:
            o = self.owner
            s = _norm(self.V[o])
            if s > 0.3:
                self._ball_offset = self.V[o] / s * 0.55
            self.ball = self.P[o] + self._ball_offset
            self.ball_z = 0.0
            self.ball_v = self.V[o].copy()
        elif self.flight is not None:
            f = self.flight
            s = min(1.0, (self.t - f.t0) / f.duration)
            se = s * (1.2 - 0.2 * s)  # ground passes slow down a little
            prev = self.ball
            self.ball = f.start + (f.end - f.start) * se
            self.ball_z = f.end_z * se + 4 * f.height * se * (1 - se)
            self.ball_v = (self.ball - prev) / DT
            if s >= 1.0:
                self._land()
        elif self.restart is not None:
            r = self.restart
            # Leave the ball where it went dead for a moment before re-spotting it.
            if self.t > r.t_start + (2.5 if r.kind == "kickoff" else 1.2):
                self.ball = r.spot.copy()
            self.ball_z = 0.0
            self.ball_v = np.zeros(2)
        else:
            self.ball = self.ball + self.ball_v * DT
            sp = _norm(self.ball_v)
            if sp > 1e-6:
                self.ball_v *= max(0.0, sp - 3.0 * DT) / sp
            self.ball_z = max(0.0, self.ball_z - 4.0 * DT)
            x, y = self.ball
            if not (0 <= x <= L and 0 <= y <= W):
                self._ball_out()
                return
            if self.t - self.loose_since > 0.15:
                d = np.linalg.norm(self.P - self.ball, axis=1)
                i = int(np.argmin(d))
                if d[i] < CONTROL_RADIUS:
                    self._claim(i)

    # ------------------------------------------------------------- decisions

    def _tick(self) -> None:
        if self.restart is not None and self.t >= self.restart.t_end:
            self._take_restart()
        elif self.owner >= 0:
            self._tackles()
            if self.owner >= 0:
                o = self.owner
                opp = list(self._team_idx(1 - self.team_of[o]))
                pressure = np.linalg.norm(self.P[opp] - self.P[o], axis=1).min()
                near_goal = _norm(self._attack_goal(self.team_of[o]) - self.P[o]) < 14
                if (self.t >= self.hold_until or (pressure < 2.2 and self.rng.random() < 2.0 * DT)
                        or (near_goal and self.rng.random() < 3.0 * DT)):
                    self._decide()
        # Team blocks react to where the ball is going, but not instantly.
        self.shape_ref += (self._ball_ref() - self.shape_ref) * min(1.0, DT / 1.5)
        in_poss = np.array([self.poss == 0, self.poss == 1], dtype=float)
        self.poss_w += (in_poss - self.poss_w) * min(1.0, DT / 2.5)
        self._move(*self._targets())
        self._update_ball()

    def _tackles(self) -> None:
        o = self.owner
        if self.t < self.protect_until:
            return
        for q in self._team_idx(1 - self.team_of[o]):
            if _norm(self.P[q] - self.P[o]) > 1.6 or self.tackle_ready[q] > self.t:
                continue
            if self.rng.random() >= 1.3 * DT:
                continue
            won = self.rng.random() < 0.45
            self._event("tackle", q, self.P[q], opponent=self.ids[o],
                        outcome="won" if won else "lost")
            if won:
                self.tackle_ready[o] = self.t + 1.0
                self._claim(q)
                return
            self.tackle_ready[q] = self.t + 1.6

    def _decide(self) -> None:
        o = self.owner
        k = self.team_of[o]
        dg = _norm(self._attack_goal(k) - self.P[o])
        if not self.is_gk[o]:
            p_shot = 0.45 if dg < 17 else 0.2 if dg < 24 else 0.03 if dg < 32 else 0.0
            if self.rng.random() < p_shot:
                self._shoot()
                return
        options = self._pass_options(o)
        if not options:
            self.hold_until = self.t + 0.4
            return
        scores = np.array([opt[0] for opt in options])
        probs = np.exp((scores - scores.max()) / 0.5)
        probs /= probs.sum()
        self._launch_pass(o, *options[self.rng.choice(len(options), p=probs)][1:])

    def _pass_options(self, o: int) -> list[tuple]:
        k = self.team_of[o]
        off_u = self._offside_u(k)
        opp = list(self._team_idx(1 - k))
        cu, _ = self._to_team(k, self.P[o])
        max_d = 60.0 if self.is_gk[o] else 45.0
        options = []
        for j in self._team_idx(k):
            if j == o:
                continue
            uj, vj = (float(c) for c in self._to_team(k, self.P[j]))
            points = [(self.P[j] + self.V[j] * 0.7, False)]
            if self.role[j] in ("FW", "MF") and uj > 0.45 and uj > off_u - 0.07:
                through = self._to_field(k, min(off_u + 0.07, 0.94), vj)
                points.append((through, True))
            for pt, through in points:
                d = _norm(pt - self.P[o])
                if d < 6 or d > max_d:
                    continue
                if not through and uj > off_u + 0.003:
                    continue  # receiver is offside
                lane = min(_seg_dist(self.P[q], self.P[o], pt)[0] for q in opp)
                pu, _ = self._to_team(k, pt)
                score = (0.07 * (pu - cu) * L + 0.35 * min(lane, 5.0)
                         - 0.03 * max(d - 25, 0) + (0.6 if through else 0.0)
                         - (1.0 if self.is_gk[j] else 0.0) - (1.5 if lane < 1.0 else 0.0))
                options.append((score, j, pt, through, lane, d))
        return options

    def _launch_pass(self, o, j, pt, through, lane, d) -> None:
        rng = self.rng
        k = self.team_of[o]
        start = self.ball.copy()
        end = _clip_to_pitch(pt)
        lofted = d > 30 or (lane < 2.0 and d > 16 and rng.random() < 0.6)
        if lofted:
            speed, height = rng.uniform(15, 20), 1.5 + 0.09 * d
        else:
            speed, height = float(np.clip(7 + 0.4 * d, 10, 21)), 0.0
        duration = _norm(end - start) / speed
        claimant = j

        if rng.random() < min(0.02 + 0.003 * d, 0.2):
            end = _clip_to_pitch(end + rng.normal(0, 4.5, 2))  # misplaced
            claimant = -1
        else:
            best = None
            for q in self._team_idx(1 - k):
                dq, s = _seg_dist(self.P[q], start, end)
                if s < 0.12 or (lofted and s < 0.85):
                    continue
                margin = dq / 6.5 + 0.4 - duration * s
                if margin < 0 and (best is None or margin < best[0]):
                    best = (margin, q, s)
            if best is not None and rng.random() < 0.4:
                _, q, s = best
                end = start + (end - start) * s
                duration *= s
                claimant = q

        ev = self._event("pass", o, start, end_x=round(float(end[0]), 2),
                         end_y=round(float(end[1]), 2), receiver=self.ids[j],
                         through_ball=bool(through), lofted=bool(lofted), outcome=None)
        self.pending_pass = ev
        self.flight = Flight("pass", start, end, self.t, max(duration, 0.1), height,
                             team=k, claimant=claimant, event=ev)
        self.owner = -1
        self.last_touch = k

    def _shoot(self) -> None:
        rng = self.rng
        o = self.owner
        k = self.team_of[o]
        sgn = 1.0 if k == 0 else -1.0
        gx = L if k == 0 else 0.0
        start = self.ball.copy()
        aim_y = W / 2 + rng.uniform(-3.2, 3.2)
        dg = _norm(np.array([gx, aim_y]) - start)
        xg = float(np.clip(0.62 * math.exp(-dg / 9.0), 0.02, 0.55))

        claimant, end_z, blocker = -1, 0.0, None
        for q in self._nearest(self._team_idx(1 - k), start):
            dq, s = _seg_dist(self.P[q], start, np.array([gx, aim_y]))
            if dq < 1.0 and 0.05 < s < 0.6:
                blocker = (q, s)
                break
        r = rng.random()
        if blocker is not None and rng.random() < 0.55:
            outcome = "blocked"
            end = start + (np.array([gx, aim_y]) - start) * blocker[1]
        elif r < xg:
            outcome = "goal"
            end = np.array([gx + sgn * 1.0, aim_y])
            end_z = rng.uniform(0.2, 2.1)
        elif r < xg + 0.38:
            outcome = "saved"
            gk = self.gk_index[1 - k]
            gy = self.P[gk][1]
            end = np.array([gx - sgn * 0.7, gy + np.clip(aim_y - gy, -2.2, 2.2)])
            end_z = rng.uniform(0.3, 1.8)
            claimant = gk
        else:
            outcome = "off_target"
            end = np.array([gx + sgn * 3.0, W / 2 + rng.choice([-1, 1]) * rng.uniform(4.6, 9.0)])
            end_z = rng.uniform(0.5, 4.0)

        assist = None
        lp = self.last_pass
        if lp is not None and lp["team"] == TEAM_KEYS[k] and self.t - lp["t"] < 8:
            assist = lp["player"]
        ev = self._event("shot", o, start, end_x=round(float(end[0]), 2),
                         end_y=round(float(end[1]), 2), xg=round(xg, 3),
                         outcome=outcome, assist=assist)
        speed = rng.uniform(22, 30)
        self.flight = Flight("shot", start, end, self.t, max(_norm(end - start) / speed, 0.1),
                             0.3, end_z=end_z, team=k, claimant=claimant, outcome=outcome, event=ev)
        self.owner = -1
        self.last_touch = k
        self.last_pass = None

    def _land(self) -> None:
        f = self.flight
        self.flight = None
        if f.kind == "shot":
            k = f.team
            if f.outcome == "goal":
                self.score[k] += 1
                self._event("goal", None, self.ball, team=TEAM_KEYS[k],
                            scorer=f.event["player"], assist=f.event["assist"],
                            score={"home": self.score[0], "away": self.score[1]})
                self._start_restart("kickoff", 1 - k, (L / 2, W / 2), delay=7.0)
            elif f.outcome == "saved":
                self._event("save", f.claimant, self.ball, shooter=f.event["player"])
                self._claim(f.claimant)
            elif f.outcome == "off_target":
                spot = self._to_field(1 - k, GOAL_AREA_DEPTH / L, 0.5)
                self._start_restart("goal_kick", 1 - k, spot, delay=4.0)
            else:
                self.last_touch = 1 - k
                ang = self.rng.uniform(0, 2 * math.pi)
                self.ball_v = np.array([math.cos(ang), math.sin(ang)]) * self.rng.uniform(4, 9)
                self.loose_since = self.t
            return
        c = f.claimant
        if c >= 0 and _norm(self.P[c] - self.ball) < 2.5:
            self._claim(c)
        else:
            self.ball_v = _unit(f.end - f.start) * self.rng.uniform(1.5, 3.5)
            self.loose_since = self.t

    def _claim(self, i: int) -> None:
        k = int(self.team_of[i])
        if self.pending_pass is not None:
            ev = self.pending_pass
            if ev["team"] == TEAM_KEYS[k]:
                ev["outcome"] = "complete"
                ev["received_by"] = self.ids[i]
                self.last_pass = ev
            else:
                ev["outcome"] = "intercepted"
                self._event("interception", i, self.P[i], passer=ev["player"])
            self.pending_pass = None
        if self.poss is not None and k != self.poss:
            self._event("possession_change", i, self.P[i])
            self.last_pass = None
        self.owner = i
        self.poss = k
        self.last_touch = k
        self.flight = None
        self.restart = None
        rng = self.rng
        hold = (1.5, 3.5) if self.is_gk[i] else (0.9, 3.0)
        self.hold_until = self.t + rng.uniform(*hold)
        self.protect_until = self.t + 0.6
        self.carry_speed = rng.uniform(3.0, 6.5)
        self.carry_bias = rng.uniform(-1, 1)

    # --------------------------------------------------------------- restarts

    def _start_restart(self, kind: str, team: int, spot, delay: float) -> None:
        spot = np.array(spot, float)
        if self.pending_pass is not None:
            self.pending_pass["outcome"] = "out_of_play"
            self.pending_pass = None
        if self.poss is not None and team != self.poss and kind != "kickoff":
            self._event("possession_change", None, spot, team=TEAM_KEYS[team])
        if kind == "kickoff":
            fw = [i for i in self._team_idx(team) if self.role[i] == "FW"]
            taker = min(fw, key=lambda i: abs(self.lane[i] - 0.5))
        elif kind == "goal_kick":
            taker = self.gk_index[team]
        else:
            taker = self._nearest(self._team_idx(team), spot)[0]
        self.restart = Restart(kind, team, spot, self.t, self.t + delay, taker)
        self.owner = -1
        self.flight = None
        self.poss = team
        self.last_pass = None

    def _take_restart(self) -> None:
        r = self.restart
        if _norm(self.P[r.taker] - r.spot) > 2.5:
            r.t_end = self.t + 0.5  # wait for the taker to get there
            return
        self._event(r.kind, r.taker, r.spot)
        self.ball = r.spot.copy()
        self._claim(r.taker)
        self.hold_until = self.t + self.rng.uniform(0.3, 1.0)

    def _ball_out(self) -> None:
        x, y = self.ball
        if 0 <= x <= L:
            spot = (float(np.clip(x, 0.5, L - 0.5)), 0.3 if y < 0 else W - 0.3)
            self._start_restart("throw_in", 1 - self.last_touch, spot, delay=3.0)
            return
        defending = 0 if x < 0 else 1  # home defends x = 0
        if self.last_touch == defending:
            spot = (0.5 if x < 0 else L - 0.5, 0.5 if y < W / 2 else W - 0.5)
            self._start_restart("corner", 1 - defending, spot, delay=5.0)
        else:
            spot = self._to_field(defending, GOAL_AREA_DEPTH / L, 0.5)
            self._start_restart("goal_kick", defending, spot, delay=4.0)

    # ----------------------------------------------------------------- output

    def _event(self, kind: str, player: int | None, pos, **extra) -> dict:
        ev = {
            "id": len(self.events),
            "type": kind,
            "t": round(self.t, 2),
            "frame": int(round(self.t * self.out_hz)),
            "team": TEAM_KEYS[self.team_of[player]] if player is not None else None,
            "player": self.ids[player] if player is not None else None,
            "x": round(float(pos[0]), 2),
            "y": round(float(pos[1]), 2),
        }
        ev.update(extra)
        self.events.append(ev)
        return ev

    def _record(self, index: int) -> None:
        speeds = np.linalg.norm(self.V, axis=1)
        players = []
        for i in range(self.n):
            k = self.team_of[i]
            players.append({
                "id": self.ids[i],
                "team": TEAM_KEYS[k],
                "number": self.players[i].number,
                "name": self.players[i].name,
                "x": round(float(self.P[i, 0]), 2),
                "y": round(float(self.P[i, 1]), 2),
                "speed": round(float(speeds[i]), 2),
                "dist": round(float(self.dist[i]), 1),
            })
        self.frames.append({
            "frame": index,
            "t": round(self.t, 2),
            "possession": TEAM_KEYS[self.poss] if self.poss is not None else None,
            "ball": {
                "x": round(float(self.ball[0]), 2),
                "y": round(float(self.ball[1]), 2),
                "z": round(float(self.ball_z), 2),
                "owner": self.ids[self.owner] if self.owner >= 0 else None,
            },
            "players": players,
        })

    def run(self) -> None:
        steps = int(round(self.duration * SIM_HZ))
        for step in range(steps + 1):
            self.t = step * DT
            if step % self.stride == 0:
                self._record(step // self.stride)
            self._tick()
        for ev in self.events:
            if ev["type"] == "pass" and ev["outcome"] is None:
                ev["outcome"] = "unresolved"

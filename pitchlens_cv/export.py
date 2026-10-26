"""Convert pixel tracks + per-frame camera calibration into the PitchLens data format.

    python -m pitchlens_cv.export --tracks match/out/tracks.jsonl \
        --homography match/out/homography.jsonl --out match/out/cv_demo

Foot points are mapped to pitch metres through the calibrated camera (including
lens distortion), smoothed per track, and given speed and cumulative distance.
Each frame also carries the camera (rotation, focal length, shared position and
lens) so the frontend can draw overlays on the original video. Output derived from
real footage stays local (match/ is git-ignored).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from sklearn.cluster import KMeans

from pitchlens_cv.calibrate import Lens, image_to_pitch
from pitchlens_cv.track import region_pixels
from pitchlens_synth.pitch import PITCH_LENGTH as L, PITCH_WIDTH as W

SMOOTH = 7  # frames in the centred moving average of positions
SPEED_SPAN = 3  # frames each side for the speed difference
MAX_SPEED = 11.0  # m/s; anything faster is tracking noise
MARGIN = 3.0  # m outside the lines still accepted (keepers, throw-ins)
MAX_JUMP = 2.5  # m between consecutive frames; more means the tracker swapped people


def lab_to_hex(lab: np.ndarray) -> str:
    """OpenCV 8-bit Lab -> '#RRGGBB', lifted a little so kits read well as flat graphics."""
    bgr = cv2.cvtColor(np.uint8([[np.clip(lab, 0, 255)]]), cv2.COLOR_LAB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * 1.15, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * 1.1, 0, 255)
    b, g, r = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)[0, 0]
    return f"#{r:02X}{g:02X}{b:02X}"


def kit_colours(video: Path, tracks: list[dict], step: int = 10) -> dict[str, dict[str, str]]:
    """Shirt / shorts colour per team and the goalkeeper shirt, measured on the footage."""
    samples = defaultdict(list)  # (team, part) -> Lab pixels
    rng = np.random.default_rng(0)
    cap = cv2.VideoCapture(str(video))
    for fr in tracks[::step]:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fr["frame"])
        ok, frame = cap.read()
        if not ok:
            continue
        for o in fr["objects"]:
            team = o.get("team")
            if not team or o["cls"] not in ("player", "goalkeeper"):
                continue
            box = np.array(o["bbox"])
            if o["cls"] == "goalkeeper":
                parts = (("goalkeeper", 0.15, 0.5),)
            else:
                parts = (("primary", 0.15, 0.5), ("secondary", 0.52, 0.7))
            for part, top, bottom in parts:
                px = region_pixels(frame, box, top, bottom, core=0.35)
                if px is not None:
                    samples[(team, part)].append(px[rng.choice(len(px), min(40, len(px)), replace=False)])
    cap.release()
    def dominant(chunks: list[np.ndarray]) -> np.ndarray:
        # The kit is the largest colour cluster; skin, hair and numbers are smaller ones.
        px = np.concatenate(chunks).astype(np.float32)
        km = KMeans(n_clusters=3, n_init=4, random_state=0).fit(px)
        return km.cluster_centers_[np.bincount(km.labels_).argmax()]

    out = {}
    for team in ("home", "away"):
        out[team] = {part: lab_to_hex(dominant(samples[(team, part)])) if len(samples[(team, part)]) >= 3 else fallback
                     for part, fallback in (("primary", "#888888"), ("secondary", "#FFFFFF"), ("goalkeeper", "#FFD23F"))}
    return out


def moving_average(x: np.ndarray, k: int) -> np.ndarray:
    k = min(k, len(x))
    k -= 1 - k % 2  # odd window keeps the output aligned with the input
    pad = k // 2
    xp = np.pad(x, ((pad, pad), (0, 0)), mode="edge")
    kernel = np.ones(k) / k
    return np.stack([np.convolve(xp[:, j], kernel, mode="valid") for j in range(x.shape[1])], 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tracks", type=Path, default=Path("match/out/tracks.jsonl"))
    ap.add_argument("--homography", type=Path, default=Path("match/out/homography.jsonl"))
    ap.add_argument("--camera", type=Path, default=Path("match/out/camera.json"))
    ap.add_argument("--video", type=Path, default=Path("match/sample_match.mp4"))
    ap.add_argument("--out", type=Path, default=Path("match/out/cv_demo"))
    args = ap.parse_args()

    tracks = [json.loads(l) for l in open(args.tracks, encoding="utf-8")]
    calib = [json.loads(l) for l in open(args.homography, encoding="utf-8")]
    cam = json.load(open(args.camera, encoding="utf-8"))
    lens = Lens(cam["width"], cam["height"], cam["k1"])
    centre = np.array(cam["centre_world"])
    cap = cv2.VideoCapture(str(args.video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    # Raw pitch positions per tracker id.
    raw = defaultdict(list)  # tracker id -> [(frame, x, y, team, role)]
    balls = {}
    for fr, rec in zip(tracks, calib):
        params = np.r_[rec["rvec"], np.log(rec["f"])]
        people = [o for o in fr["objects"] if o["cls"] in ("player", "goalkeeper") and o.get("team")]
        if people:
            pts = image_to_pitch(np.array([o["foot"] for o in people]), params, centre, lens)
            for o, (x, y) in zip(people, pts):
                if -MARGIN <= x <= L + MARGIN and -MARGIN <= y <= W + MARGIN:
                    role = "GK" if o["cls"] == "goalkeeper" else "player"
                    raw[o["id"]].append((fr["frame"], float(x), float(y), o["team"], role))
        if fr["ball"]:
            bx, by = image_to_pitch(np.array([fr["ball"]["center"]]), params, centre, lens)[0]
            if 0 <= bx <= L and 0 <= by <= W:
                balls[fr["frame"]] = (float(bx), float(by))

    # A tracker id can jump to another person (ID swap). Split it into segments
    # whenever the team changes or the position jumps; each segment is one player id.
    series = defaultdict(list)  # player id -> [(frame, x, y)]
    info = {}  # player id -> (team, role)
    for tid, rows in raw.items():
        seg = 0
        for k, (f, x, y, team, role) in enumerate(rows):
            if k:
                pf, px, py, pteam, _ = rows[k - 1]
                gap = f - pf
                if team != pteam or np.hypot(x - px, y - py) > MAX_JUMP * gap:
                    seg += 1
            pid = f"T{tid:03d}" if seg == 0 else f"T{tid:03d}.{seg}"
            series[pid].append((f, x, y))
            info[pid] = (team, role)

    # Smooth, then speed and cumulative distance per player.
    per_frame = defaultdict(list)
    for pid, s in series.items():
        arr = np.array(s)
        frames_idx, xy = arr[:, 0].astype(int), moving_average(arr[:, 1:], SMOOTH)
        lo = np.clip(np.arange(len(xy)) - SPEED_SPAN, 0, len(xy) - 1)
        hi = np.clip(np.arange(len(xy)) + SPEED_SPAN, 0, len(xy) - 1)
        dt = np.maximum(frames_idx[hi] - frames_idx[lo], 1) / fps
        speed = np.minimum(np.linalg.norm(xy[hi] - xy[lo], axis=1) / dt, MAX_SPEED)
        step = np.r_[0.0, np.linalg.norm(np.diff(xy, axis=0), axis=1)]
        step[step > MAX_SPEED * 2 / fps] = 0.0  # ignore jumps across tracking gaps
        dist = np.cumsum(step)
        team, _ = info[pid]
        for f, (x, y), v, d in zip(frames_idx, xy, speed, dist):
            per_frame[int(f)].append({
                "id": pid, "team": team, "number": None, "name": None,
                "x": round(float(x), 2), "y": round(float(y), 2),
                "speed": round(float(v), 2), "dist": round(float(d), 1),
            })

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "frames.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for rec in calib:
            i = rec["frame"]
            inv = np.linalg.inv(np.array(rec["H"]).reshape(3, 3))
            camera = {
                # Linear pitch -> image homography (ignores lens distortion), for simple consumers.
                "H": [round(float(v), 9) for v in (inv / inv[2, 2]).ravel()],
                # Full model in the right-handed world (x, -y, z): pixel = K * dist(R * (X - C)).
                "R": rec["R"],
                "C": [round(float(v), 4) for v in centre],
                "f": rec["f"],
                "cx": lens.cx,
                "cy": lens.cy,
                "k1": round(lens.k1, 6),
            }
            ball = balls.get(i)
            fh.write(json.dumps({
                "frame": i,
                "t": round(i / fps, 3),
                "possession": None,
                "ball": {"x": round(ball[0], 2), "y": round(ball[1], 2), "z": 0.0, "owner": None} if ball else None,
                "players": sorted(per_frame.get(i, []), key=lambda p: p["id"]),
                "camera": camera,
            }, separators=(",", ":")) + "\n")

    teams = {}
    kits = kit_colours(args.video, tracks)
    print(f"kit colours from the footage: {kits}")
    for key in ("home", "away"):
        teams[key] = {
            "name": key.capitalize(), "short": key[:3].upper(), "formation": None,
            "colors": kits[key],
            "attacks": None,
            "players": [{"id": pid, "number": None, "name": None,
                         "position": None, "role": "GK" if r == "GK" else None}
                        for pid, (tm, r) in sorted(info.items()) if tm == key],
        }
    meta = {
        "source": "cv",
        "generator": "pitchlens_cv",
        "pitch": {"length": L, "width": W},
        "fps": fps,
        "duration": round(len(calib) / fps, 3),
        "frame_count": len(calib),
        "video": {"file": args.video.name, "width": width, "height": height},
        "teams": teams,
    }
    with open(args.out / "meta.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=2)
    with open(args.out / "events.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump([], fh)

    n = [len(per_frame.get(r["frame"], [])) for r in calib]
    speeds = [p["speed"] for ps in per_frame.values() for p in ps]
    print(f"frames {len(calib)}, players/frame mean {np.mean(n):.1f}, ball in {100 * len(balls) / len(calib):.0f}%")
    print(f"speed m/s mean {np.mean(speeds):.2f}, p95 {np.percentile(speeds, 95):.2f}")
    print(f"written to {args.out}")


if __name__ == "__main__":
    main()

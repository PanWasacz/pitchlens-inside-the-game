"""Per-frame camera calibration from pitch keypoints.

    python -m pitchlens_cv.calibrate --video match/sample_match.mp4 \
        --weights model/roboflow/football-pitch-detection.pt --out match/out

A YOLOv8-pose model finds up to 32 pitch keypoints (layout of roboflow/sports
SoccerPitchConfiguration). A broadcast main camera stands still and only pans,
tilts, rolls and zooms, so instead of a free 8-DOF homography per frame we fit a
physical pinhole camera:

1. Per-frame RANSAC homographies (conf > 0.5, min 4 points) are decomposed to get
   a first guess of rotation, focal length and camera position.
2. The camera position and the lens radial distortion (k1) are shared by all
   frames and fitted jointly (robust bundle adjustment on a subset of frames).
3. Every frame then only fits rotation + focal length (4 DOF) to its keypoints,
   with a robust loss and an outlier-rejection pass.
4. Rotation and focal length are smoothed over time with a centred filter (the
   pipeline is offline, so smoothing adds no lag); frames without enough
   keypoints are interpolated.

Keypoints closer than 12 px to the image border are ignored: the model pins
off-screen keypoints to the edge with high confidence.

Held-out keypoint test on the sample clip (each keypoint predicted from the
others): median 6.1 px vs 6.4 px for free homographies, p90 13 px vs 26 px, and
24 px vs 112 px for keypoints far (> 25 m) from the rest. Refining frames against
detected white line pixels was tried and rejected: lines only constrain the
direction across them, so corners slid along the lines (keypoint error 5 -> 11 px).

Writes homography.jsonl (per frame: camera rotation / focal, plus the linear
homography for consumers that ignore distortion), camera.json (shared camera
position and lens) and calibration.mp4 with the projected pitch lines.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from scipy.spatial.transform import Rotation
from sports.configs.soccer import SoccerPitchConfiguration
from ultralytics import YOLO

# roboflow/sports keypoint layout, re-dimensioned to a real 105 x 68 m pitch (cm).
PITCH = SoccerPitchConfiguration(
    width=6800, length=10500, penalty_box_width=4032, penalty_box_length=1650,
    goal_box_width=1832, goal_box_length=550, centre_circle_radius=915,
    penalty_spot_distance=1100,
)
VERTICES_M = np.array(PITCH.vertices, dtype=np.float64) / 100.0  # (32, 2) metres
# Keypoints 11, 12, 21, 22 sit where the penalty arc meets the penalty-area line
# (measured on the sample clip within a few cm); the library places them at the
# goal-area width instead, which pulled every fit ~2 m off around the box.
_ARC_HALF = float(np.sqrt(9.15 ** 2 - (16.5 - 11.0) ** 2))  # 7.31 m
VERTICES_M[[10, 18], 1] = 34.0 - _ARC_HALF
VERTICES_M[[11, 19], 1] = 34.0 + _ARC_HALF

KP_CONF = 0.5
BORDER_PX = 12  # the model pins off-screen keypoints to the image edge; ignore those
MIN_POINTS = 4  # for the initial homographies
MIN_FIT_POINTS = 3  # for the 4-DOF per-frame camera fit
RANSAC_M = 1.0  # homography inlier threshold, metres
ROBUST_PX = 4.0  # soft-L1 scale of the camera fits, pixels
OUTLIER_PX = 15.0  # keypoints further than this from the fit are dropped and refitted
SMOOTH_SIGMA = 1.5  # frames, centred Gaussian on rotation and log-focal

# Pitch (x along, y towards the near side) is left-handed with z up; the camera
# maths uses the right-handed world (x, -y, z).
FLIP_Y = np.diag([1.0, -1.0, 1.0])


def to_world(p2: np.ndarray, z: np.ndarray | float = 0.0) -> np.ndarray:
    p2 = np.asarray(p2, np.float64).reshape(-1, 2)
    return np.c_[p2[:, 0], -p2[:, 1], np.broadcast_to(z, len(p2))]


class Lens:
    """Shared intrinsics: principal point at the image centre, one radial term."""

    def __init__(self, width: int, height: int, k1: float = 0.0):
        self.cx, self.cy, self.k1 = width / 2, height / 2, k1

    def K(self, f: float) -> np.ndarray:
        return np.array([[f, 0, self.cx], [0, f, self.cy], [0, 0, 1.0]])

    @property
    def dist(self) -> np.ndarray:
        return np.array([self.k1, 0, 0, 0], np.float64)


def project(params: np.ndarray, centre: np.ndarray, lens: Lens, world: np.ndarray) -> np.ndarray:
    """World points -> distorted image pixels. params = (rotation vector, log focal)."""
    R, _ = cv2.Rodrigues(params[:3])
    out, _ = cv2.projectPoints(world, params[:3], -R @ centre, lens.K(np.exp(params[3])), lens.dist)
    return out.reshape(-1, 2)


def visible(params: np.ndarray, centre: np.ndarray, lens: Lens, world: np.ndarray) -> np.ndarray:
    """Points in front of the camera and inside the range where the distortion is monotonic.

    Beyond r^2 = 1 / (3|k1|) the radial polynomial folds back, which would draw
    off-screen geometry into the picture.
    """
    R, _ = cv2.Rodrigues(params[:3])
    cam = (world - centre) @ R.T
    with np.errstate(divide="ignore", invalid="ignore"):
        r2 = (cam[:, 0] ** 2 + cam[:, 1] ** 2) / cam[:, 2] ** 2
    limit = 1 / (3 * abs(lens.k1)) if lens.k1 else np.inf
    return (cam[:, 2] > 0.5) & (r2 < 0.9 * limit)


def image_to_pitch(px: np.ndarray, params: np.ndarray, centre: np.ndarray, lens: Lens) -> np.ndarray:
    """Distorted image pixels -> points on the grass (pitch metres); NaN above the horizon."""
    f = np.exp(params[3])
    norm = cv2.undistortPoints(np.asarray(px, np.float64).reshape(-1, 1, 2), lens.K(f), lens.dist).reshape(-1, 2)
    R, _ = cv2.Rodrigues(params[:3])
    rays = np.c_[norm, np.ones(len(norm))] @ R  # R^T applied to each ray
    s = -centre[2] / rays[:, 2]
    ground = centre + rays * s[:, None]
    ground[s <= 0] = np.nan
    return np.c_[ground[:, 0], -ground[:, 1]]


def decompose(H: np.ndarray, lens: Lens) -> tuple[np.ndarray, np.ndarray] | None:
    """Rotation / log-focal and camera centre from an image -> pitch homography."""
    G = np.array([[1, 0, -lens.cx], [0, 1, -lens.cy], [0, 0, 1.0]]) @ np.linalg.inv(H) @ FLIP_Y
    h1, h2, h3 = G[:, 0], G[:, 1], G[:, 2]
    f2 = [-(h1[0] * h2[0] + h1[1] * h2[1]) / (h1[2] * h2[2]),
          (h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2) / (h2[2] ** 2 - h1[2] ** 2)]
    f2 = [v for v in f2 if np.isfinite(v) and v > 0]
    if not f2:
        return None
    f = float(np.sqrt(np.mean(f2)))
    Ki = np.diag([1 / f, 1 / f, 1.0])
    a, b, c = Ki @ h1, Ki @ h2, Ki @ h3
    s = (np.linalg.norm(a) + np.linalg.norm(b)) / 2
    r1, r2, t = a / s, b / s, c / s
    if t[2] < 0:  # the pitch must be in front of the camera
        r1, r2, t = -r1, -r2, -t
    U, _, Vt = np.linalg.svd(np.stack([r1, r2, np.cross(r1, r2)], 1))
    R = U @ Vt
    if np.linalg.det(R) < 0:
        return None
    return np.r_[cv2.Rodrigues(R)[0].ravel(), np.log(f)], -R.T @ t


def detect(video: Path, model: YOLO) -> list[tuple[np.ndarray, np.ndarray]]:
    out = []
    for i, frame in enumerate(sv.get_video_frames_generator(str(video))):
        r = model.predict(frame, verbose=False)[0]
        if r.keypoints is None or not len(r.keypoints.xy):
            out.append((np.zeros((32, 2)), np.zeros(32)))
        else:
            out.append((r.keypoints.xy[0].cpu().numpy().astype(np.float64), r.keypoints.conf[0].cpu().numpy()))
        if i % 100 == 0:
            print(f"keypoints: frame {i}")
    return out


def fit_shared(obs: list[dict], centre0: np.ndarray, lens: Lens) -> tuple[np.ndarray, float]:
    """Bundle adjustment of camera centre + k1 over a subset of well-observed frames."""
    sample = [o for o in obs if o["init"] is not None and len(o["idx"]) >= 6][::3]
    G = 4  # centre (3) + k1
    x0 = np.r_[centre0, lens.k1, np.concatenate([o["init"] for o in sample])]

    def residuals(x):
        trial = Lens(2 * lens.cx, 2 * lens.cy, x[3])
        return np.concatenate([
            (project(x[G + 4 * i: G + 4 * i + 4], x[:3], trial, to_world(VERTICES_M[o["idx"]])) - o["px"]).ravel()
            for i, o in enumerate(sample)
        ])

    rows = sum(2 * len(o["idx"]) for o in sample)
    S = lil_matrix((rows, len(x0)), dtype=int)
    r = 0
    for i, o in enumerate(sample):
        n = 2 * len(o["idx"])
        S[r:r + n, :G] = 1
        S[r:r + n, G + 4 * i: G + 4 * i + 4] = 1
        r += n
    sol = least_squares(residuals, x0, jac_sparsity=S, loss="soft_l1", f_scale=ROBUST_PX)
    return sol.x[:3], float(sol.x[3])


def fit_frame(init: np.ndarray, idx: np.ndarray, px: np.ndarray, centre: np.ndarray, lens: Lens):
    """Rotation + focal for one frame, with one outlier-rejection pass."""
    def solve(sel, x0):
        return least_squares(lambda p: (project(p, centre, lens, to_world(VERTICES_M[idx[sel]])) - px[sel]).ravel(),
                             x0, loss="soft_l1", f_scale=ROBUST_PX).x

    sel = np.ones(len(idx), bool)
    p = solve(sel, init)
    err = np.linalg.norm(project(p, centre, lens, to_world(VERTICES_M[idx])) - px, axis=1)
    if (err > OUTLIER_PX).any() and (err <= OUTLIER_PX).sum() >= MIN_FIT_POINTS:
        sel = err <= OUTLIER_PX
        p = solve(sel, p)
        err = np.linalg.norm(project(p, centre, lens, to_world(VERTICES_M[idx])) - px, axis=1)
    return p, sel, err


def smooth(params: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Centred smoothing of rotation (as aligned quaternions) and log-focal; fills gaps."""
    n = len(params)
    q = np.zeros((n, 4))
    q[valid] = Rotation.from_rotvec(params[valid, :3]).as_quat()
    for i in range(1, n):  # keep quaternion signs continuous
        if valid[i] and np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    series = np.c_[q, params[:, 3]]
    t = np.arange(n)
    for j in range(series.shape[1]):
        series[:, j] = np.interp(t, t[valid], series[valid, j])
    series = median_filter(series, size=(5, 1), mode="nearest")
    series = gaussian_filter1d(series, SMOOTH_SIGMA, axis=0, mode="nearest")
    rot = Rotation.from_quat(series[:, :4] / np.linalg.norm(series[:, :4], axis=1, keepdims=True))
    return np.c_[rot.as_rotvec(), series[:, 4]]


def linear_homography(params: np.ndarray, centre: np.ndarray, lens: Lens) -> np.ndarray:
    """Image -> pitch homography of the same camera without lens distortion."""
    R, _ = cv2.Rodrigues(params[:3])
    t = -R @ centre
    P = lens.K(np.exp(params[3])) @ np.c_[R[:, 0], R[:, 1], t] @ FLIP_Y  # pitch -> image
    Hi = np.linalg.inv(P)
    return Hi / Hi[2, 2]


def calibrate(video: Path, model: YOLO) -> tuple[list[dict], dict]:
    info = sv.VideoInfo.from_video_path(str(video))
    lens = Lens(info.width, info.height)
    kps = detect(video, model)

    obs = []
    for xy, conf in kps:
        inside = ((xy[:, 0] > BORDER_PX) & (xy[:, 0] < info.width - BORDER_PX)
                  & (xy[:, 1] > BORDER_PX) & (xy[:, 1] < info.height - BORDER_PX))
        idx = np.where((conf > KP_CONF) & inside)[0]
        o = {"idx": idx, "px": xy[idx], "init": None, "centre": None}
        if len(idx) >= MIN_POINTS:
            H, _ = cv2.findHomography(xy[idx], VERTICES_M[idx], cv2.RANSAC, RANSAC_M)
            d = decompose(H, lens) if H is not None else None
            if d is not None:
                o["init"], o["centre"] = d
        obs.append(o)

    centres = np.array([o["centre"] for o in obs if o["centre"] is not None])
    centre, lens.k1 = fit_shared(obs, np.median(centres, axis=0), lens)
    print(f"camera at pitch x={centre[0]:.1f} m, y={-centre[1]:.1f} m, height {centre[2]:.1f} m; lens k1={lens.k1:+.3f}")

    n = len(obs)
    params = np.zeros((n, 4))
    valid = np.zeros(n, bool)
    records = []
    prev = None
    for i, o in enumerate(obs):
        rec = {"frame": i, "points": int(len(o["idx"])), "inliers": 0, "error_px": None, "status": "interpolated"}
        init = prev if prev is not None else o["init"]
        if len(o["idx"]) >= MIN_FIT_POINTS and init is not None:
            p, sel, err = fit_frame(init, o["idx"], o["px"], centre, lens)
            if sel.sum() >= MIN_FIT_POINTS and np.median(err[sel]) < OUTLIER_PX:
                params[i], valid[i], prev = p, True, p
                rec.update(inliers=int(sel.sum()), status="fitted")
        records.append(rec)
    smoothed = smooth(params, valid)

    for i, (rec, o) in enumerate(zip(records, obs)):
        p = smoothed[i]
        if len(o["idx"]):
            err = np.linalg.norm(project(p, centre, lens, to_world(VERTICES_M[o["idx"]])) - o["px"], axis=1)
            rec["error_px"] = round(float(np.median(err)), 2)
        R, _ = cv2.Rodrigues(p[:3])
        rec["rvec"] = [round(float(v), 7) for v in p[:3]]
        rec["f"] = round(float(np.exp(p[3])), 3)
        rec["R"] = [round(float(v), 9) for v in R.ravel()]
        rec["H"] = [round(float(v), 9) for v in linear_homography(p, centre, lens).ravel()]
    camera = {"centre_world": centre.tolist(), "position_pitch": [centre[0], -centre[1], centre[2]],
              "k1": lens.k1, "cx": lens.cx, "cy": lens.cy, "width": info.width, "height": info.height}
    return records, camera


def pitch_lines() -> list[np.ndarray]:
    """Polylines of the pitch markings in metres, densified so lens distortion shows."""
    lines = [VERTICES_M[[a - 1, b - 1]] for a, b in PITCH.edges]
    c = np.array([PITCH.length / 200, PITCH.width / 200])
    ang = np.linspace(0, 2 * np.pi, 64)
    lines.append(c + PITCH.centre_circle_radius / 100 * np.stack([np.cos(ang), np.sin(ang)], 1))
    t = np.linspace(0, 1, 24)[:, None]
    return [np.concatenate([a + t * (b - a) for a, b in zip(l[:-1], l[1:])]) for l in lines]


def render(video: Path, records: list[dict], camera: dict, out_path: Path) -> None:
    info = sv.VideoInfo.from_video_path(str(video))
    lens = Lens(camera["width"], camera["height"], camera["k1"])
    centre = np.array(camera["centre_world"])
    lines = pitch_lines()
    with sv.VideoSink(str(out_path), info) as sink:
        for frame, rec in zip(sv.get_video_frames_generator(str(video)), records):
            p = np.r_[rec["rvec"], np.log(rec["f"])]
            color = (255, 0, 255) if rec["status"] == "fitted" else (0, 165, 255)
            for line in lines:
                world = to_world(line)
                img = project(p, centre, lens, world).astype(np.int32)
                ok = visible(p, centre, lens, world)
                # Draw only runs of consecutive valid points.
                for run in np.split(np.arange(len(line)), np.where(~ok)[0]):
                    run = run[ok[run]]
                    if len(run) > 1:
                        cv2.polylines(frame, [img[run]], False, color, 2, cv2.LINE_AA)
            label = f"{rec['status']}  kp={rec['inliers']}/{rec['points']}  err={rec['error_px']}px  f={rec['f']:.0f}"
            cv2.putText(frame, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
            sink.write_frame(frame)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", type=Path, default=Path("match/sample_match.mp4"))
    ap.add_argument("--weights", default="model/roboflow/football-pitch-detection.pt")
    ap.add_argument("--out", type=Path, default=Path("match/out"))
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    records, camera = calibrate(args.video, YOLO(args.weights))
    with open(args.out / "homography.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    with open(args.out / "camera.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(camera, fh, indent=2)
    render(args.video, records, camera, args.out / "calibration.mp4")

    fitted = sum(r["status"] == "fitted" for r in records)
    errors = [r["error_px"] for r in records if r["error_px"] is not None]
    print(f"frames {len(records)}: fitted {fitted}, interpolated {len(records) - fitted}")
    print(f"keypoint error after smoothing px: median {np.median(errors):.1f}, p95 {np.percentile(errors, 95):.1f}")
    print(f"written to {args.out}")


if __name__ == "__main__":
    main()

"""Detect and track players, goalkeepers, referees and the ball in a match video.

    python -m pitchlens_cv.track --video match/sample_match.mp4 --weights model/your.pt --out match/out

Pass 1 runs YOLOv8 + ByteTrack and samples shirt colours per track. Teams are then
split with K-Means on those colours (majority vote per track). Pass 2 renders an
annotated preview video. Output stays in pixel space; the homography step that maps
it to pitch metres (docs/schema.md) comes later.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
import torch
from sklearn.cluster import KMeans
from ultralytics import YOLO

TEAM_KEYS = ("home", "away")
COLORS = {
    "home": sv.Color.from_hex("#E63946"),
    "away": sv.Color.from_hex("#3FA7F5"),
    "goalkeeper": sv.Color.from_hex("#FFD23F"),
    "referee": sv.Color.from_hex("#202020"),
    "unknown": sv.Color.from_hex("#AAAAAA"),
}


def class_ids(model: YOLO) -> dict[str, int]:
    """Map our class names to the model's ids (custom football model or COCO)."""
    names = {v: k for k, v in model.names.items()}
    if "player" in names:
        return {k: names[k] for k in ("ball", "player", "goalkeeper", "referee") if k in names}
    return {"ball": names["sports ball"], "player": names["person"]}


def shirt_feature(frame: np.ndarray, box: np.ndarray) -> np.ndarray | None:
    """Mean Lab colour of the torso after removing pixels close to the local grass."""
    return region_colour(frame, box, 0.15, 0.5)


def region_colour(frame: np.ndarray, box: np.ndarray, top: float, bottom: float) -> np.ndarray | None:
    """Mean Lab colour of a horizontal band of a person box (fractions of its height)."""
    px = region_pixels(frame, box, top, bottom)
    return px.mean(axis=0) if px is not None else None


def region_pixels(frame: np.ndarray, box: np.ndarray, top: float, bottom: float,
                  core: float = 1.0) -> np.ndarray | None:
    """Lab pixels of a horizontal band of a person box, without grass.

    `core` < 1 keeps only that share of pixels furthest from the grass colour: on small,
    blurred players the kit edges are mixed with grass (red + green reads as brown).

    Pixels close to the local grass colour are dropped; the grass colour is the median
    of a ring around the box, so kits that are themselves green are handled correctly.
    """
    H, W = frame.shape[:2]
    x1, y1, x2, y2 = box.astype(int)
    h, w = y2 - y1, x2 - x1
    if h < 8 or w < 4:
        return None
    X1, Y1 = max(x1 - int(0.6 * w), 0), max(y1 - int(0.15 * h), 0)
    X2, Y2 = min(x2 + int(0.6 * w), W), min(y2 + int(0.15 * h), H)
    lab = cv2.cvtColor(frame[Y1:Y2, X1:X2], cv2.COLOR_BGR2LAB).astype(np.float32)
    ring = np.ones(lab.shape[:2], bool)
    ring[y1 - Y1:y2 - Y1, x1 - X1:x2 - X1] = False
    if not ring.any():
        return None
    grass = np.median(lab[ring], axis=0)
    band = lab[y1 - Y1 + int(top * h): y1 - Y1 + int(bottom * h),
               x1 - X1 + int(0.2 * w): x1 - X1 + int(0.8 * w)].reshape(-1, 3)
    dist = np.linalg.norm(band - grass, axis=1)
    keep = band[dist > 18]
    if core < 1.0 and len(keep) >= 8:
        d = dist[dist > 18]
        keep = keep[d >= np.quantile(d, 1 - core)]
    return keep if len(keep) >= 8 else None


def detect_and_track(video: Path, model: YOLO, imgsz: int, conf: float, device: str | None = None):
    if device is None:  # auto: first CUDA GPU when available, otherwise CPU
        device = "0" if torch.cuda.is_available() else "cpu"
    print(f"device: {device} (cuda available: {torch.cuda.is_available()})")
    info = sv.VideoInfo.from_video_path(str(video))
    ids = class_ids(model)
    names = {v: k for k, v in ids.items()}
    tracker = sv.ByteTrack(frame_rate=int(round(info.fps)))
    frames, features = [], []  # features: (object dict, Lab colour)

    for i, frame in enumerate(sv.get_video_frames_generator(str(video))):
        # half=True (FP16) only works on CUDA; CPU runs full precision.
        fp16 = {"half": True} if device != "cpu" else {}
        result = model.predict(frame, imgsz=imgsz, conf=conf, device=device, verbose=False, **fp16)[0]
        det = sv.Detections.from_ultralytics(result)
        is_ball = det.class_id == ids["ball"]
        balls, people = det[is_ball], det[~is_ball]
        people = people[np.isin(people.class_id, list(names))]
        people = tracker.update_with_detections(people.with_nms(0.5, class_agnostic=True))

        objects = []
        for box, cid, tid, c in zip(people.xyxy, people.class_id, people.tracker_id, people.confidence):
            o = {
                "id": int(tid),
                "cls": names[int(cid)],
                "bbox": [round(float(v), 1) for v in box],
                "foot": [round(float((box[0] + box[2]) / 2), 1), round(float(box[3]), 1)],
                "conf": round(float(c), 3),
            }
            f = shirt_feature(frame, box)
            if f is not None:
                features.append((o, f))
            objects.append(o)
        ball = None
        if len(balls):
            b = int(np.argmax(balls.confidence))
            x1, y1, x2, y2 = balls.xyxy[b]
            ball = {"center": [round(float((x1 + x2) / 2), 1), round(float((y1 + y2) / 2), 1)],
                    "bbox": [round(float(v), 1) for v in balls.xyxy[b]],
                    "conf": round(float(balls.confidence[b]), 3)}
        frames.append({"frame": i, "t": round(i / info.fps, 3), "objects": objects, "ball": ball})
        if i % 100 == 0:
            print(f"frame {i}/{info.total_frames}: {len(objects)} people, ball={'yes' if ball else 'no'}")
    return info, frames, features


def smooth_by_track(frames: list[dict], key: str, window: int) -> None:
    """Replace o[key] with the majority value of the same track within +-window frames.

    Absorbs single-frame misclassifications and short ID swaps between players.
    """
    tracks = defaultdict(list)
    for fr in frames:
        for o in fr["objects"]:
            tracks[o["id"]].append((fr["frame"], o))
    for seq in tracks.values():
        idx = np.array([f for f, _ in seq])
        raw = [o.get(key) for _, o in seq]
        for f, o in seq:
            lo, hi = np.searchsorted(idx, f - window), np.searchsorted(idx, f + window, "right")
            votes = Counter(r for r in raw[lo:hi] if r is not None)
            o[key] = votes.most_common(1)[0][0] if votes else None


def assign_teams(frames: list[dict], features: list[tuple[dict, np.ndarray]], fps: float) -> None:
    """K-Means (k=2) on shirt colours of outfield players, smoothed along each track.

    Goalkeepers join the team whose outfield players stand closer; referees get none.
    """
    # A person's role does not change, so the class is a majority over the whole track.
    smooth_by_track(frames, "cls", window=len(frames))
    outfield = [(o, f) for o, f in features if o["cls"] == "player"]
    km = KMeans(n_clusters=2, n_init=10, random_state=0).fit(np.array([f for _, f in outfield]))
    for (o, _), c in zip(outfield, km.labels_):
        o["team"] = int(c)
    smooth_by_track(frames, "team", window=int(fps))

    # "home" is the cluster whose players stand further left on average.
    xs = defaultdict(list)
    for fr in frames:
        for o in fr["objects"]:
            if o["cls"] == "player" and o.get("team") is not None:
                xs[o["team"]].append(o["foot"][0])
    left = min(xs, key=lambda c: np.mean(xs[c]))

    for fr in frames:
        for o in fr["objects"]:
            if o["cls"] == "player" and o.get("team") is not None:
                o["team"] = "home" if o["team"] == left else "away"
            else:
                o["team"] = None
        centers = {k: np.mean([o["foot"][0] for o in fr["objects"] if o["team"] == k])
                   for k in TEAM_KEYS if any(o["team"] == k for o in fr["objects"])}
        for o in fr["objects"]:
            if o["cls"] == "goalkeeper" and len(centers) == 2:
                o["team"] = min(centers, key=lambda k: abs(centers[k] - o["foot"][0]))


def render(video: Path, info: sv.VideoInfo, frames: list[dict], out_path: Path) -> None:
    ellipse = {k: sv.EllipseAnnotator(color=c, thickness=2) for k, c in COLORS.items()}
    label = {k: sv.LabelAnnotator(color=c, text_scale=0.45, text_padding=3,
                                  text_position=sv.Position.BOTTOM_CENTER) for k, c in COLORS.items()}
    ball_marker = sv.TriangleAnnotator(color=sv.Color.WHITE, base=18, height=15)
    trace = sv.TraceAnnotator(color=sv.Color.WHITE, trace_length=25, thickness=2,
                              position=sv.Position.CENTER)

    with sv.VideoSink(str(out_path), info) as sink:
        for frame, fr in zip(sv.get_video_frames_generator(str(video)), frames):
            groups = defaultdict(list)
            for o in fr["objects"]:
                key = "referee" if o["cls"] == "referee" else (
                    "goalkeeper" if o["cls"] == "goalkeeper" else o.get("team") or "unknown")
                groups[key].append(o)
            for key, objs in groups.items():
                d = sv.Detections(xyxy=np.array([o["bbox"] for o in objs]),
                                  class_id=np.zeros(len(objs), dtype=int),
                                  tracker_id=np.array([o["id"] for o in objs]))
                frame = ellipse[key].annotate(frame, d)
                frame = label[key].annotate(frame, d, labels=[f"#{o['id']}" for o in objs])
            if fr["ball"]:
                d = sv.Detections(xyxy=np.array([fr["ball"]["bbox"]]), class_id=np.array([0]),
                                  tracker_id=np.array([0]))
                frame = trace.annotate(frame, d)
                frame = ball_marker.annotate(frame, d)
            sink.write_frame(frame)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", type=Path, default=Path("match/sample_match.mp4"))
    ap.add_argument("--weights", default="yolov8x.pt", help="custom football model or COCO yolov8")
    ap.add_argument("--imgsz", type=int, default=1920)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--out", type=Path, default=Path("match/out"))
    ap.add_argument("--device", default=None,
                    help='override device, e.g. "cpu" or "0"; default: CUDA "0" if available, else CPU')
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    model = YOLO(args.weights)
    info, frames, features = detect_and_track(args.video, model, args.imgsz, args.conf, args.device)
    assign_teams(frames, features, info.fps)

    with open(args.out / "tracks.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for fr in frames:
            fh.write(json.dumps(fr, separators=(",", ":")) + "\n")
    render(args.video, info, frames, args.out / "tracked.mp4")

    ball_rate = sum(fr["ball"] is not None for fr in frames) / len(frames)
    counts = Counter(o["cls"] for fr in frames for o in fr["objects"])
    print(f"frames {len(frames)}, unique tracks {len({o['id'] for fr in frames for o in fr['objects']})}")
    print("mean detections/frame "
          + ", ".join(f"{k} {v / len(frames):.1f}" for k, v in counts.items()))
    print(f"ball found in {100 * ball_rate:.0f}% of frames")
    print(f"written to {args.out}")


if __name__ == "__main__":
    main()

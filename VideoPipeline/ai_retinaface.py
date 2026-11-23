"""RetinaFace-only first-pass detector for the experimental video branch.

No automatic censoring approval or identity recognition. Sampling, grouping and
bounding-box margins match the MediaPipe experiment for comparison.
"""
from __future__ import annotations

import math

from VideoPipeline.ai_faces import MAX_SAMPLES

# A detection score is not a probability of successful de-identification.
DETECTION_THRESHOLD = 0.5
FACE_MARGIN = 0.20


def normalize_face(area, width: int, height: int):
    """Convert RetinaFace [left, top, right, bottom] pixels to a padded box."""
    if not isinstance(area, (list, tuple)) or len(area) != 4 or width <= 0 or height <= 0:
        return None
    try:
        left, top, right, bottom = (float(v) for v in area)
    except (TypeError, ValueError):
        return None
    if not all(map(math.isfinite, (left, top, right, bottom))):
        return None
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None
    x0 = max(0., (left - FACE_MARGIN * w) / width)
    y0 = max(0., (top - FACE_MARGIN * h) / height)
    x1 = min(1., (right + FACE_MARGIN * w) / width)
    y1 = min(1., (bottom + FACE_MARGIN * h) / height)
    if x1 - x0 < .01 or y1 - y0 < .01:
        return None
    return {"x": round(x0, 6), "y": round(y0, 6),
            "w": round(x1 - x0, 6), "h": round(y1 - y0, 6)}


def normalize_detections(results, width: int, height: int):
    """Allow the library's empty dict response and ignore malformed entries."""
    if not isinstance(results, dict):
        raise RuntimeError("RetinaFace produced an unexpected detection response.")
    faces = []
    for item in results.values():
        if not isinstance(item, dict):
            continue
        box = normalize_face(item.get("facial_area"), width, height)
        try:
            confidence = float(item.get("score", 0))
        except (ValueError, TypeError):
            continue
        if box and math.isfinite(confidence) and confidence >= DETECTION_THRESHOLD:
            faces.append({"box": box, "score": confidence})
    return faces



def _center_distance(a, b):
    ax, ay = a["x"] + a["w"] / 2, a["y"] + a["h"] / 2
    bx, by = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    return math.hypot(ax - bx, ay - by)


def _matchable(a, b):
    # Conservative gating limits identity swaps when people cross.
    return _center_distance(a, b) <= max(
        .055, .65 * max(a["w"], a["h"], b["w"], b["h"])
    )


def _suggestions_with_tracking(detections, path, clip_start, clip_end, interval):
    """Associate face detections with frame-by-frame optical-flow positions.

    Uncorroborated motion and tracking failures terminate a proposal, rather
    than silently claiming that a face remains covered.
    """
    from VideoPipeline.advanced import track_region

    duration = clip_end - clip_start
    finished, active = [], []
    for _, at, faces in detections:
        predictions = []
        for tr in active:
            try:
                motion = track_region(
                    path, clip_start, clip_end, tr["box"],
                    tr["last_t"], at, every_frame=True,
                )
            except (RuntimeError, ValueError) as exc:
                motion = {"complete": False, "warning": str(exc)}
            if not motion.get("complete") or not motion.get("keyframes"):
                tr["message"] = (
                    "Tracking stopped before the next detector sample. "
                    + str(motion.get("warning", ""))
                )
                tr["tracking_complete"] = False
                finished.append(tr)
                continue
            points = motion["keyframes"]
            if len(tr["keyframes"]) + len(points) > 20000:
                tr["tracking_complete"] = False
                tr["message"] = "Maximum tracking keyframes reached; review remaining video."
                finished.append(tr)
                continue
            predicted = {
                "x": float(points[-1]["x"]), "y": float(points[-1]["y"]),
                "w": tr["box"]["w"], "h": tr["box"]["h"]
            }
            predictions.append((tr, points, predicted))

        candidates = sorted(
            (_center_distance(pred, face["box"]), i, j)
            for i, (_, _, pred) in enumerate(predictions)
            for j, face in enumerate(faces)
            if _matchable(pred, face["box"])
        )
        used_tracks, used_faces, matches = set(), set(), {}
        for _, i, j in candidates:
            if i not in used_tracks and j not in used_faces:
                used_tracks.add(i)
                used_faces.add(j)
                matches[i] = j

        next_active = []
        for i, (tr, points, predicted) in enumerate(predictions):
            if i not in matches:
                tr["tracking_complete"] = False
                tr["message"] = (
                    "Face was not confirmed at the next detection sample. "
                    "Review the uncovered interval and manually extend the mask if necessary."
                )
                finished.append(tr)
                continue
            face = faces[matches[i]]
            last_t = tr["last_t"]
            tr["keyframes"].extend(
                dict(point) for point in points if point["t"] > last_t + 1e-5
            )
            tr["box"] = predicted
            tr["last_t"] = at
            tr["sample_count"] += 1
            tr["confidence"] = min(tr["confidence"], face["score"])
            tr["tracking_complete"] = True
            next_active.append(tr)

        for j, face in enumerate(faces):
            if j in used_faces:
                continue
            box = dict(face["box"])
            next_active.append({
                "box": box, "start": at, "last_t": at,
                "keyframes": [{"t": round(at, 4), **box}],
                "sample_count": 1, "confidence": face["score"],
                "tracking_complete": False,
                "message": "Only one sampled face detection; continuous motion is unverified.",
            })
        active = next_active

    finished.extend(active)
    proposals = []
    for tr in finished:
        points = tr["keyframes"]
        start, end = max(0., float(tr["start"])), float(tr["last_t"])
        motion_complete = tr["tracking_complete"] and len(points) > 1 and end > start
        if end <= start:
            # Single detection: allow review of a static box, not a track.
            end = min(duration, start + max(.05, interval / 2))
        if end <= start:
            continue
        first_box = points[0]
        proposals.append({
            "start": round(start, 4), "end": round(end, 4),
            "x": first_box["x"], "y": first_box["y"],
            "w": tr["box"]["w"], "h": tr["box"]["h"],
            "sampled_positions": points,
            "tracked_keyframes": points if motion_complete else [],
            "tracking_complete": motion_complete,
            "tracking_message": (
                "Optical flow linked detections frame by frame. Review for drift, "
                "occlusion, changes in face size and missed frames."
                if motion_complete else tr["message"]
            ),
            "confidence": round(float(tr["confidence"]), 3),
            "sample_count": tr["sample_count"], "kind": "face",
        })
    return sorted(proposals, key=lambda item: (item["start"], item["x"]))


def scan_faces(path: str, clip_start: float, clip_end: float) -> dict:
    """Run locally on sampled video frames, returning only unapproved suggestions."""
    try:
        import cv2
        from retinaface import RetinaFace
    except ImportError as exc:
        raise RuntimeError(
            "RetinaFace scanner requires opencv-python and retina-face. "
            "See VideoPipeline/README.md for setup in CoCANoT's Python environment."
        ) from exc

    duration = clip_end - clip_start
    if not all(math.isfinite(v) for v in (clip_start, clip_end)) or duration <= 0:
        raise ValueError("Invalid video interval.")

    # Preserve the sampling cadence on the MediaPipe and YuNet branches.
    interval = max(.5, duration / MAX_SAMPLES)
    sample_count = min(MAX_SAMPLES, max(1, math.ceil(duration / interval)))
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("Cannot open video for RetinaFace scanning.")

    detections = []
    unreadable = 0
    try:
        try:
            # Build weights once per scan, not once per sampled frame.
            # Pre-download weights on synthetic footage before any PHI work.
            model = RetinaFace.build_model()
        except Exception as exc:
            raise RuntimeError(
                "RetinaFace model could not load. Verify the backend and preload "
                "model weights on a non-sensitive test before scanning recordings."
            ) from exc
        for index in range(sample_count):
            t = min(duration - .0001, (index + .5) * duration / sample_count)
            cap.set(cv2.CAP_PROP_POS_MSEC, (clip_start + t) * 1000)
            ok, frame = cap.read()
            if not ok:
                unreadable += 1
                detections.append((index, t, []))
                continue
            height, width = frame.shape[:2]
            try:
                raw = RetinaFace.detect_faces(
                    img_path=frame, threshold=DETECTION_THRESHOLD,
                    model=model, allow_upscaling=True)
            except Exception as exc:
                raise RuntimeError(
                    f"RetinaFace inference failed at clip-relative {t:.2f}s. "
                    "The scan did not create or approve any censor boxes."
                ) from exc
            detections.append((index, t, normalize_detections(raw, width, height)))
    finally:
        cap.release()

    return {
        "suggestions": _suggestions_with_tracking(
            detections, path, clip_start, clip_end, duration / sample_count
        ),
        "sampled_frames": sample_count, "unreadable_frames": unreadable,
        "sample_interval": round(duration / sample_count, 3),
        "detector": "RetinaFace",
        "warning": "RetinaFace samples detection frames and optical flow follows matched faces between samples. "
                   "A tracker failure ends that proposal. Review all footage for drift, gaps and missed faces."
    }

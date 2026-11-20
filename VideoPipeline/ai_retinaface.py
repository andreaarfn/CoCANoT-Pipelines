"""RetinaFace-only first-pass detector for the experimental video branch.

No automatic censoring approval or identity recognition. Sampling, grouping and
bounding-box margins match the MediaPipe experiment for comparison.
"""
from __future__ import annotations

import math

from VideoPipeline.ai_faces import MAX_SAMPLES, _assemble

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
        "suggestions": _assemble(detections, duration / sample_count, duration),
        "sampled_frames": sample_count, "unreadable_frames": unreadable,
        "sample_interval": round(duration / sample_count, 3),
        "detector": "RetinaFace",
        "warning": "RetinaFace checks sampled frames only; missed or obscured faces remain possible. "
                   "Inspect every recording, track and correct accepted censor boxes, and verify final export."
    }

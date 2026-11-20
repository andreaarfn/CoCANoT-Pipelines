"""Local MediaPipe Tasks first-pass face suggestions. No source video is modified.

This is sampled detection, NOT continuous privacy coverage. A human must review
all footage and tracking before exporting any video as de-identified.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

MAX_SAMPLES = 1200
MODEL_NAME = "blaze_face_short_range.tflite"


def model_path() -> Path:
    configured = os.environ.get("COCANOT_MEDIAPIPE_FACE_MODEL", "").strip()
    path = Path(configured).expanduser() if configured else Path(__file__).parent / "models" / MODEL_NAME
    if not path.is_file():
        raise RuntimeError(
            "MediaPipe face model is not installed. Download blaze_face_short_range.tflite "
            "as documented in VideoPipeline/README.md, or set COCANOT_MEDIAPIPE_FACE_MODEL."
        )
    return path


def _rect(detection, width: int, height: int):
    box = detection.bounding_box
    # Extra 20% margin reduces the risk of cropping facial features.
    margin_x, margin_y = box.width * .20, box.height * .20
    left = max(0., (box.origin_x - margin_x) / width)
    top = max(0., (box.origin_y - margin_y) / height)
    right = min(1., (box.origin_x + box.width + margin_x) / width)
    bottom = min(1., (box.origin_y + box.height + margin_y) / height)
    if right-left < .01 or bottom-top < .01:
        return None
    return {"x": round(left, 6), "y": round(top, 6),
            "w": round(right-left, 6), "h": round(bottom-top, 6)}


def _near(a, b):
    cx, cy = a["x"] + a["w"]/2, a["y"] + a["h"]/2
    dx, dy = b["x"] + b["w"]/2, b["y"] + b["h"]/2
    return math.hypot(cx-dx, cy-dy) <= max(.08, .8 * max(a["w"], a["h"], b["w"], b["h"]))


def _assemble(detections, interval, duration):
    """Group only detections at consecutive sample positions; never bridge a missed detection."""
    tracks = []
    active = []
    for sample_index, t, faces in detections:
        next_active = []
        used = set()
        for track in active:
            last = track["observations"][-1]
            if sample_index - last["sample"] != 1:
                continue
            choices = [(i, face) for i, face in enumerate(faces)
                       if i not in used and _near(last["box"], face["box"])]
            if choices:
                i, face = min(choices, key=lambda pair:
                              math.hypot((last["box"]["x"]+last["box"]["w"]/2)-(pair[1]["box"]["x"]+pair[1]["box"]["w"]/2),
                                         (last["box"]["y"]+last["box"]["h"]/2)-(pair[1]["box"]["y"]+pair[1]["box"]["h"]/2)))
                track["observations"].append({"sample":sample_index, "t":t, **face})
                next_active.append(track)
                used.add(i)
        for i, face in enumerate(faces):
            if i not in used:
                track = {"observations": [{"sample":sample_index, "t":t, **face}]}
                tracks.append(track)
                next_active.append(track)
        active = next_active

    suggestions = []
    for track in tracks:
        obs = track["observations"]
        start = max(0., obs[0]["t"] - interval/2)
        end = min(duration, obs[-1]["t"] + interval/2)
        if end <= start:
            continue
        width = max(o["box"]["w"] for o in obs)
        height = max(o["box"]["h"] for o in obs)
        keyframes = []
        for o in obs:
            box = o["box"]
            center_x = box["x"] + box["w"]/2
            center_y = box["y"] + box["h"]/2
            keyframes.append({"t": round(o["t"], 4),
                              "x": round(max(0., min(1-width, center_x-width/2)), 6),
                              "y": round(max(0., min(1-height, center_y-height/2)), 6),
                              "w": round(width, 6), "h": round(height, 6)})
        # A proposal is just a position hint. Do not automatically promote sampled
        # detections to validated tracking keyframes or claim continuous coverage.
        suggestions.append({"start": round(start, 4), "end": round(end, 4),
                            "x": keyframes[0]["x"], "y": keyframes[0]["y"],
                            "w": round(width, 6), "h": round(height, 6),
                            "sampled_positions": keyframes,
                            "confidence": round(min(o["score"] for o in obs), 3),
                            "sample_count": len(obs), "kind": "face"})
    return suggestions


def scan_faces(path: str, clip_start: float, clip_end: float) -> dict:
    """Run offline face detection over uniformly sampled frames of a trimmed clip."""
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
    except ImportError as exc:
        raise RuntimeError("AI face scan requires mediapipe and opencv-python in CoCANoT's Python environment.") from exc

    duration = clip_end - clip_start
    if not all(math.isfinite(v) for v in (clip_start, clip_end)) or duration <= 0:
        raise ValueError("Invalid video interval.")
    interval = max(.5, duration / MAX_SAMPLES)
    sample_count = min(MAX_SAMPLES, max(1, math.ceil(duration / interval)))
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("Cannot open video for AI face scanning.")
    detections = []
    unreadable = 0
    try:
        options = vision.FaceDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path())),
            running_mode=vision.RunningMode.IMAGE,
            min_detection_confidence=.5)
        with vision.FaceDetector.create_from_options(options) as detector:
            for index in range(sample_count):
                t = min(duration - .0001, (index + .5) * duration / sample_count)
                cap.set(cv2.CAP_PROP_POS_MSEC, (clip_start+t)*1000)
                ok, frame = cap.read()
                if not ok:
                    unreadable += 1
                    detections.append((index, t, []))
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                height, width = rgb.shape[:2]
                faces = []
                for d in result.detections:
                    box = _rect(d, width, height)
                    if box:
                        faces.append({"box": box, "score": float(d.categories[0].score) if d.categories else 0.})
                detections.append((index, t, faces))
    finally:
        cap.release()
    return {"suggestions": _assemble(detections, duration/sample_count, duration),
            "sampled_frames": sample_count, "unreadable_frames": unreadable,
            "sample_interval": round(duration/sample_count, 3),
            "warning": "Sampled face detection does not establish continuous censoring coverage. "
                       "Review all footage, including frames between samples; track or correct every accepted region."}

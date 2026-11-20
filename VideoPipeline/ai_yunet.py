"""Offline YuNet-only face scan experiment for CoCANoT.

Sampling and grouping deliberately match the MediaPipe comparison branch.
Detections are *suggestions*, not validated de-identification or tracking.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

from VideoPipeline.ai_faces import MAX_SAMPLES, _assemble

MODEL_NAME = "face_detection_yunet_2023mar.onnx"
# Identical threshold to the MediaPipe experimental branch for an initial
# comparison of reported detections, not a calibrated equal-error comparison.
DETECTION_THRESHOLD = 0.5


def model_path() -> Path:
    override = os.environ.get("COCANOT_YUNET_FACE_MODEL", "").strip()
    path = Path(override).expanduser() if override else Path(__file__).parent / "models" / MODEL_NAME
    if not path.is_file():
        raise RuntimeError(
            "YuNet model is not installed. Follow VideoPipeline/README.md to download "
            "face_detection_yunet_2023mar.onnx locally or set COCANOT_YUNET_FACE_MODEL."
        )
    return path


def face_box(row, width: int, height: int):
    """Convert a YuNet [x,y,w,h,...,score] detection into a padded 0..1 box."""
    x, y, w, h = [float(v) for v in row[:4]]
    if not all(math.isfinite(v) for v in (x,y,w,h)) or w <= 0 or h <= 0:
        return None
    margin_x, margin_y = w * .20, h * .20
    left = max(0., (x-margin_x)/width)
    top = max(0., (y-margin_y)/height)
    right = min(1., (x+w+margin_x)/width)
    bottom = min(1., (y+h+margin_y)/height)
    if right-left < .01 or bottom-top < .01:
        return None
    return {"x":round(left,6),"y":round(top,6),
            "w":round(right-left,6),"h":round(bottom-top,6)}


def scan_faces(path: str, clip_start: float, clip_end: float) -> dict:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("YuNet face scanning requires opencv-python in CoCANoT's Python environment.") from exc
    if not hasattr(cv2, "FaceDetectorYN"):
        raise RuntimeError("Installed OpenCV does not provide FaceDetectorYN. Update opencv-python.")
    duration = clip_end - clip_start
    if not all(math.isfinite(v) for v in (clip_start, clip_end)) or duration <= 0:
        raise ValueError("Invalid video interval.")

    # Retain exactly the MediaPipe prototype's frame-sampling schedule.
    interval = max(.5, duration / MAX_SAMPLES)
    sample_count = min(MAX_SAMPLES, max(1, math.ceil(duration/interval)))
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("Cannot open video for YuNet face scanning.")
    detections = []
    unreadable = 0
    try:
        detector = cv2.FaceDetectorYN.create(
            str(model_path()), "", (320,320),
            score_threshold=DETECTION_THRESHOLD,
            nms_threshold=.3, top_k=5000)
        for index in range(sample_count):
            t = min(duration - .0001, (index+.5)*duration/sample_count)
            cap.set(cv2.CAP_PROP_POS_MSEC, (clip_start+t)*1000)
            ok, frame = cap.read()
            if not ok:
                unreadable += 1
                detections.append((index,t,[]))
                continue
            height,width = frame.shape[:2]
            detector.setInputSize((width,height))
            _, rows = detector.detect(frame)
            faces = []
            if rows is not None:
                for row in rows:
                    box = face_box(row,width,height)
                    score = float(row[14])
                    if box and math.isfinite(score):
                        faces.append({"box":box,"score":score})
            detections.append((index,t,faces))
    finally:
        cap.release()
    return {"suggestions":_assemble(detections,duration/sample_count,duration),
            "sampled_frames":sample_count,"unreadable_frames":unreadable,
            "sample_interval":round(duration/sample_count,3),
            "detector":"YuNet",
            "warning":"YuNet scans sampled frames only. Face detection may miss profile, "
                      "occluded or downward-facing people. Review all footage and "
                      "manually track/correct every accepted censor box."}

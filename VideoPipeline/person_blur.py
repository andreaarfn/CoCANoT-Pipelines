"""Optional local person-aware background blur support.

Only the model weights are downloaded on explicit user request. Video
frames remain inside the desktop application.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
import urllib.request

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "image_segmenter/selfie_segmenter/float16/1/selfie_segmenter.tflite"
)
MAX_MODEL_SIZE = 25 * 1024 * 1024


def model_path() -> Path:
    return Path(os.environ.get(
        "COCANOT_PERSON_SEGMENTATION_MODEL",
        str(Path.home() / ".cocanot" / "models" / "selfie_segmenter.tflite"),
    )).expanduser()


def status() -> dict:
    model = model_path()
    try:
        import mediapipe as mp
        available = hasattr(mp, "tasks") and hasattr(mp.tasks, "vision")
    except (ImportError, AttributeError):
        available = False
    return {
        "runtime_installed": available,
        "model_installed": model.is_file() and 100_000 < model.stat().st_size < MAX_MODEL_SIZE,
        "model_path": str(model),
        "ready": available and model.is_file() and 100_000 < model.stat().st_size < MAX_MODEL_SIZE,
        "setup_hint": "Install the optional runtime into your CoCANoT Python environment: python -m pip install mediapipe",
    }


def download_model() -> dict:
    """Download only official public model weights after explicit button press."""
    target = model_path()
    current = status()
    if current["model_installed"]:
        return current
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".download")
    if temp.exists():
        temp.unlink()
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "CoCANoT-Pipelines"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response, temp.open("wb") as handle:
            if response.geturl() != MODEL_URL:
                raise RuntimeError("Unexpected redirect while downloading person segmentation model.")
            size = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_MODEL_SIZE:
                    raise RuntimeError("Downloaded segmentation model exceeds expected maximum size.")
                handle.write(chunk)
        if size < 100_000:
            raise RuntimeError("Downloaded model is unexpectedly small.")
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()
    return status()


def preview_frame(clip: dict, relative_time: float) -> dict:
    """Create a person-blurred still frame in memory for the desktop UI."""
    import math
    from VideoPipeline.processing import validate_project
    from VideoPipeline.advanced import _canvas, _cv2, PersonBackgroundSegmenter
    validated = validate_project({"clips": [{**clip, "masks": []}]})[0]
    cv2 = _cv2()
    duration = validated["end"] - validated["start"]
    if not math.isfinite(relative_time) or not (0 <= relative_time <= duration):
        raise ValueError("Preview time is outside the selected clip.")
    cap = cv2.VideoCapture(validated["media"]["path"])
    if not cap.isOpened():
        raise RuntimeError("Could not decode video for blur preview.")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_no = max(0, round((validated["start"] + relative_time) * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_no - 1))
            ok, frame = cap.read()
        if not ok:
            raise RuntimeError("Could not decode the selected frame.")
    finally:
        cap.release()
    segmenter = PersonBackgroundSegmenter()
    try:
        rendered = segmenter.apply(_canvas(frame, cv2), cv2, relative_time)
    finally:
        segmenter.close()
    ok, encoded = cv2.imencode(".jpg", rendered, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("Could not encode blurred preview.")
    return {
        "image": "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii"),
        "time": relative_time,
        "note": "Single-frame person blur preview. Inspect the final video for privacy.",
    }


def preview_polygon_frame(clip: dict, relative_time: float) -> dict:
    """Generate a frame-accurate still showing manual foreground preservation."""
    import math
    from VideoPipeline.processing import validate_project
    from VideoPipeline.advanced import _canvas, _cv2, apply_polygon_background_blur
    validated = validate_project({"clips": [{**clip, "masks": []}]})[0]
    blur = validated.get("background_blur") or {}
    if not blur.get("enabled") or blur.get("mode") != "polygon":
        raise ValueError("Enable the draw-your-own background blur mode first.")
    duration = validated["end"] - validated["start"]
    if not math.isfinite(relative_time) or not (0 <= relative_time <= duration):
        raise ValueError("Preview timestamp is outside the clip.")
    cv2 = _cv2()
    cap = cv2.VideoCapture(validated["media"]["path"])
    if not cap.isOpened():
        raise RuntimeError("Cannot open video to generate blur preview.")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_no = max(0, round((validated["start"] + relative_time) * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_no - 1))
            ok, frame = cap.read()
        if not ok:
            raise RuntimeError("Cannot decode selected video frame.")
    finally:
        cap.release()
    image = _canvas(frame, cv2)
    image = apply_polygon_background_blur(
        image, blur["polygons"], cv2,
        feather=float(blur.get("feather", 9)),
        sigma=float(blur.get("strength", 24)))
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise RuntimeError("Unable to encode background blur preview.")
    return {
        "image": "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii"),
        "time": relative_time,
        "note": "Preview of manual subject mask; inspect rendered output.",
    }

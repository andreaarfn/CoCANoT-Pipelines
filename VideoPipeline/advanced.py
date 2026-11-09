"""Optical template tracking and frame-accurate mask/blur rendering.

For research prototyping only: manual inspection of the final output is mandatory.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path


def _cv2():
    try:
        import cv2
        return cv2
    except ImportError as exc:
        raise RuntimeError("Motion tracking and background blur require OpenCV: python -m pip install opencv-python") from exc


def _canvas(frame, cv2):
    height, width = frame.shape[:2]
    if width <= 0 or height <= 0:
        raise ValueError("Cannot decode video frame.")
    ratio = min(1280 / width, 720 / height)
    new_width, new_height = max(1, round(width * ratio)), max(1, round(height * ratio))
    resized = cv2.resize(frame, (new_width, new_height))
    import numpy as np
    canvas = np.zeros((720, 1280, 3), dtype="uint8")
    x, y = (1280 - new_width) // 2, (720 - new_height) // 2
    canvas[y:y + new_height, x:x + new_width] = resized
    return canvas


def _rect(region):
    x = max(0, min(1279, round(float(region["x"]) * 1280)))
    y = max(0, min(719, round(float(region["y"]) * 720)))
    width = max(1, min(1280 - x, round(float(region["w"]) * 1280)))
    height = max(1, min(720 - y, round(float(region["h"]) * 720)))
    return x, y, width, height


def _interpolate(region, time):
    points = region.get("keyframes") or []
    if not points:
        return region
    ordered = sorted(points, key=lambda item: float(item["t"]))
    if time <= float(ordered[0]["t"]):
        return {**region, **ordered[0]}
    for left, right in zip(ordered, ordered[1:]):
        lo, hi = float(left["t"]), float(right["t"])
        if lo <= time <= hi:
            factor = (time - lo) / max(1e-8, hi - lo)
            return {**region, **{k: float(left[k]) * (1 - factor) + float(right[k]) * factor for k in ("x", "y", "w", "h")}}
    return {**region, **ordered[-1]}


def track_region(path: str, clip_start: float, clip_end: float, region: dict, from_time: float) -> dict:
    """Track a rectangle forward using local template matching.

    A confidence failure stops tracking; never silently extrapolates beyond it.
    """
    cv2 = _cv2()
    video = cv2.VideoCapture(path)
    if not video.isOpened():
        raise ValueError("Cannot open video for tracking.")
    try:
        fps = video.get(cv2.CAP_PROP_FPS) or 30
        start_frame = max(0, round((clip_start + from_time) * fps))
        end_frame = min(round(clip_end * fps), start_frame + round(fps * 120))
        video.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        success, frame = video.read()
        if not success:
            raise ValueError("Could not read selected starting frame.")
        canvas = _canvas(frame, cv2)
        x, y, w, h = _rect(region)
        if w < 12 or h < 12:
            raise ValueError("Tracking region must be at least 12 pixels wide and high.")
        template = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)[y:y+h, x:x+w].copy()
        if template.shape[:2] != (h, w):
            raise ValueError("Tracking region is outside the video.")
        keyframes = [{"t": float(from_time), "x": x/1280, "y": y/720, "w": w/1280, "h": h/720}]
        failed = False
        sampled = 0
        # One sample every ~0.15 seconds, keeping processing practical on laptops.
        stride = max(1, round(fps / 7))
        frame_index = start_frame
        while frame_index + stride < end_frame:
            for _ in range(stride - 1):
                if not video.grab():
                    failed = True
                    break
            if failed:
                break
            ok, frame = video.read()
            if not ok:
                failed = True
                break
            frame_index += stride
            canvas = _canvas(frame, cv2)
            gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
            margin = max(26, round(max(w, h) * 0.65))
            left = max(0, x - margin)
            top = max(0, y - margin)
            right = min(1280, x + w + margin)
            bottom = min(720, y + h + margin)
            search = gray[top:bottom, left:right]
            if search.shape[0] < h or search.shape[1] < w:
                failed = True
                break
            match = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(match)
            if not math.isfinite(score) or score < 0.55:
                failed = True
                break
            x, y = left + location[0], top + location[1]
            # Slow adaptation helps accommodate lighting changes.
            new_patch = gray[y:y+h, x:x+w]
            template = cv2.addWeighted(template, 0.8, new_patch, 0.2, 0)
            t = (frame_index / fps) - clip_start
            keyframes.append({"t": round(t, 4), "x": x/1280, "y": y/720, "w": w/1280, "h": h/720})
            sampled += 1
        last_time = float(keyframes[-1]["t"])
        expected_end = clip_end - clip_start
        complete = not failed and frame_index + stride >= end_frame and end_frame >= round(clip_end * fps) - stride
        return {"keyframes": keyframes, "tracked_until": last_time,
                "complete": complete, "warning": "" if complete else
                f"Tracking ended at {last_time:.2f}s (loss of confidence or 120s tracking limit). Reposition the mask and track again; review every affected frame."}
    finally:
        video.release()


def render_advanced(clips: list[dict], temp: Path, ffmpeg_binary: str) -> None:
    """Render with moving masks and background blur; video audio is removed."""
    cv2 = _cv2()
    command = [ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1280x720", "-r", "30",
               "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temp)]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for clip in clips:
            cap = cv2.VideoCapture(clip["media"]["path"])
            if not cap.isOpened():
                raise RuntimeError(f"Cannot decode {clip['media']['name']}")
            try:
                fps = cap.get(cv2.CAP_PROP_FPS) or 30
                first = round(clip["start"] * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, first)
                read_index = first - 1
                current_frame = None
                output_count = math.ceil((clip["end"] - clip["start"]) * 30)
                for idx in range(output_count):
                    time = idx / 30
                    wanted = max(first, round((clip["start"] + time) * fps))
                    while read_index < wanted:
                        success, frame = cap.read()
                        if not success:
                            raise RuntimeError(f"Unexpected end of video: {clip['media']['name']}")
                        current_frame = frame
                        read_index += 1
                    image = _canvas(current_frame, cv2)
                    background = clip.get("background_blur")
                    if background and background.get("enabled"):
                        preserve = _rect(background)
                        # Strong but not irreversible background blur.
                        blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=24)
                        x, y, w, h = preserve
                        blurred[y:y+h, x:x+w] = image[y:y+h, x:x+w]
                        image = blurred
                    for mask in clip.get("masks", []):
                        if float(mask.get("start", 0)) <= time <= float(mask.get("end", clip["end"] - clip["start"])):
                            region = _interpolate(mask, time)
                            x, y, w, h = _rect(region)
                            image[y:y+h, x:x+w] = 0
                    if proc.stdin is None:
                        raise RuntimeError("FFmpeg export input closed.")
                    proc.stdin.write(image.tobytes())
            finally:
                cap.release()
        proc.stdin.close()
        message = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        result = proc.wait(timeout=600)
        if result:
            raise RuntimeError(f"FFmpeg encoding failed: {message[-1500:]}")
    except Exception:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        raise

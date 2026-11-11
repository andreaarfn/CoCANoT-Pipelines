"""Optical-flow tracking and frame-accurate opaque censor-mask rendering.

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
        raise RuntimeError("Motion-tracked censor rendering requires OpenCV: python -m pip install opencv-python") from exc


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
    """Move tracked boxes without changing their original dimensions.

    Also prevents older saved tracks with scale drift from expanding masks.
    """
    points = region.get("keyframes") or []
    if not points:
        return region
    ordered = sorted(points, key=lambda item: float(item["t"]))
    fixed_w, fixed_h = float(region["w"]), float(region["h"])
    def fixed(point):
        # Clamp the position to keep the original-size redaction on-screen.
        return {**region, "x": max(0.0, min(1.0-fixed_w, float(point["x"]))),
                "y": max(0.0, min(1.0-fixed_h, float(point["y"]))),
                "w": fixed_w, "h": fixed_h}
    if time <= float(ordered[0]["t"]):
        return fixed(ordered[0])
    for left, right in zip(ordered, ordered[1:]):
        lo, hi = float(left["t"]), float(right["t"])
        if lo <= time <= hi:
            factor = (time - lo) / max(1e-8, hi - lo)
            return fixed({k: float(left[k])*(1-factor) + float(right[k])*factor for k in ("x","y")})
    return fixed(ordered[-1])


def track_region(path: str, clip_start: float, clip_end: float, region: dict,
                 from_time: float, until_time: float) -> dict:
    """Fixed-size translation tracking over an explicit censor interval.

    Motion uses robust inlier translations; estimated scaling is ignored. Template matching can recover
    from feature-loss on low-texture targets. Neither method silently accepts
    uncertain detections: export validation retains the gap warning.
    """
    cv2 = _cv2()
    import numpy as np
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("Cannot open video for tracking.")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        if not math.isfinite(fps) or fps <= 0:
            fps = 30.0
        duration = clip_end - clip_start
        if not (0 <= from_time < until_time <= duration + 1e-6):
            raise ValueError("Tracking start/end are outside the clip.")
        start_frame = max(0, round((clip_start + from_time) * fps))
        end_frame = max(start_frame, min(
            round((clip_start + until_time) * fps),
            max(0, round(clip_end * fps) - 1)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        ok, image = cap.read()
        if not ok:
            raise ValueError("Unable to read censor region's starting frame.")
        previous = cv2.cvtColor(_canvas(image, cv2), cv2.COLOR_BGR2GRAY)
        x, y, w, h = _rect(region)
        if min(w, h) < 12:
            raise ValueError("Draw a larger censor region (at least 12 pixels).")

        def get_features(gray, bounds):
            bx, by, bw, bh = bounds
            mask = np.zeros(gray.shape, np.uint8)
            inset = max(1, min(bw, bh) // 16)
            mask[by + inset:by + bh - inset, bx + inset:bx + bw - inset] = 255
            return cv2.goodFeaturesToTrack(gray, 140, 0.008, 4, mask=mask)

        def sample_template(gray, bounds):
            bx, by, bw, bh = bounds
            return gray[by:by+bh, bx:bx+bw].copy()

        points = get_features(previous, (x, y, w, h))
        reference = sample_template(previous, (x, y, w, h))
        frames = [{"t":round(float(from_time), 4), "x":x/1280, "y":y/720,
                   "w":w/1280, "h":h/720}]
        index = start_frame
        # Smaller gaps reduce feature loss between consecutive optical-flow steps.
        stride = max(1, round(fps / 15))
        warning = ""
        fallback_frames = 0
        fixed_width, fixed_height = w, h

        while index < end_frame:
            step = min(stride, end_frame - index)
            for _ in range(step - 1):
                if not cap.grab():
                    warning = "Video decoding stopped unexpectedly."
                    break
            if warning:
                break
            ok, image = cap.read()
            if not ok:
                warning = "Unable to decode a video frame."
                break
            index += step
            current = cv2.cvtColor(_canvas(image, cv2), cv2.COLOR_BGR2GRAY)
            bounds = None
            if points is not None and len(points) >= 5:
                next_points, status, _ = cv2.calcOpticalFlowPyrLK(
                    previous, current, points, None, winSize=(29, 29), maxLevel=3)
                if next_points is not None and status is not None:
                    good = status.ravel() == 1
                    source = points.reshape(-1, 2)[good]
                    dest = next_points.reshape(-1, 2)[good]
                    if len(source) >= 5:
                        back, back_status, _ = cv2.calcOpticalFlowPyrLK(
                            current, previous, dest.astype("float32").reshape(-1,1,2), None)
                        if back is not None and back_status is not None:
                            error = np.linalg.norm(source - back.reshape(-1,2), axis=1)
                            consistent = (back_status.ravel() == 1) & (error < 3.5)
                            source, dest = source[consistent], dest[consistent]
                            if len(source) >= 5:
                                # Do NOT transform all four rectangle corners:
                                # accumulated RANSAC scale/rotation expands
                                # boxes even when the object barely changes size.
                                # Estimate robust translation only and keep the
                                # user-selected width/height exactly fixed.
                                affine, inliers = cv2.estimateAffinePartial2D(
                                    source, dest, method=cv2.RANSAC,
                                    ransacReprojThreshold=4)
                                if affine is not None and inliers is not None and inliers.mean() >= 0.50:
                                    kept = inliers.ravel().astype(bool)
                                    displacement = dest[kept] - source[kept]
                                    if len(displacement) >= 4:
                                        dx, dy = np.median(displacement, axis=0)
                                        # Reject implausible jumps rather than silently
                                        # following a different object.
                                        if (np.isfinite(dx) and np.isfinite(dy)
                                                and abs(dx) <= max(20, w * 0.45)
                                                and abs(dy) <= max(20, h * 0.45)):
                                            bx = round(x + float(dx))
                                            by = round(y + float(dy))
                                            if 0 <= bx <= 1280 - w and 0 <= by <= 720 - h:
                                                bounds = (bx, by, w, h)
            if bounds is None:
                # Recover using a nearby patch when distinctive corners disappear.
                margin = max(32, round(max(w,h)*0.7))
                left = max(0, x-margin)
                top = max(0, y-margin)
                right = min(1280, x+w+margin)
                bottom = min(720, y+h+margin)
                search = current[top:bottom, left:right]
                if (reference.shape[0] >= 12 and reference.shape[1] >= 12
                        and search.shape[0] >= reference.shape[0]
                        and search.shape[1] >= reference.shape[1]
                        and float(reference.std()) >= 5):
                    result = cv2.matchTemplate(search, reference, cv2.TM_CCOEFF_NORMED)
                    _, confidence, _, position = cv2.minMaxLoc(result)
                    if math.isfinite(confidence) and confidence >= 0.60:
                        bounds = (left+position[0], top+position[1], w, h)
                        fallback_frames += 1
                if bounds is None:
                    warning = (
                        "Unable to confidently follow the selected pixels. "
                        "Try a larger or more textured box, or split the interval."
                    )
                    break
            x,y,w,h = bounds
            # Safety invariant: motion tracking may move a box, never resize it.
            w,h = fixed_width,fixed_height
            previous = current
            points = get_features(previous, bounds)
            patch = sample_template(previous, bounds)
            if patch.shape == reference.shape:
                reference = cv2.addWeighted(reference, 0.90, patch, 0.10, 0)
            else:
                reference = patch
            time = round(index/fps - clip_start, 4)
            frames.append({"t":time,"x":x/1280,"y":y/720,"w":w/1280,"h":h/720})

        complete = not warning and index >= end_frame
        if complete:
            # Position from the final decoded frame holds until the requested
            # end timestamp, which might fall between physical video frames.
            final_time = round(float(until_time), 4)
            if final_time > frames[-1]["t"]:
                frames.append({**frames[-1], "t":final_time})
        last = frames[-1]["t"]
        if not complete and not warning:
            warning = "Tracking did not reach the requested end."
        return {
            "keyframes":frames,
            "tracked_until":last,
            "complete":complete,
            "fallback_frames":fallback_frames,
            "size_mode":"fixed",
            "warning": (
                f"{warning} Tracking stopped at {last:.2f}s of {until_time:.2f}s. "
                "The uncovered frames need manual correction."
                if not complete else
                f"Tracking reached {until_time:.2f}s. Used template recovery "
                f"on {fallback_frames} step(s). Inspect the rendered video."
            )
        }
    finally:
        cap.release()


def render_advanced(clips: list[dict], temp: Path, ffmpeg_binary: str) -> None:
    """Render motion-tracked solid censor masks; remove all audio."""
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

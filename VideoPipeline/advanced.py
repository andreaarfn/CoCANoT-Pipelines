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


def _subject_aware_blur(frame, region, cv2):
    """GrabCut foreground separation from a user-selected subject rectangle.

    On failure, blur the entire frame instead of leaving a potentially
    identifying background unredacted. This is not privacy certification.
    """
    import numpy as np
    height, width = frame.shape[:2]
    preview_width = 480
    preview_height = max(1, round(height * preview_width / width))
    small = cv2.resize(frame, (preview_width, preview_height))
    x, y, w, h = region
    sx, sy = preview_width / width, preview_height / height
    rx = max(1, min(preview_width - 4, round(x * sx)))
    ry = max(1, min(preview_height - 4, round(y * sy)))
    rw = max(3, min(preview_width - rx - 1, round(w * sx)))
    rh = max(3, min(preview_height - ry - 1, round(h * sy)))
    blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=26)
    try:
        labels = np.zeros((preview_height, preview_width), np.uint8)
        background_model = np.zeros((1, 65), np.float64)
        foreground_model = np.zeros((1, 65), np.float64)
        cv2.grabCut(small, labels, (rx, ry, rw, rh), background_model,
                    foreground_model, 2, cv2.GC_INIT_WITH_RECT)
        foreground = np.isin(labels, [cv2.GC_FGD, cv2.GC_PR_FGD]).astype("float32")
        foreground = cv2.resize(foreground, (width, height), interpolation=cv2.INTER_LINEAR)
        foreground = cv2.GaussianBlur(foreground, (0, 0), sigmaX=3)
        alpha = np.clip(foreground, 0, 1)[:, :, None]
        return np.clip(frame * alpha + blurred * (1 - alpha), 0, 255).astype("uint8")
    except cv2.error:
        return blurred


def apply_polygon_background_blur(frame, polygons, cv2, feather=9, sigma=24):
    """Preserve user-selected polygon subjects; blur all pixels outside.

    Polygon vertices use 0..1 coordinates on the normalized 1280x720 frame.
    Multiple polygons preserve multiple separate people or objects. A missing
    or invalid selection fails loudly rather than exporting unblurred footage.
    """
    import numpy as np
    if not isinstance(polygons, list) or not polygons:
        raise ValueError("Draw at least one subject outline before exporting polygon blur.")
    height, width = frame.shape[:2]
    keep = np.zeros((height, width), dtype=np.uint8)
    for polygon in polygons:
        vertices = polygon.get("points", [])
        if len(vertices) < 3:
            raise ValueError("Each preserved-area mask requires at least three points.")
        coords = np.array([
            [round(float(p["x"]) * (width - 1)), round(float(p["y"]) * (height - 1))]
            for p in vertices
        ], dtype=np.int32)
        cv2.fillPoly(keep, [coords], 255)
    # A soft boundary avoids hard cutout artifacts but cannot certify privacy.
    keep = cv2.GaussianBlur(keep, (0, 0), sigmaX=max(0.1, feather))
    alpha = (keep.astype(np.float32) / 255.0)[:, :, None]
    blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=max(1.0, sigma))
    return np.clip(frame.astype(np.float32) * alpha +
                   blurred.astype(np.float32) * (1 - alpha), 0, 255).astype(np.uint8)


class PersonBackgroundSegmenter:
    """Local MediaPipe person/background segmentation for a Zoom-style blur."""

    def __init__(self):
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise RuntimeError(
                "Person-aware blur requires MediaPipe. Install with: python -m pip install mediapipe"
            ) from exc
        import os
        from pathlib import Path
        model = Path(os.environ.get(
            "COCANOT_PERSON_SEGMENTATION_MODEL",
            str(Path.home() / ".cocanot" / "models" / "selfie_segmenter.tflite")
        )).expanduser()
        if not model.is_file():
            raise RuntimeError(
                "Person segmentation model missing. Download MediaPipe Selfie Segmenter "
                f"to {model}. No patient video is uploaded."
            )
        self.mp = mp
        self.segmenter = mp.tasks.vision.ImageSegmenter.create_from_options(
            mp.tasks.vision.ImageSegmenterOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                output_confidence_masks=True,
                output_category_mask=False,
            )
        )
        self.timestamp = -1
        self.smooth_mask = None

    def apply(self, frame, cv2, time_seconds):
        import numpy as np
        image = self.mp.Image(
            image_format=self.mp.ImageFormat.SRGB,
            data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        )
        timestamp = max(self.timestamp + 1, round(time_seconds * 1000))
        self.timestamp = timestamp
        result = self.segmenter.segment_for_video(image, timestamp)
        if len(result.confidence_masks or []) < 2:
            # Fail closed: if no person mask is returned, blur the full frame.
            return cv2.GaussianBlur(frame, (0, 0), sigmaX=28)
        confidence = result.confidence_masks[1].numpy_view().astype(np.float32)
        confidence = cv2.resize(confidence, (frame.shape[1], frame.shape[0]))
        # Temporal smoothing reduces visible flicker at edges.
        if self.smooth_mask is None:
            self.smooth_mask = confidence
        else:
            self.smooth_mask = self.smooth_mask * 0.45 + confidence * 0.55
        alpha = np.clip((self.smooth_mask - 0.30) / 0.40, 0, 1)
        alpha = cv2.GaussianBlur(alpha, (0, 0), sigmaX=2.5)[:, :, None]
        blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=28)
        return np.clip(frame * alpha + blurred * (1-alpha), 0, 255).astype(np.uint8)

    def close(self):
        self.segmenter.close()


def render_advanced(clips: list[dict], temp: Path, ffmpeg_binary: str) -> None:
    """Render with moving masks and background blur; video audio is removed."""
    cv2 = _cv2()
    command = [ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1280x720", "-r", "30",
               "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temp)]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    person_segmenter = None
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
                        # Apply the selected method without assuming a rectangle.
                        if background.get("mode") == "polygon":
                            image = apply_polygon_background_blur(
                                image, background.get("polygons", []), cv2,
                                feather=background.get("feather", 9),
                                sigma=background.get("strength", 24))
                        elif background.get("mode") == "person":
                            if person_segmenter is None:
                                person_segmenter = PersonBackgroundSegmenter()
                            image = person_segmenter.apply(image, cv2, idx / 30)
                        elif background.get("mode") == "subject":
                            image = _subject_aware_blur(image, _rect(background), cv2)
                        else:
                            blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=24)
                            x, y, w, h = _rect(background)
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
                if person_segmenter is not None:
                    person_segmenter.close()
                    person_segmenter = None
        proc.stdin.close()
        message = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        result = proc.wait(timeout=600)
        if result:
            raise RuntimeError(f"FFmpeg encoding failed: {message[-1500:]}")
    except Exception:
        if person_segmenter is not None:
            person_segmenter.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        raise

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
    """Track visual features using Lucas-Kanade optical flow and RANSAC.

    Stop on ambiguous motion; never extrapolate a mask after tracking loss.
    """
    cv2 = _cv2()
    import numpy as np
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("Cannot open video for tracking.")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start_frame = max(0, round((clip_start + from_time) * fps))
        end_frame = min(round(clip_end * fps) - 1, start_frame + round(fps * 120))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        ok, frame = cap.read()
        if not ok:
            raise ValueError("Could not read selected starting frame.")
        previous = cv2.cvtColor(_canvas(frame, cv2), cv2.COLOR_BGR2GRAY)
        x, y, w, h = _rect(region)
        if min(w, h) < 18:
            raise ValueError("Please draw a larger tracking rectangle.")

        def features(gray, box):
            bx, by, bw, bh = box
            roi = np.zeros(gray.shape, np.uint8)
            margin = max(2, min(bw, bh) // 12)
            roi[by+margin:by+bh-margin, bx+margin:bx+bw-margin] = 255
            return cv2.goodFeaturesToTrack(gray, 120, 0.012, 5, mask=roi)

        points = features(previous, (x, y, w, h))
        if points is None or len(points) < 7:
            raise ValueError("Not enough distinctive pixels. Draw the box around a more textured object.")
        frames = [{"t": round(from_time, 4), "x": x/1280, "y": y/720, "w": w/1280, "h": h/720}]
        stride = max(1, round(fps / 10))
        index = start_frame
        warning = ""
        while index + stride <= end_frame:
            for _ in range(stride - 1):
                if not cap.grab():
                    warning = "Video decoding ended."
                    break
            if warning:
                break
            ok, frame = cap.read()
            if not ok:
                warning = "Video decoding ended."
                break
            index += stride
            current = cv2.cvtColor(_canvas(frame, cv2), cv2.COLOR_BGR2GRAY)
            next_points, status, _ = cv2.calcOpticalFlowPyrLK(
                previous, current, points, None, winSize=(23, 23), maxLevel=3)
            if next_points is None:
                warning = "Object features disappeared."
                break
            good = status.ravel() == 1
            source = points.reshape(-1, 2)[good]
            dest = next_points.reshape(-1, 2)[good]
            if len(source) < 7:
                warning = "Too few tracked pixels."
                break
            reverse, rev_status, _ = cv2.calcOpticalFlowPyrLK(
                current, previous, dest.astype("float32").reshape(-1,1,2), None)
            if reverse is None:
                warning = "Tracking confidence dropped."
                break
            error = np.linalg.norm(source - reverse.reshape(-1,2), axis=1)
            passed = (rev_status.ravel() == 1) & (error < 2.5)
            source, dest = source[passed], dest[passed]
            if len(source) < 7:
                warning = "Tracked pixels failed consistency checks."
                break
            affine, inliers = cv2.estimateAffinePartial2D(
                source, dest, method=cv2.RANSAC, ransacReprojThreshold=3)
            if affine is None or inliers is None or inliers.mean() < 0.55:
                warning = "Movement was ambiguous."
                break
            scale = math.hypot(float(affine[0,0]), float(affine[0,1]))
            if not 0.8 <= scale <= 1.25:
                warning = "Object resized too quickly."
                break
            corners = np.float32([[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
            transformed = cv2.transform(corners[None,:,:], affine)[0]
            low = transformed.min(axis=0)
            high = transformed.max(axis=0)
            nx, ny = map(float, low)
            nw, nh = map(float, high-low)
            if nx < 0 or ny < 0 or nx+nw >= 1280 or ny+nh >= 720 or min(nw,nh) < 18:
                warning = "Tracked object reached the frame edge."
                break
            x,y,w,h = round(nx),round(ny),round(nw),round(nh)
            previous = current
            points = features(previous, (x,y,w,h))
            if points is None or len(points) < 7:
                warning = "Tracking region lost detail."
                break
            t = index/fps-clip_start
            frames.append({"t":round(t,4),"x":x/1280,"y":y/720,"w":w/1280,"h":h/720})
        complete = not warning and end_frame >= round(clip_end*fps)-stride-1
        if not complete and not warning:
            warning = "120-second tracking limit reached."
        last = frames[-1]["t"]
        return {"keyframes":frames,"tracked_until":last,"complete":complete,
                "warning": (f"{warning} Tracking ended at {last:.2f}s. Inspect and retrack any uncovered frames."
                            if not complete else "Tracking completed. Review the rendered video frame by frame.")}
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
                        preserve = _rect(background)
                        # Strong but not irreversible background blur.
                        if background.get("mode") == "person":
                            if person_segmenter is None:
                                person_segmenter = PersonBackgroundSegmenter()
                            image = person_segmenter.apply(image, cv2, idx / 30)
                        elif background.get("mode") == "subject":
                            image = _subject_aware_blur(image, preserve, cv2)
                        else:
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

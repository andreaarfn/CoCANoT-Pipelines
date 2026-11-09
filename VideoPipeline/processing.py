"""Local, non-destructive FFmpeg video processing for CoCANoT.

Project edits are kept in JSON; source media are never modified.
This initial implementation supports clip ordering, trimming, and opaque
rectangle redaction. Exported videos must be visually reviewed.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
MAX_PROJECT_BYTES = 8 * 1024 * 1024


def _binary(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} is required for video processing. Install FFmpeg and ensure {name} is on PATH.")
    return found


def inspect_video(path: str) -> dict:
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("Choose a supported video file (MP4, MOV, MKV, AVI, WebM, M4V).")
    command = [_binary("ffprobe"), "-v", "error", "-show_streams",
               "-show_format", "-of", "json", str(source)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=True)
    data = json.loads(result.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise ValueError("No video stream found.")
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Video duration is unavailable.")
    return {"path": str(source), "name": source.name, "duration": duration,
            "width": int(video.get("width") or 0), "height": int(video.get("height") or 0),
            "audio": any(s.get("codec_type") == "audio" for s in data.get("streams", []))}


def _validate_box(region: dict) -> None:
    values = [float(region.get(k, 0)) for k in ("x", "y", "w", "h")]
    if (not all(map(math.isfinite, values)) or values[0] < 0 or values[1] < 0
            or values[2] <= 0 or values[3] <= 0 or values[0]+values[2] > 1.001
            or values[1]+values[3] > 1.001):
        raise ValueError("Region geometry must fit within the video frame.")


def validate_project(project: dict) -> list[dict]:
    clips = project.get("clips")
    if not isinstance(clips, list) or not clips or len(clips) > 1000:
        raise ValueError("Project requires between 1 and 1000 clips.")
    output = []
    for clip in clips:
        media = inspect_video(clip.get("path", ""))
        start = float(clip.get("start", 0))
        end = float(clip.get("end", media["duration"]))
        if not all(map(math.isfinite, (start, end))) or start < 0 or end <= start or end > media["duration"] + 0.01:
            raise ValueError(f"Invalid clip trim boundaries: {media['name']}")
        masks = clip.get("masks", [])
        if not isinstance(masks, list) or len(masks) > 500:
            raise ValueError("Invalid redaction regions.")
        for mask in masks:
            if mask.get("type", "solid") != "solid":
                raise ValueError("Only opaque black censoring is supported by the current export engine.")
            nums = [float(mask.get(k, 0)) for k in ("x", "y", "w", "h")]
            if not all(map(math.isfinite, nums)) or nums[0] < 0 or nums[1] < 0 or nums[2] <= 0 or nums[3] <= 0 or nums[0] + nums[2] > 1.001 or nums[1] + nums[3] > 1.001:
                raise ValueError("Mask geometry must be normalized to the video frame.")
            a = float(mask.get("start", 0))
            b = float(mask.get("end", end - start))
            if not all(map(math.isfinite, (a, b))) or a < 0 or b <= a:
                raise ValueError("Invalid mask time interval.")
        background = clip.get("background_blur")
        if background and background.get("enabled"):
            mode = background.get("mode", "rectangle")
            if mode not in ("rectangle", "subject", "person", "polygon"):
                raise ValueError("Unsupported background blur mode.")
            if mode == "polygon":
                polygons = background.get("polygons")
                if not isinstance(polygons, list) or not (1 <= len(polygons) <= 30):
                    raise ValueError("Draw at least one subject outline to preserve for background blur.")
                for polygon in polygons:
                    points = polygon.get("points") if isinstance(polygon, dict) else None
                    if not isinstance(points, list) or not (3 <= len(points) <= 100):
                        raise ValueError("Each subject outline needs 3 to 100 points.")
                    for point in points:
                        if not isinstance(point, dict):
                            raise ValueError("Invalid polygon vertex.")
                        x, y = float(point.get("x", -1)), float(point.get("y", -1))
                        if not math.isfinite(x) or not math.isfinite(y) or not (0 <= x <= 1 and 0 <= y <= 1):
                            raise ValueError("Preserved-area vertices must be inside the video frame.")
                for prop, lower, upper in (("feather", 0, 50), ("strength", 1, 70)):
                    val = float(background.get(prop, 9 if prop == "feather" else 24))
                    if not math.isfinite(val) or not lower <= val <= upper:
                        raise ValueError(f"Invalid polygon blur {prop} setting.")
            else:
                _validate_box(background)
        for mask in masks:
            points = mask.get("keyframes", [])
            if points:
                if not isinstance(points, list) or len(points) > 20000:
                    raise ValueError("Invalid tracking keyframes.")
                previous = -1
                for point in points:
                    _validate_box(point)
                    t = float(point["t"])
                    if not math.isfinite(t) or t <= previous or t < 0 or t > end-start + 0.5:
                        raise ValueError("Invalid tracking keyframe timestamp.")
                    previous = t
                if float(mask.get("tracked_until", -1)) + 0.3 < float(mask.get("end", end-start)):
                    raise ValueError("Tracking doesn't cover the mask's full interval. Review and shorten it or retrack before export.")
        output.append({**clip, "media": media, "start": start, "end": end})
    return output


def render_project(project: dict, destination: str) -> dict:
    clips = validate_project(project)
    target = Path(destination).expanduser().resolve()
    if target.suffix.lower() != ".mp4":
        raise ValueError("Export destination must have .mp4 extension.")
    if any(target == Path(c["media"]["path"]) for c in clips):
        raise ValueError("Export may not overwrite source footage.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.stem + ".partial.mp4")
    if temp.exists():
        raise FileExistsError(f"Temporary export already exists: {temp}")
    if any(c.get("background_blur", {}).get("enabled") or any(m.get("keyframes") for m in c.get("masks", [])) for c in clips):
        from VideoPipeline.advanced import render_advanced
        try:
            render_advanced(clips, temp, _binary("ffmpeg"))
            temp.replace(target)
        finally:
            if temp.exists():
                temp.unlink()
        return {"path": str(target), "duration": sum(c["end"] - c["start"] for c in clips),
                "note": "Moving masks/background blur applied. Audio removed. Human privacy review required."}
    command = [_binary("ffmpeg"), "-hide_banner", "-nostdin", "-y"]
    for clip in clips:
        command += ["-ss", str(clip["start"]), "-t", str(clip["end"] - clip["start"]), "-i", clip["media"]["path"]]
    graph = []
    for index, clip in enumerate(clips):
        label = f"v{index}"
        chain = f"[{index}:v:0]setpts=PTS-STARTPTS,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p"
        # Mask coordinates refer to the displayed output canvas.
        for mask in clip.get("masks", []):
            x = max(0, min(1279, round(float(mask["x"]) * 1280)))
            y = max(0, min(719, round(float(mask["y"]) * 720)))
            w = max(1, min(1280 - x, round(float(mask["w"]) * 1280)))
            h = max(1, min(720 - y, round(float(mask["h"]) * 720)))
            a = max(0.0, float(mask.get("start", 0)))
            b = min(clip["end"] - clip["start"], float(mask.get("end", clip["end"] - clip["start"])))
            if b > a:
                chain += f",drawbox=x={x}:y={y}:w={w}:h={h}:color=black:t=fill:enable='between(t,{a:.6f},{b:.6f})'"
        graph.append(chain + f"[{label}]")
    if len(clips) > 1:
        graph.append("".join(f"[v{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0[outv]")
    else:
        graph.append("[v0]null[outv]")
    command += ["-filter_complex", ";".join(graph), "-map", "[outv]", "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-movflags", "+faststart", str(temp)]
    try:
        finished = subprocess.run(command, capture_output=True, text=True, timeout=7200)
        if finished.returncode != 0:
            raise RuntimeError((finished.stderr or "FFmpeg export failed.")[-2500:])
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()
    return {"path": str(target), "duration": sum(c["end"] - c["start"] for c in clips),
            "note": "Audio intentionally removed. Human privacy review required before sharing."}


def save_project(project: dict, path: str) -> str:
    validate_project(project)
    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != ".json":
        raise ValueError("Project file must be JSON.")
    payload = json.dumps({"schema_version": 1, **project}, indent=2)
    if len(payload.encode("utf-8")) > MAX_PROJECT_BYTES:
        raise ValueError("Project exceeds size limit.")
    target.write_text(payload, encoding="utf-8")
    return str(target)


def load_project(path: str) -> dict:
    source = Path(path).expanduser().resolve(strict=True)
    if source.suffix.lower() != ".json" or source.stat().st_size > MAX_PROJECT_BYTES:
        raise ValueError("Invalid project file.")
    project = json.loads(source.read_text(encoding="utf-8"))
    if project.get("schema_version") != 1:
        raise ValueError("Unsupported video project version.")
    validate_project(project)
    return project

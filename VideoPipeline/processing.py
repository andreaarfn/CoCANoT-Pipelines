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
        if not isinstance(clip.get("remove_audio", False), bool):
            raise ValueError("Remove audio must be a checkbox setting.")
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
        output.append({**{k:v for k,v in clip.items() if k != "background_blur"}, "media": media, "start": start, "end": end})
    return output



def _mux_selected_audio(clips: list[dict], silent_video: Path, ffmpeg_binary: str) -> None:
    """Preserve source audio unless explicitly removed for a clip.

    Silence fills muted clips and sources without audio, keeping audio segments
    aligned with the final trimmed video sequence.
    """
    if not any(c["media"]["audio"] and not c.get("remove_audio", False) for c in clips):
        return

    output = silent_video.with_name(silent_video.stem + ".audio.mp4")
    if output.exists():
        raise FileExistsError(f"Temporary audio export already exists: {output}")
    command = [ffmpeg_binary, "-hide_banner", "-nostdin", "-y", "-i", str(silent_video)]
    chains = []
    for index, clip in enumerate(clips):
        length = clip["end"] - clip["start"]
        if clip["media"]["audio"] and not clip.get("remove_audio", False):
            command += ["-i", clip["media"]["path"]]
            source = f"[{index + 1}:a:0]atrim=start={clip['start']:.6f}:end={clip['end']:.6f},asetpts=PTS-STARTPTS"
        else:
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            source = f"[{index + 1}:a:0]asetpts=PTS-STARTPTS"
        chains.append(
            f"{source},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad,atrim=duration={length:.6f},asetpts=PTS-STARTPTS[a{index}]"
        )
    if len(clips) > 1:
        chains.append(
            "".join(f"[a{i}]" for i in range(len(clips)))
            + f"concat=n={len(clips)}:v=0:a=1[outa]"
        )
    else:
        chains.append("[a0]anull[outa]")
    command += [
        "-filter_complex", ";".join(chains), "-map", "0:v:0", "-map", "[outa]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(output),
    ]
    try:
        finished = subprocess.run(command, capture_output=True, text=True, timeout=7200)
        if finished.returncode != 0:
            raise RuntimeError((finished.stderr or "Audio export failed.")[-2500:])
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("Audio export did not produce a valid MP4.")
        output.replace(silent_video)
    finally:
        if output.exists():
            output.unlink()


def validate_video_annotations(annotations: list, duration: float) -> list[dict]:
    """Validate structured events against final exported-video time (seconds)."""
    if not isinstance(annotations, list) or len(annotations) > 2000:
        raise ValueError("Video annotations must be a list of at most 2000 events.")
    if not math.isfinite(float(duration)) or duration < 0:
        raise ValueError("Final video duration is invalid.")
    clean = []
    seen = set()
    for index, item in enumerate(annotations):
        if not isinstance(item, dict):
            raise ValueError(f"Annotation {index + 1} must be an object.")
        try:
            onset = float(item["onset"])
            length = float(item["duration"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Annotation {index + 1}: onset and duration must be numbers.") from exc
        description = str(item.get("description") or "").strip()
        if not all(math.isfinite(v) for v in (onset, length)):
            raise ValueError(f"Annotation {index + 1}: timestamps must be finite.")
        if onset < 0 or length < 0 or onset + length > duration + 0.02:
            raise ValueError(f"Annotation {index + 1}: interval exceeds the final video duration.")
        if not description or len(description) > 500:
            raise ValueError(f"Annotation {index + 1}: add a description of 1–500 characters without PHI.")
        identifier = str(item.get("id") or f"event-{index + 1}").strip()
        if not identifier or len(identifier) > 100 or identifier in seen:
            raise ValueError(f"Annotation {index + 1}: event identifier is invalid or duplicated.")
        seen.add(identifier)
        clean.append({"id": identifier, "onset": onset, "duration": length,
                      "description": description})
    return sorted(clean, key=lambda row: (row["onset"], row["id"]))


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
    if any(any(m.get("keyframes") for m in c.get("masks", [])) for c in clips):
        from VideoPipeline.advanced import render_advanced
        try:
            ffmpeg = _binary("ffmpeg")
            render_advanced(clips, temp, ffmpeg)
            _mux_selected_audio(clips, temp, ffmpeg)
            temp.replace(target)
        finally:
            if temp.exists():
                temp.unlink()
        return {"path": str(target), "duration": sum(c["end"] - c["start"] for c in clips),
                "note": "Moving censor masks applied. Audio follows clip settings. Human privacy review required."}
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
        _mux_selected_audio(clips, temp, _binary("ffmpeg"))
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()
    return {"path": str(target), "duration": sum(c["end"] - c["start"] for c in clips),
            "note": "Audio follows clip settings. Human privacy review required before sharing."}


def save_project(project: dict, path: str) -> str:
    validate_project(project)
    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != ".json":
        raise ValueError("Project file must be JSON.")
    clean = {**project, "clips": [{k: v for k, v in clip.items() if k != "background_blur"} for clip in project["clips"]]}
    payload = json.dumps({"schema_version": 1, **clean}, indent=2)
    if len(payload.encode("utf-8")) > MAX_PROJECT_BYTES:
        raise ValueError("Project exceeds size limit.")
    target.write_text(payload, encoding="utf-8")
    return str(target)


def load_project(path: str, resolve_clip_path=None) -> dict:
    source = Path(path).expanduser().resolve(strict=True)
    if source.suffix.lower() != ".json" or source.stat().st_size > MAX_PROJECT_BYTES:
        raise ValueError("Invalid project file.")
    project = json.loads(source.read_text(encoding="utf-8"))
    if project.get("schema_version") != 1:
        raise ValueError("Unsupported video project version.")
    if resolve_clip_path is not None:
        project["clips"] = [
            {**clip, "path": resolve_clip_path(clip.get("path", ""))}
            for clip in project.get("clips", []) if isinstance(clip, dict)
        ]
    validate_project(project)
    return {**project, "clips": [{k: v for k, v in clip.items() if k != "background_blur"} for clip in project["clips"]]}

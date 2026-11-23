"""Non-destructive local checks for potential video frame/segment discontinuities.

A gap in decoded presentation timestamps is evidence of discontinuous timing,
NOT proof that source video was dropped. Missing footage with rewritten
timestamps cannot be inferred without an independent clock/reference stream.
"""
from __future__ import annotations

import math
import statistics
import subprocess

from VideoPipeline.processing import _binary, inspect_video

MAX_FLAGS = 200
MAX_PROBE_SECONDS = 240
MAX_DECODE_SECONDS = 300


def analyze_timestamps(timestamps: list[float], start: float, end: float) -> dict:
    """Identify unusually large frame-to-frame presentation timestamp gaps."""
    selected = [t for t in timestamps if math.isfinite(t) and start - 0.001 <= t <= end + .001]
    positive = [b-a for a, b in zip(selected, selected[1:]) if 0 < b-a <= 5.]
    if len(positive) < 2:
        return {
            "frame_count": len(selected), "typical_interval": None,
            "events": [], "quality": "insufficient",
            "note": "Too few usable frame timestamps to evaluate continuity."
        }
    typical = statistics.median(positive)
    # Only flag gaps >= 2.5 expected frames AND >= 0.12 seconds;
    # this is an exploratory screen, not a missing-frame certification.
    cutoff = max(.12, typical * 2.5)
    events = []
    for a, b in zip(selected, selected[1:]):
        gap = b-a
        if gap > cutoff:
            events.append({
                "kind": "timestamp_gap",
                "start": round(max(0., a-start), 3),
                "end": round(min(end-start, b-start), 3),
                "gap_seconds": round(gap, 3),
                "expected_frame_interval": round(typical, 4),
                "detail": "Presentation timestamp jump. Possible missing frames, paused recording, variable frame rate, or timestamp irregularity."
            })
        if len(events) >= MAX_FLAGS:
            break
    # VFR often has varying frame spacing. Keep events visible but warn.
    variability = sum(d > typical * 1.6 or d < typical * .5 for d in positive) / len(positive)
    return {
        "frame_count": len(selected),
        "typical_interval": round(typical, 5),
        "events": events, "quality": "variable" if variability > .15 else "regular",
        "note": ("Frame timing varies considerably; flagged gaps may be normal variable-frame-rate behavior."
                 if variability > .15 else "Frame timing appears reasonably regular between recorded timestamps.")
    }


def check_video_continuity(path: str, start: float, end: float) -> dict:
    """Read presentation timestamps and attempt full decoding; do not modify source."""
    media = inspect_video(path)
    duration = float(media["duration"])
    if not all(map(math.isfinite, (start, end))) or start < 0 or end <= start or end > duration + .01:
        raise ValueError("Select valid clip boundaries before checking video continuity.")

    command = [_binary("ffprobe"), "-v", "error", "-select_streams", "v:0",
               "-show_entries", "frame=best_effort_timestamp_time",
               "-of", "csv=p=0", media["path"]]
    try:
        probe = subprocess.run(command, capture_output=True, text=True,
                               timeout=MAX_PROBE_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Frame timestamp inspection timed out. Try a shorter recording.") from exc
    if probe.returncode:
        raise RuntimeError("FFprobe could not inspect video frame timestamps.")

    timestamps = []
    for line in probe.stdout.splitlines():
        value = line.split(",", 1)[0].strip()
        try:
            number = float(value)
        except ValueError:
            continue
        if math.isfinite(number):
            timestamps.append(number)
    inspected = analyze_timestamps(timestamps, start, end)
    # Independent full decode check catches corruption not reflected in PTS.
    decode = [_binary("ffmpeg"), "-hide_banner", "-loglevel", "error",
              "-nostdin", "-i", media["path"], "-map", "0:v:0", "-an",
              "-f", "null", "-"]
    try:
        decoded = subprocess.run(decode, capture_output=True, text=True,
                                 timeout=MAX_DECODE_SECONDS, check=False)
        decode_warning = decoded.returncode != 0 or bool(decoded.stderr.strip())
    except subprocess.TimeoutExpired:
        decode_warning = True
        decoded = None

    flags = list(inspected["events"])
    if decode_warning:
        flags.append({
            "kind": "decode_warning", "start": None, "end": None,
            "detail": "FFmpeg reported a decoding problem or timed out. Review the original recording and technical logs."
        })
    return {
        "status": "attention" if flags else ("inconclusive" if inspected["quality"] == "insufficient" else "no_flags"),
        "frame_count": inspected["frame_count"],
        "typical_interval": inspected["typical_interval"],
        "timing_quality": inspected["quality"],
        "events": flags,
        "truncated": len(inspected["events"]) >= MAX_FLAGS,
        "note": inspected["note"],
        "limitations": (
            "This checks timestamps and decoding only. It cannot establish that footage was "
            "never dropped, detect removed frames with rewritten timestamps, or validate "
            "synchronization with Natus neural data without independent references."
        ),
    }

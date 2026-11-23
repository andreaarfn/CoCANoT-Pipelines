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


# Return bounded raw evidence to the dashboard, and preserve the largest
# interval in each plotted time bin so brief spikes remain visible.
MAX_RAW_INTERVALS = 20000
MAX_CHART_POINTS = 360
ALGORITHM_VERSION = "continuity-timing-v2"


def _chart_intervals(intervals: list[dict]) -> list[dict]:
    if len(intervals) <= MAX_CHART_POINTS:
        return [{"t": row["t"], "ms": row["delta_ms"]} for row in intervals]
    chunk = math.ceil(len(intervals) / MAX_CHART_POINTS)
    return [
        {"t": item["t"], "ms": item["delta_ms"]}
        for offset in range(0, len(intervals), chunk)
        for item in [max(intervals[offset:offset+chunk],
                         key=lambda row: abs(row["delta_ms"]))]
    ]


def analyze_timestamps(timestamps: list[float], start: float, end: float) -> dict:
    """Measure frame PTS differences and flag timestamp discontinuities.

    Results are screening evidence; a timestamp anomaly is not a confirmed
    missing segment. Frame times are analyzed in the order FFprobe reports them.
    """
    selected = [t for t in timestamps
                if math.isfinite(t) and start - .001 <= t <= end + .001]
    intervals = [
        {"t": round(b-start, 5), "from": round(a-start, 5),
         "to": round(b-start, 5), "delta_ms": round((b-a)*1000, 4)}
        for a, b in zip(selected, selected[1:])
    ]
    positive = [row["delta_ms"]/1000 for row in intervals
                if 0 < row["delta_ms"] <= 5000]
    base = {
        "frame_count": len(selected),
        "interval_count": len(intervals),
        "intervals": intervals[:MAX_RAW_INTERVALS],
        "intervals_truncated": len(intervals) > MAX_RAW_INTERVALS,
        "chart": _chart_intervals(intervals),
        "typical_interval": None,
        "median_interval_ms": None,
        "p95_interval_ms": None,
        "max_interval_ms": round(max((row["delta_ms"] for row in intervals), default=0), 3),
        "threshold_ms": None,
        "algorithm_version": ALGORITHM_VERSION,
        "events": [], "event_count": 0, "events_truncated": False,
        "quality": "insufficient",
        "note": "Too few usable frame timestamps to evaluate continuity.",
    }
    if len(positive) < 2:
        return base
    typical = statistics.median(positive)
    ordered = sorted(positive)
    p95 = ordered[math.ceil(.95 * len(ordered))-1]
    threshold = max(.12, typical * 2.5)
    events = []
    for row in intervals:
        delta = row["delta_ms"] / 1000.
        if delta > threshold:
            # Only approximate: variable frame rate may make this meaningless.
            estimated_missing = max(0, round(delta / typical) - 1)
            events.append({
                "kind": "timestamp_gap",
                "start": round(max(0., row["from"]), 3),
                "end": round(min(end-start, row["to"]), 3),
                "gap_seconds": round(delta, 5),
                "expected_frame_interval": round(typical, 5),
                "estimated_missing_intervals": estimated_missing,
                "detail": ("Presentation timestamp jump. This may reflect missing "
                           "frames, pauses, variable frame rate or timestamp irregularity."),
            })
        elif delta <= 0:
            events.append({
                "kind": "nonincreasing_timestamp",
                "start": round(max(0., row["from"]), 3),
                "end": round(min(end-start, row["to"]), 3),
                "gap_seconds": round(delta, 5),
                "detail": "Repeated or reversed presentation timestamp; investigate clock/stream timing.",
            })
    variability = sum(d > typical*1.6 or d < typical*.5 for d in positive) / len(positive)
    base.update({
        "typical_interval": round(typical, 6),
        "median_interval_ms": round(1000*typical, 3),
        "p95_interval_ms": round(1000*p95, 3),
        "threshold_ms": round(1000*threshold, 3),
        "events": events[:MAX_FLAGS],
        "event_count": len(events),
        "events_truncated": len(events) > MAX_FLAGS,
        "quality": "variable" if variability > .15 else "regular",
        "note": ("Frame timing varies considerably; flagged gaps may be normal "
                 "variable-frame-rate behavior." if variability > .15 else
                 "Frame timing appears reasonably regular between recorded timestamps."),
    })
    return base


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
        "truncated": inspected["events_truncated"],
        "event_count": inspected["event_count"] + int(decode_warning),
        "raw_intervals": inspected["intervals"],
        "raw_intervals_truncated": inspected["intervals_truncated"],
        "interval_count": inspected["interval_count"],
        "interval_chart": inspected["chart"],
        "median_interval_ms": inspected["median_interval_ms"],
        "p95_interval_ms": inspected["p95_interval_ms"],
        "max_interval_ms": inspected["max_interval_ms"],
        "threshold_ms": inspected["threshold_ms"],
        "algorithm_version": inspected["algorithm_version"],
        "note": inspected["note"],
        "method": "FFprobe frame presentation timestamps + independent FFmpeg decode check",
        "decode_status": "warning" if decode_warning else "no_errors_observed",
        "threshold_rule": "Gap > max(120 ms, 2.5 x median positive frame interval)",
        "limitations": (
            "This checks timestamps and decoding only. It cannot establish that footage was "
            "never dropped, detect removed frames with rewritten timestamps, or validate "
            "synchronization with Natus neural data without independent references."
        ),
    }

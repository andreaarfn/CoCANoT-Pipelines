"""Recording-session video coverage from explicit acquisition-clock references.

This module never treats MP4 creation_time, filesystem mtime, or the order of
imported files as an acquisition timestamp. Only user-provided start times,
anchored to an independently checked source, can support coverage conclusions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

MIN_GAP_SECONDS = 0.05
MAX_SEGMENTS = 1000


def _instant(value: str | None, label: str) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO 8601 timestamp with an explicit timezone.")
    try:
        value = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone or UTC offset.")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def analyze_session_coverage(
    segments: list[dict],
    expected_start: str | None = None,
    expected_end: str | None = None,
) -> dict:
    """Merge timestamped clip intervals, find uncovered ranges and report unknowns.

    Explicit clip start timestamps are required. Clip duration refers to the
    trimmed portion, whose acquisition start is full-recording start + trim.
    Unreferenced clips are excluded from coverage arithmetic and reported.
    """
    if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS:
        raise ValueError("Provide 1–1000 video segments.")
    expected_a = _instant(expected_start, "Reference recording start")
    expected_b = _instant(expected_end, "Reference recording end")
    if (expected_a is None) != (expected_b is None):
        raise ValueError("Provide both reference start and end, or neither.")
    if expected_a is not None and expected_b <= expected_a:
        raise ValueError("Reference recording end must follow the start.")

    referenced, unreferenced = [], []
    for i, item in enumerate(segments):
        if not isinstance(item, dict):
            raise ValueError("Invalid video segment.")
        label = str(item.get("name") or f"Video {i+1}")[:160]
        duration = float(item.get("duration", 0))
        trim_start = float(item.get("trim_start", 0))
        trim_end = float(item.get("trim_end", duration))
        if not all(math.isfinite(v) for v in (duration, trim_start, trim_end)) or not (duration > 0 and 0 <= trim_start < trim_end <= duration + .01):
            raise ValueError(f"Invalid clip timing: {label}")
        clip_start = _instant(item.get("recording_start"), f"{label} acquisition start")
        if clip_start is None:
            unreferenced.append({"id": str(item.get("id") or i), "name": label, "reason": "No verified acquisition start time supplied."})
            continue
        from datetime import timedelta
        a = clip_start + timedelta(seconds=trim_start)
        b = clip_start + timedelta(seconds=trim_end)
        referenced.append({"id": str(item.get("id") or i), "name": label, "a": a, "b": b,
                           "start": _iso(a), "end": _iso(b),
                           "duration_seconds": round((b-a).total_seconds(), 3),
                           "source": "user-entered reference (not independently verified)"})
    referenced.sort(key=lambda r: (r["a"], r["b"]))
    merged = []
    for item in referenced:
        if not merged or item["a"] > merged[-1][1]:
            merged.append([item["a"], item["b"]])
        else:
            merged[-1][1] = max(merged[-1][1], item["b"])

    if expected_a is not None:
        window_a, window_b = expected_a, expected_b
    elif merged:
        window_a, window_b = merged[0][0], merged[-1][1]
    else:
        return {
            "status": "inconclusive", "events": [], "segments": [],
            "unreferenced": unreferenced, "reference_provided": False,
            "note": "No acquisition timestamp references were supplied.",
        }

    clipped = []
    for a, b in merged:
        a, b = max(a, window_a), min(b, window_b)
        if b > a:
            clipped.append((a, b))
    cursor = window_a
    events = []
    for a, b in clipped:
        if (a-cursor).total_seconds() > MIN_GAP_SECONDS:
            events.append({
                "kind": "coverage_gap",
                "start": _iso(cursor), "end": _iso(a),
                "duration_seconds": round((a-cursor).total_seconds(), 3),
                "location": ("leading" if cursor == window_a else "between_segments"),
            })
        cursor = max(cursor, b)
    if (window_b-cursor).total_seconds() > MIN_GAP_SECONDS:
        events.append({
            "kind": "coverage_gap",
            "start": _iso(cursor), "end": _iso(window_b),
            "duration_seconds": round((window_b-cursor).total_seconds(), 3),
            "location": "trailing" if expected_a else "between_segments",
        })
    total_seconds = (window_b-window_a).total_seconds()
    covered_seconds = sum((b-a).total_seconds() for a,b in clipped)
    incomplete = len(unreferenced) > 0 or not referenced
    return {
        "status": "inconclusive" if incomplete else ("attention" if events else "no_gaps_observed"),
        "events": events,
        "segments": [{k:v for k,v in row.items() if k not in ("a","b")} for row in referenced],
        "unreferenced": unreferenced,
        "reference_provided": expected_a is not None,
        "reference_start": _iso(window_a), "reference_end": _iso(window_b),
        "reference_duration_seconds": round(total_seconds,3),
        "covered_seconds": round(covered_seconds,3),
        "uncovered_seconds": round(max(0.,total_seconds-covered_seconds),3),
        "coverage_percent": round(100*covered_seconds/total_seconds,2) if total_seconds else None,
        "note": ("Incomplete: some video segments lack acquisition timestamps. "
                 "Coverage conclusions cannot be considered complete." if incomplete else
                 "Computed from manually supplied acquisition-clock references. "
                 "Cross-check against Natus logs; source times are not automatically authenticated."),
        "limitations": "No frame-content verification, clock synchronization or automatic Natus timestamp extraction. "
                       "MP4 creation_time and filesystem dates are deliberately not used as acquisition evidence.",
    }

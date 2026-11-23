"""End-to-end continuity smoke benchmark using synthetic encoded MP4 files.

Creates temporary, non-sensitive videos using FFmpeg; no patient files accessed.
This is a codec-path sanity check, not a validated Natus performance study.

Run: python -m VideoPipeline.benchmark_media_continuity
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from VideoPipeline.continuity import check_video_continuity
from VideoPipeline.processing import _binary, inspect_video


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("FFmpeg fixture generation failed: " + result.stderr[-1000:])


def run_media_benchmark() -> dict:
    ffmpeg = _binary("ffmpeg")
    scenarios = []
    with tempfile.TemporaryDirectory(prefix="cocanot-continuity-test-") as root:
        directory = Path(root)
        normal = directory / "normal.mp4"
        preserved = directory / "dropped_preserved_pts.mp4"
        rewritten = directory / "dropped_rewritten_pts.mp4"
        base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        _run(base + ["-f", "lavfi", "-i",
                      "testsrc2=size=320x180:rate=30:duration=8",
                      "-an", "-c:v", "mpeg4", "-q:v", "4", str(normal)])
        # Remove a known half-second of encoded source pictures without
        # closing the corresponding presentation-timestamp interval.
        selection = "select=not(between(n\\,90\\,104))"
        _run(base + ["-i", str(normal), "-vf", selection,
                      "-fps_mode", "vfr", "-an", "-c:v", "mpeg4",
                      "-q:v", "4", str(preserved)])
        # Exactly the same removal with reconstructed monotonic timestamps:
        # the algorithm should not claim to detect this loss.
        _run(base + ["-i", str(normal), "-vf",
                      selection + ",setpts=N/(30*TB)",
                      "-fps_mode", "vfr", "-an", "-c:v", "mpeg4",
                      "-q:v", "4", str(rewritten)])
        for name, path, expected in [
            ("normal_encoded_mp4", normal, False),
            ("15_removed_frames_preserved_pts", preserved, True),
            ("15_removed_frames_rewritten_pts", rewritten, False),
        ]:
            duration = inspect_video(str(path))["duration"]
            report = check_video_continuity(str(path), 0, duration)
            detected = any(e["kind"] == "timestamp_gap" for e in report["events"])
            scenarios.append({
                "scenario": name, "expected_timestamp_gap": expected,
                "gap_detected": detected, "passes_expected_behavior": detected == expected,
                "frames": report["frame_count"],
                "median_interval_ms": report["median_interval_ms"],
                "largest_interval_ms": report["max_interval_ms"],
                "flagged_events": report["event_count"],
            })
    return {
        "benchmark": "synthetic_encoded_mp4",
        "passed": sum(bool(r["passes_expected_behavior"]) for r in scenarios),
        "total": len(scenarios),
        "scenarios": scenarios,
        "limitations": "One synthetic MPEG-4 codec and FFmpeg-generated signals. "
                       "Rewritten timestamps conceal known removals. This is not clinical validation."
    }


def main():
    print(json.dumps(run_media_benchmark(), indent=2))


if __name__ == "__main__":
    main()

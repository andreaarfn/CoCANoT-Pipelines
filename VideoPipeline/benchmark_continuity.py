"""Deterministic synthetic PTS benchmark for the continuity screening algorithm.

Run from project root:
  python -m VideoPipeline.benchmark_continuity

The benchmark validates timestamp-gap detection only. It does NOT establish
performance on genuine recordings, image-content defects or Natus alignment.
"""
from __future__ import annotations

import json

from VideoPipeline.continuity import analyze_timestamps


def benchmark_cases(fps: int = 30, duration: int = 12) -> list[dict]:
    """Ground-truth fixtures with known injected timing abnormalities."""
    total = fps * duration
    base = [i / fps for i in range(total)]
    anchor = 4 * fps
    cases = [
        {"name": "normal_constant_rate", "times": base,
         "positive": False, "expected": None, "category": "normal"},
    ]
    for removed in (1, 2, 5, 10, 30):
        changed = [t for i, t in enumerate(base)
                   if not anchor <= i < anchor+removed]
        cases.append({"name": f"dropped_{removed}_frames_preserve_pts",
                      "times": changed, "positive": True,
                      "expected": (anchor-1) / fps, "category": "gap"})
    # Genuinely missing footage with timestamps reindexed hides the gap.
    dropped = [t for i, t in enumerate(base)
               if not anchor <= i < anchor+30]
    rewritten = [i / fps for i in range(len(dropped))]
    cases.append({"name": "dropped_30_frames_rewritten_pts",
                  "times": rewritten, "positive": True,
                  "expected": None, "category": "rewritten_pts"})
    # Variable, but continuous, frame durations are a negative control.
    variable = [0.]
    for i in range(1, total):
        variable.append(variable[-1] + (.022 if i % 2 else .044))
    cases.append({"name": "normal_variable_frame_rate",
                  "times": variable, "positive": False,
                  "expected": None, "category": "normal"})
    # A clock discontinuity is detectable, but not proof of lost images.
    jumped = [t + (0.8 if i >= anchor else 0.) for i, t in enumerate(base)]
    cases.append({"name": "timestamp_jump_without_dropped_frames",
                  "times": jumped, "positive": False,
                  "expected": None, "category": "timestamp_only"})
    # A backwards PTS regression is separately detectable.
    backwards = base.copy()
    backwards[anchor] = backwards[anchor-1]
    cases.append({"name": "repeated_presentation_timestamp",
                  "times": backwards, "positive": False,
                  "expected": None, "category": "timestamp_only"})
    return cases


def evaluate(fps: int = 30) -> dict:
    reports = []
    true_positive = false_negative = false_positive = true_negative = 0
    localization = []
    for scenario in benchmark_cases(fps):
        timestamps = scenario["times"]
        result = analyze_timestamps(timestamps, 0, max(timestamps) + 1/fps)
        gap_events = [item for item in result["events"] if item["kind"] == "timestamp_gap"]
        found = bool(gap_events)
        positive = scenario["positive"]
        if positive and found:
            true_positive += 1
        elif positive:
            false_negative += 1
        elif found:
            false_positive += 1
        else:
            true_negative += 1
        error = None
        if positive and found and scenario["expected"] is not None:
            error = min(abs(item["start"]-scenario["expected"]) for item in gap_events)
            localization.append(error)
        reports.append({
            "scenario": scenario["name"],
            "ground_truth_missing_frames": positive,
            "timestamp_gap_detected": found,
            "timing_quality": result["quality"],
            "gap_events": len(gap_events),
            "localization_error_seconds": round(error, 4) if error is not None else None,
            "interpretation": ("Actual missing frames with rewritten timestamps can be undetectable."
                               if scenario["category"] == "rewritten_pts" else
                               "Timestamp-only defect; a flag does not prove frames were lost."
                               if scenario["category"] == "timestamp_only" else ""),
        })
    def ratio(a, b):
        return round(a/b, 4) if b else None
    return {
        "benchmark": "synthetic_pts_only",
        "fps": fps,
        "cases": reports,
        "confusion_matrix": {"tp": true_positive, "fn": false_negative,
                             "fp": false_positive, "tn": true_negative},
        "sensitivity": ratio(true_positive, true_positive+false_negative),
        "precision": ratio(true_positive, true_positive+false_positive),
        "false_positive_cases": false_positive,
        "mean_localization_error_seconds": (
            round(sum(localization)/len(localization), 4) if localization else None
        ),
        "limitations": (
            "Synthetic PTS-array benchmark only. No decoded video frames, "
            "visual continuity measurements, encoder behavior or Natus references. "
            "Some negatives intentionally contain timestamp anomalies, so precision "
            "is for identifying actual frame removal, not any timing problem."
        ),
    }


def main():
    print(json.dumps(evaluate(), indent=2))


if __name__ == "__main__":
    main()

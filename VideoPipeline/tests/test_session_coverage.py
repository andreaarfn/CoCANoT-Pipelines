"""Reference clock session coverage tests; no video files or patient records."""
import unittest

from VideoPipeline.session_coverage import analyze_session_coverage


def segment(name, start, duration=1500, trim_start=0, trim_end=None):
    return {
        "id": name, "name": name, "recording_start": start,
        "duration": duration, "trim_start": trim_start,
        "trim_end": duration if trim_end is None else trim_end,
    }


class SessionCoverageTests(unittest.TestCase):
    def test_three_minute_gap_across_natus_segments(self):
        clips = [
            segment("a", "2026-11-23T10:00:00-06:00", 25*60),
            segment("b", "2026-11-23T10:28:00-06:00", 17*60),
            segment("c", "2026-11-23T10:45:00-06:00", 15*60),
        ]
        report = analyze_session_coverage(
            clips, "2026-11-23T10:00:00-06:00",
            "2026-11-23T11:00:00-06:00",
        )
        self.assertEqual(report["status"], "attention")
        self.assertEqual(len(report["events"]), 1)
        self.assertEqual(report["events"][0]["duration_seconds"], 180)
        self.assertEqual(report["covered_seconds"], 3420)
        self.assertEqual(report["coverage_percent"], 95.0)

    def test_unsorted_and_overlapping_video_segments_count_once(self):
        clips = [
            segment("later", "2026-11-23T10:09:00Z", 600),
            segment("first", "2026-11-23T10:00:00Z", 600),
        ]
        report = analyze_session_coverage(clips)
        self.assertEqual(report["events"], [])
        self.assertEqual(report["covered_seconds"], 1140)

    def test_neural_reference_detects_leading_and_trailing_gaps(self):
        report = analyze_session_coverage(
            [segment("middle", "2026-11-23T10:05:00Z", 300)],
            "2026-11-23T10:00:00Z", "2026-11-23T10:15:00Z",
        )
        self.assertEqual([e["location"] for e in report["events"]],
                         ["leading", "trailing"])
        self.assertEqual([e["duration_seconds"] for e in report["events"]],
                         [300, 300])

    def test_clip_trim_shifts_acquisition_coverage(self):
        report = analyze_session_coverage(
            [segment("trim", "2026-11-23T10:00:00Z", 600, 120, 360)],
            "2026-11-23T10:00:00Z", "2026-11-23T10:10:00Z",
        )
        self.assertEqual(report["covered_seconds"], 240)
        self.assertEqual(report["events"][0]["duration_seconds"], 120)
        self.assertEqual(report["events"][1]["duration_seconds"], 240)

    def test_unknown_start_makes_report_inconclusive(self):
        report = analyze_session_coverage([
            segment("known", "2026-11-23T10:00:00Z", 600),
            segment("unknown", None, 600),
        ])
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(report["unreferenced"][0]["name"], "unknown")

    def test_untrusted_naive_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            analyze_session_coverage([segment("a", "2026-11-23T10:00:00")])

    def test_no_reference_without_clip_start_is_inconclusive(self):
        report = analyze_session_coverage([segment("a", None)])
        self.assertEqual(report["status"], "inconclusive")
        self.assertFalse(report["events"])

    def test_neural_reference_same_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "end"):
            analyze_session_coverage(
                [segment("a", "2026-11-23T10:00:00Z")],
                "2026-11-23T10:00:00Z", "2026-11-23T10:00:00Z"
            )


if __name__ == "__main__":
    unittest.main()

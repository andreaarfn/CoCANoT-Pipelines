"""Synthetic timestamp tests for exploratory dropped-video detection."""
import unittest

from VideoPipeline.continuity import analyze_timestamps
from VideoPipeline.benchmark_continuity import evaluate


class ContinuityAnalysisTests(unittest.TestCase):
    def test_regular_frame_timestamps_do_not_flag_missing_video(self):
        times = [i/30 for i in range(90)]
        result = analyze_timestamps(times, 0, 3)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["quality"], "regular")

    def test_large_jump_localized_relative_to_trim(self):
        times = [i/30 for i in range(30)] + [2+i/30 for i in range(30)]
        result = analyze_timestamps(times, .5, 3)
        self.assertEqual(len(result["events"]), 1)
        item = result["events"][0]
        self.assertEqual(item["kind"], "timestamp_gap")
        self.assertAlmostEqual(item["start"], 29/30 - .5, places=2)
        self.assertAlmostEqual(item["end"], 1.5, places=2)

    def test_trim_excludes_outside_recording_anomalies(self):
        times = [i/30 for i in range(30)] + [2+i/30 for i in range(30)]
        result = analyze_timestamps(times, 2, 3)
        self.assertEqual(result["events"], [])

    def test_too_few_frames_are_inconclusive(self):
        result = analyze_timestamps([0], 0, 1)
        self.assertEqual(result["quality"], "insufficient")
        self.assertFalse(result["events"])

    def test_small_variation_not_flagged_as_gap(self):
        times = [0, .03, .065, .1, .132, .165, .197]
        result = analyze_timestamps(times, 0, 1)
        self.assertEqual(result["events"], [])


    def test_evidence_includes_raw_frame_intervals(self):
        times = [i/30 for i in range(300)]
        report = analyze_timestamps(times, 0, 10)
        self.assertEqual(report["frame_count"], 300)
        self.assertEqual(report["interval_count"], 299)
        self.assertEqual(len(report["intervals"]), 299)
        self.assertEqual(len(report["chart"]), 299)
        self.assertAlmostEqual(report["median_interval_ms"], 33.333, places=2)
        self.assertGreaterEqual(report["threshold_ms"], 120)

    def test_plot_preserves_largest_gap_in_downsampled_data(self):
        times = [i/30 for i in range(3000) if not 1500 <= i < 1530]
        report = analyze_timestamps(times, 0, 100)
        self.assertLessEqual(len(report["chart"]), 360)
        self.assertAlmostEqual(
            max(item["ms"] for item in report["chart"]),
            report["max_interval_ms"], places=3
        )

    def test_nonincreasing_pts_is_flagged_separately(self):
        times = [0, 1/30, 2/30, 2/30, 3/30, 4/30, 5/30]
        report = analyze_timestamps(times, 0, 1)
        self.assertTrue(any(item["kind"] == "nonincreasing_timestamp"
                            for item in report["events"]))

    def test_ground_truth_benchmark_documents_undetectable_rewritten_gap(self):
        benchmark = evaluate()
        cases = {item["scenario"]: item for item in benchmark["cases"]}
        self.assertFalse(cases["dropped_30_frames_rewritten_pts"]["timestamp_gap_detected"])
        self.assertFalse(cases["dropped_1_frames_preserve_pts"]["timestamp_gap_detected"])
        self.assertTrue(cases["dropped_10_frames_preserve_pts"]["timestamp_gap_detected"])
        self.assertFalse(cases["normal_constant_rate"]["timestamp_gap_detected"])
        self.assertGreater(benchmark["false_positive_cases"], 0)



if __name__ == "__main__":
    unittest.main()

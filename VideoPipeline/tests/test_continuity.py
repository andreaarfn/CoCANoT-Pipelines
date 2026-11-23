"""Synthetic timestamp tests for exploratory dropped-video detection."""
import unittest

from VideoPipeline.continuity import analyze_timestamps


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


if __name__ == "__main__":
    unittest.main()

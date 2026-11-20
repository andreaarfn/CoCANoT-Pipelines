"""Dependency-free tests for sampled MediaPipe face suggestion grouping."""
import unittest
from types import SimpleNamespace

from VideoPipeline.ai_faces import _assemble, _near, _rect


class FaceSuggestionsTests(unittest.TestCase):
    def test_rect_is_padded_and_clamped(self):
        box = SimpleNamespace(origin_x=-4, origin_y=10, width=20, height=20)
        detection = SimpleNamespace(bounding_box=box)
        result = _rect(detection, 100, 100)
        self.assertEqual(result["x"], 0)
        self.assertGreaterEqual(result["w"], .2)
        self.assertLessEqual(result["x"] + result["w"], 1)

    def test_consecutive_detections_group_into_one_suggestion(self):
        box = {"x": .2, "y": .3, "w": .1, "h": .1}
        result = _assemble([
            (0, .25, [{"box": box, "score": .9}]),
            (1, .75, [{"box": {**box, "x": .23}, "score": .8}])
        ], .5, 5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sample_count"], 2)
        self.assertEqual(result[0]["confidence"], .8)
        self.assertNotIn("keyframes", result[0])
        self.assertEqual(result[0]["end"], 1.0)

    def test_missing_detection_breaks_track(self):
        box = {"x": .2, "y": .3, "w": .1, "h": .1}
        result = _assemble([
            (0, .25, [{"box": box, "score": .9}]),
            (1, .75, []),
            (2, 1.25, [{"box": box, "score": .8}])
        ], .5, 3)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["end"], .5)
        self.assertEqual(result[1]["start"], 1.0)

    def test_very_different_face_not_joined(self):
        a = {"x": .1, "y": .1, "w": .1, "h": .1}
        b = {"x": .8, "y": .8, "w": .1, "h": .1}
        self.assertFalse(_near(a, b))
        self.assertEqual(len(_assemble([
            (0, .25, [{"box": a, "score": .95}]),
            (1, .75, [{"box": b, "score": .95}])
        ], .5, 3)), 2)


if __name__ == "__main__":
    unittest.main()

"""Dependency-free tests for RetinaFace coordinate adaptation and scoring."""
import unittest

from VideoPipeline.ai_retinaface import normalize_detections, normalize_face


class RetinaFaceAdapterTests(unittest.TestCase):
    def test_padding_matches_other_detectors(self):
        box = normalize_face([20, 30, 40, 40], 100, 100)
        self.assertAlmostEqual(box["x"], .16)
        self.assertAlmostEqual(box["y"], .28)
        self.assertAlmostEqual(box["w"], .28)
        self.assertAlmostEqual(box["h"], .14)

    def test_edge_boxes_clamped(self):
        box = normalize_face([-4, 3, 20, 24], 100, 100)
        self.assertEqual(box["x"], 0)
        self.assertGreater(box["w"], .2)
        self.assertLessEqual(box["x"] + box["w"], 1)

    def test_invalid_boxes_rejected(self):
        self.assertIsNone(normalize_face([10, 2, 10, 20], 100, 100))
        self.assertIsNone(normalize_face([float("nan"), 2, 10, 20], 100, 100))
        self.assertIsNone(normalize_face([1, 2, 3], 100, 100))
        self.assertIsNone(normalize_face([1, 2, 3, 4], 0, 100))

    def test_retinaface_response_mapping(self):
        result = normalize_detections({
            "face_1": {"facial_area": [10, 20, 30, 40], "score": .91},
            "face_2": {"facial_area": [45, 20, 60, 40], "score": .4},
            "face_3": {"facial_area": None, "score": .99}
        }, 100, 100)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["score"], .91)

    def test_empty_and_malformed_response(self):
        self.assertEqual(normalize_detections({}, 100, 100), [])
        with self.assertRaises(RuntimeError):
            normalize_detections(None, 100, 100)


if __name__ == "__main__":
    unittest.main()

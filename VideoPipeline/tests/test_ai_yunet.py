"""YuNet adapter unit checks; no patient video or model weights required."""
import unittest

from VideoPipeline.ai_yunet import face_box


class YuNetBoxTests(unittest.TestCase):
    def test_padding_and_normalization(self):
        result = face_box([20, 30, 20, 10], 100, 100)
        self.assertAlmostEqual(result["x"], .16)
        self.assertAlmostEqual(result["y"], .28)
        self.assertAlmostEqual(result["w"], .28)
        self.assertAlmostEqual(result["h"], .14)

    def test_clamp_at_frame_boundary(self):
        result = face_box([-4, 5, 20, 20], 100, 100)
        self.assertEqual(result["x"], 0)
        self.assertGreater(result["w"], .2)
        self.assertLessEqual(result["x"] + result["w"], 1.)

    def test_invalid_boxes_are_not_accepted(self):
        self.assertIsNone(face_box([1, 2, 0, 2], 100, 100))
        self.assertIsNone(face_box([1, 2, float("nan"), 2], 100, 100))


if __name__ == "__main__":
    unittest.main()

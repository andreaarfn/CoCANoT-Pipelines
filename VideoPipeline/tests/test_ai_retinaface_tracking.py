"""Association tests with a mocked optical-flow tracker (no video or AI weights)."""
import unittest
from unittest.mock import patch

from VideoPipeline.ai_retinaface import _suggestions_with_tracking


def box(x):
    return {"x": x, "y": .2, "w": .15, "h": .2}


def face(x):
    return {"box": box(x), "score": .9}


def motion(path, clip_start, clip_end, region, start, end, *, every_frame=False):
    assert every_frame
    return {"complete": True, "keyframes": [
        {"t": start, **region},
        {"t": (start + end) / 2, **{**region, "x": region["x"] + .01}},
        {"t": end, **{**region, "x": region["x"] + .02}},
    ]}


class OpticalFlowLinkTests(unittest.TestCase):
    @patch("VideoPipeline.advanced.track_region", side_effect=motion)
    def test_one_face_three_samples_becomes_one_motion_track(self, tracker):
        detections = [
            (0, .25, [face(.2)]),
            (1, .75, [face(.22)]),
            (2, 1.25, [face(.24)]),
        ]
        proposals = _suggestions_with_tracking(detections, "synthetic.mp4", 0, 2, .5)
        self.assertEqual(len(proposals), 1)
        self.assertTrue(proposals[0]["tracking_complete"])
        self.assertEqual(proposals[0]["sample_count"], 3)
        self.assertGreaterEqual(len(proposals[0]["tracked_keyframes"]), 5)
        self.assertAlmostEqual(proposals[0]["start"], .25)
        self.assertAlmostEqual(proposals[0]["end"], 1.25)
        self.assertEqual(tracker.call_count, 2)

    @patch("VideoPipeline.advanced.track_region", side_effect=motion)
    def test_a_missing_detection_ends_track(self, _tracker):
        detections = [(0, .25, [face(.2)]), (1, .75, []),
                      (2, 1.25, [face(.24)])]
        proposals = _suggestions_with_tracking(detections, "synthetic.mp4", 0, 2, .5)
        self.assertEqual(len(proposals), 2)
        self.assertTrue(proposals[0]["interrupted"])
        self.assertFalse(proposals[0]["tracking_complete"])

    @patch("VideoPipeline.advanced.track_region")
    def test_failed_tracking_does_not_merge_detections(self, tracker):
        tracker.return_value = {"complete": False, "warning": "lost features"}
        detections = [(0, .25, [face(.2)]), (1, .75, [face(.2)])]
        proposals = _suggestions_with_tracking(detections, "synthetic.mp4", 0, 2, .5)
        self.assertEqual(len(proposals), 2)
        self.assertTrue(proposals[0]["interrupted"])
        self.assertFalse(proposals[0]["tracked_keyframes"])

    @patch("VideoPipeline.advanced.track_region", side_effect=motion)
    def test_two_faces_do_not_merge_into_one_track(self, _tracker):
        detections = [(0, .25, [face(.1), face(.7)]),
                      (1, .75, [face(.12), face(.72)])]
        proposals = _suggestions_with_tracking(detections, "synthetic.mp4", 0, 2, .5)
        self.assertEqual(len(proposals), 2)
        self.assertTrue(all(s["sample_count"] == 2 for s in proposals))


if __name__ == "__main__":
    unittest.main()

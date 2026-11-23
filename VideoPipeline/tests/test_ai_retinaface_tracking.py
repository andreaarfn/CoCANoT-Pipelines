"""Association tests with a mocked optical-flow tracker (no video or AI weights)."""
import unittest
from unittest.mock import patch

from VideoPipeline.ai_retinaface import _suggestions_with_tracking


def box(x):
    return {"x": x, "y": .2, "w": .15, "h": .2}


def face(x):
    return {"box": box(x), "score": .9}


def motion(path, clip_start, clip_end, region, start, end, *,
           every_frame=False, reverse=False):
    assert every_frame
    assert reverse == (end < start)
    points = [
        {"t": start, **region},
        {"t": (start + end) / 2, **{**region, "x": region["x"] + .01}},
        {"t": end, **{**region, "x": region["x"] + .02}},
    ]
    return {"complete": True, "keyframes": sorted(points, key=lambda p: p["t"])}


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
        self.assertAlmostEqual(proposals[0]["start"], 0.)
        self.assertAlmostEqual(proposals[0]["end"], 2.)
        self.assertTrue(proposals[0]["leading_extended"])
        self.assertTrue(proposals[0]["trailing_extended"])
        self.assertEqual(tracker.call_count, 4)

    @patch("VideoPipeline.advanced.track_region", side_effect=motion)
    def test_a_missing_detection_ends_track(self, _tracker):
        detections = [(0, .25, [face(.2)]), (1, .75, []),
                      (2, 1.25, [face(.24)])]
        proposals = _suggestions_with_tracking(detections, "synthetic.mp4", 0, 2, .5)
        self.assertEqual(len(proposals), 2)
        self.assertTrue(proposals[0]["interrupted"])
        self.assertFalse(proposals[0]["tracking_complete"])

    @patch("VideoPipeline.advanced.track_region", side_effect=motion)
    def test_valid_prefix_kept_when_later_sample_has_no_detection(self, _tracker):
        detections = [(0, .25, [face(.2)]), (1, .75, [face(.22)]),
                      (2, 1.25, [])]
        proposals = _suggestions_with_tracking(detections, "synthetic.mp4", 0, 2, .5)
        self.assertEqual(len(proposals), 1)
        self.assertTrue(proposals[0]["interrupted"])
        self.assertTrue(proposals[0]["tracking_complete"])
        self.assertAlmostEqual(proposals[0]["start"], 0.)
        self.assertAlmostEqual(proposals[0]["end"], .75)
        self.assertGreater(len(proposals[0]["tracked_keyframes"]), 1)

    @patch("VideoPipeline.advanced.track_region", side_effect=motion)
    def test_midclip_track_does_not_automatically_extend_to_boundaries(self, _tracker):
        detections = [(0, .25, []), (1, .75, [face(.2)]),
                      (2, 1.25, [face(.22)]), (3, 1.75, [])]
        proposals = _suggestions_with_tracking(detections, "synthetic.mp4", 0, 2, .5)
        self.assertEqual(len(proposals), 1)
        self.assertAlmostEqual(proposals[0]["start"], .75)
        self.assertAlmostEqual(proposals[0]["end"], 1.25)
        self.assertFalse(proposals[0]["leading_extended"])
        self.assertFalse(proposals[0]["trailing_extended"])

    @patch("VideoPipeline.advanced.track_region", side_effect=motion)
    def test_single_detection_does_not_invent_continuous_track(self, tracker):
        detections = [(0, .25, [face(.2)])]
        proposals = _suggestions_with_tracking(detections, "synthetic.mp4", 0, .5, .5)
        self.assertEqual(len(proposals), 1)
        self.assertFalse(proposals[0]["tracking_complete"])
        self.assertFalse(proposals[0]["leading_extended"])
        self.assertFalse(proposals[0]["trailing_extended"])
        tracker.assert_not_called()

    @patch("VideoPipeline.advanced.track_region")
    def test_failed_boundary_extension_is_not_claimed(self, tracker):
        def stop_at_boundary(path, clip_start, clip_end, region, start, end,
                             *, every_frame=False, reverse=False):
            if reverse or end == clip_end - clip_start:
                return {"complete": False, "warning": "feature loss"}
            return motion(path, clip_start, clip_end, region, start, end,
                          every_frame=every_frame, reverse=reverse)
        tracker.side_effect = stop_at_boundary
        detections = [(0, .25, [face(.2)]), (1, .75, [face(.22)])]
        proposals = _suggestions_with_tracking(detections, "synthetic.mp4", 0, 1., .5)
        self.assertEqual(len(proposals), 1)
        self.assertAlmostEqual(proposals[0]["start"], .25)
        self.assertAlmostEqual(proposals[0]["end"], .75)
        self.assertFalse(proposals[0]["leading_extended"])
        self.assertFalse(proposals[0]["trailing_extended"])
        self.assertIn("Could not track", proposals[0]["edge_warning"])

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

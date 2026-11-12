"""Regression tests for saved Video projects following exported Video ID renames."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from VideoPipeline.processing import load_project


class VideoProjectPathRebindingTests(unittest.TestCase):
    def test_renamed_video_keeps_clip_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old_path = str(root / "sub-001_VID-001.mp4")
            new_path = str(root / "sub-001_VID-002.mp4")
            project_path = root / "saved_video_project.json"
            masks = [{"type": "solid", "x": 0.1, "y": 0.2,
                      "w": 0.3, "h": 0.4, "start": 1, "end": 5}]
            project_path.write_text(json.dumps({
                "schema_version": 1,
                "clips": [{"path": old_path, "start": 0, "end": 6,
                           "masks": masks, "remove_audio": False}],
            }), encoding="utf-8")
            seen = []

            def fake_inspect(path):
                seen.append(path)
                self.assertEqual(path, new_path)
                return {"path": path, "name": Path(path).name,
                        "duration": 10, "audio": False, "width": 640, "height": 480}

            with patch("VideoPipeline.processing.inspect_video", side_effect=fake_inspect):
                restored = load_project(
                    str(project_path),
                    resolve_clip_path=lambda path: new_path if path == old_path else path,
                )
            self.assertEqual(seen, [new_path])
            self.assertEqual(restored["clips"][0]["path"], new_path)
            self.assertEqual(restored["clips"][0]["masks"], masks)
            self.assertEqual(restored["clips"][0]["end"], 6)

    def test_no_rebinding_preserves_original_project_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video_path = str(root / "recording.mp4")
            project_path = root / "project.json"
            project_path.write_text(json.dumps({
                "schema_version": 1,
                "clips": [{"path": video_path, "start": 0, "end": 3, "masks": []}],
            }), encoding="utf-8")
            with patch("VideoPipeline.processing.inspect_video", return_value={
                "path": video_path, "name": "recording.mp4",
                "duration": 5, "audio": False, "width": 640, "height": 480,
            }) as inspected:
                restored = load_project(str(project_path))
            self.assertEqual(restored["clips"][0]["path"], video_path)
            inspected.assert_called_once_with(video_path)


if __name__ == "__main__":
    unittest.main()

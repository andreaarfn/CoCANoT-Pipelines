# Video motion tracking and background blur (experimental)

This branch adds optional OpenCV-powered features to the CoCANoT Video workspace.

## Local development prerequisites
- Existing CoCANoT Python 3.12 environment
- FFmpeg and FFprobe on PATH (macOS: `brew install ffmpeg`)
- OpenCV in the **same Python environment** used to launch CoCANoT:
  `python -m pip install opencv-python`

The video editor can still inspect and import files without OpenCV. Tracking and
blurred exports require it. The pipeline never uploads video to a remote service.

## How to test
1. Import an H.264 MP4 and add a solid censor box.
2. Move the playhead to the desired starting frame.
3. Use **Track forward from playhead** on the region.
4. Scrub the preview to inspect the tracked positions. Tracking is limited
   to 120 seconds per request, and stops if confidence drops.
5. Optionally choose **Blur outside preserved area** and change the
   four preserve-region coordinates (percent of the 1280x720 canvas).
6. Save the project and export a censored MP4. Audio is removed.
7. Independently review the *rendered* video, frame by frame around
   motion, occlusions, and cuts, before any sharing.

## Privacy warnings
- Motion tracking is based on local template matching and can drift or stop.
- Tracking gaps extending beyond the last keyframe block export; re-track
  or explicitly revise the censor interval and manually inspect the remainder.
- Background blur is aesthetic obscuration, not guaranteed de-identification.
  Use fully opaque censor regions for identifiers and review the output.
- Automatic face/text detection, freehand masks, full audio redaction,
  and privacy certification are not implemented.
- The OpenCV renderer normalizes output to 1280x720 at 30fps and is intended
  for short development/test clips. Variable-frame-rate inputs require
  additional verification.

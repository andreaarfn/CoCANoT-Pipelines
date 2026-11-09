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
3. Drag directly on the video to draw a censor region, then use **Track forward from playhead**.
   Tracking uses Lucas–Kanade optical flow with bidirectional checks and RANSAC, and stops on low confidence.
4. Scrub the preview to inspect the tracked positions. Tracking is limited
   to 120 seconds per request, and stops if confidence drops.
5. Optionally choose **Blur outside preserved area** and change the
   four preserve-region coordinates (percent of the 1280x720 canvas).
   Select **Smart subject selection (GrabCut)** to attempt separating the
   subject's pixels from the surrounding background at export time.
   The in-editor preview is approximate and is not a processed-frame preview.
6. Save the project and export a censored MP4. Audio is removed.
7. Independently review the *rendered* video, frame by frame around
   motion, occlusions, and cuts, before any sharing.

## Privacy warnings
- Motion tracking is based on local template matching and can drift or stop.
- Tracking gaps extending beyond the last keyframe block export; re-track
  or explicitly revise the censor interval and manually inspect the remainder.
- Background blur is aesthetic obscuration, not guaranteed de-identification.
- Smart subject segmentation requires a good foreground seed rectangle and can
  accidentally blur the subject or preserve unintended background pixels.
- Pixel-based tracking and GrabCut are CPU-intensive; use short sample videos
  initially. More advanced neural segmentation can be added later.
  Use fully opaque censor regions for identifiers and review the output.
- Automatic face/text detection, freehand masks, full audio redaction,
  and privacy certification are not implemented.
- The OpenCV renderer normalizes output to 1280x720 at 30fps and is intended
  for short development/test clips. Variable-frame-rate inputs require
  additional verification.

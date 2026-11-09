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
2. Move the playhead to the intended first frame and drag to draw a censor box.
3. Set the censor region's **Start** and **End** times in the region settings.
4. Click **Track censor interval**. Tracking begins at the region's Start time
   and ends at its End time, regardless of where the playhead currently is.
   Lucas–Kanade optical flow with consistency checks/RANSAC tracks visual features.
   There is no 120-second cutoff; long intervals can take significantly longer.
   If confidence drops, tracking stops and warns you, and export will block
   incomplete tracked intervals until they are corrected.
   Changing Start/End clears the previous tracking and requires tracking again.
   Scrub the preview and visually inspect the rendered result.
5. Optionally choose **Blur outside preserved area** and change the
   four preserve-region coordinates (percent of the 1280x720 canvas).
   Select **Smart subject selection (GrabCut)** to attempt separating the
   subject's pixels from the surrounding background at export time.
   The in-editor preview is approximate and is not a processed-frame preview.
6. Save the project and export a censored MP4. Audio is removed.
7. Independently review the *rendered* video, frame by frame around
   motion, occlusions, and cuts, before any sharing.

## Privacy warnings
- Motion tracking is based on local optical flow and can drift or stop.
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

## Zoom-style people-aware blur (optional)
- Install the optional person segmentation runtime into the **active** Python
  environment: `python -m pip install mediapipe`.
- Download the official MediaPipe selfie segmentation model locally:
  `mkdir -p ~/.cocanot/models`
  `curl -fL https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/1/selfie_segmenter.tflite -o ~/.cocanot/models/selfie_segmenter.tflite`
- In Video -> Background blur, select **Detect people automatically (Zoom-style)**.
  This runs inference entirely on-device (the model download is separate).
- People are automatically preserved in focus and the remaining scene is
  blurred; no manual bounding rectangle is required.
- The current video preview is approximate. The actual segmentation is only
  visible after exporting. Inspect the output for flickering edges, partial
  people, missed subjects, and visible information in the background.
- This model is primarily intended for foreground portraits/video calls. It
  may perform poorly on overhead surgical fields, multiple occluded people,
  unusual viewpoints, or gloves/instruments. Keep the rectangle and GrabCut
  alternatives for those recordings.
- MediaPipe is optional and not currently included in packaged installers.
  This branch requires manual installation for testing.

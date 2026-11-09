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

## If every censor region reports "Tracking incomplete"
- Update to the latest branch and run **Track censor interval** again.
  Existing saved projects retain old keyframes until retracked.
- The tracker now combines optical flow with a local correlation fallback
  when corner features disappear; it reports the reason and stop time per region.
- If a region still fails: draw it around a larger textured area, avoid
  fully black/flat regions, or split the censor time span into smaller intervals.
- An incomplete track is *not* accepted as de-identified. Check every frame.

## Censor boxes growing during tracking (fixed)
The previous optical-flow path applied repeated scale/rotation estimates,
which could inflate a box over time even if the target had not grown.
Tracking now estimates **translation only** and preserves each mask's
initial width and height throughout the interval. Preview and export
also clamp tracked keyframe dimensions back to that original size,
including already-saved projects with older enlarged keyframes.
For best tracking positions, retrack old regions after updating.
This preserves size but does not guarantee that a moving or approaching
subject remains fully covered: verify the rendered video frame by frame.

## People-aware blur setup in the Video workspace
The **Detect people automatically (Zoom-style)** option now has an integrated
setup and single-frame preview. Import a clip, enable background blur, select
the people-aware mode, and click **Download person detection model**.
This downloads *public model weights only* after an explicit click. Footage
remains on the local computer. The MediaPipe Python runtime is still an
optional install: `python -m pip install mediapipe` in the same environment
that launches CoCANoT. The UI checks readiness and shows setup instructions.

Use **Preview people-aware blur at playhead** to generate a real segmented
still frame with background blur. This does not play the video or modify it.
Click **Return to video playback** to resume editing. The final export applies
the model frame by frame with temporal mask smoothing.

**Not a de-identification guarantee:** This intentionally keeps people,
including faces, sharp. Use separate opaque censor boxes for identities and
inspect the entire output. Selfie Segmenter is optimized for front-facing
people and may miss clinical subjects, odd perspectives, or foregrounds.

## Manual foreground masks for distant subjects (new)
When the Zoom-style automatic person model misses a distant or unusually posed
person, select **Background blur → Draw foreground masks (manual)**.

1. Import your video and pause at a representative frame.
2. Check **Blur outside preserved area** and set **Blur method** to
   **Draw foreground masks (manual)**.
3. Click **Draw foreground mask**, then click successive points along the
   subject's outline. Use **Undo point** to correct the last vertex, and
   **Finish outline** to close and save the selected foreground area.
4. Repeat for additional people or other areas you want to keep sharp.
5. Change **Blur strength** and **Edge softness**, then click
   **Preview masked blur at playhead** to inspect a processed still image.
6. Export as usual. The selected foreground areas are preserved, while
   pixels outside the outlines receive Gaussian background blur.
   The exported recording has no audio.

This method uses OpenCV locally and does **not** require MediaPipe or downloading
a people-detection model. It is manual, image-frame-anchored masking; outlines do
not yet auto-follow moving subjects. For footage with significant camera/subject
motion, recheck the mask on multiple frames and do not release an output with
exposed identifying background details. The preview is a still frame; the saved
MP4 must be examined separately. Opaque face censor boxes remain necessary
where de-identification requires obscuring people's identities.

# CoCANoT Video (experimental)

The current Video pipeline supports local video import, trimming, clip
reordering, solid opaque censor boxes, motion tracking, project save/load,
and export of audio-free 720p MP4 files.

**Background blur, automatic people segmentation, and hand-drawn foreground
blur masks have been removed from this branch for now.** Older saved projects
may contain `background_blur` settings. These settings are ignored during
processing and stripped when loading or saving a project.

## Requirements

- FFmpeg / FFprobe on PATH (macOS: `brew install ffmpeg`)
- OpenCV for motion tracking and moving-mask export:
  `python -m pip install opencv-python`

## Optional MediaPipe AI face first pass

The **Scan faces (AI)** button in Process Video runs a *local*, optional
MediaPipe Tasks face detector. It does not upload patient footage or automatically
approve censoring. MediaPipe detects faces on sampled frames; CoCANoT groups
nearby consecutive detections into **unapproved suggestions**.

Install into the **same Python environment that runs CoCANoT**:

```bash
python -m pip install mediapipe opencv-python
```

The model is a separate local file (download once on an approved machine):

```bash
mkdir -p VideoPipeline/models
curl -fL "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite" \
  -o VideoPipeline/models/blaze_face_short_range.tflite
```

Run from the repository root. Alternatively set
`COCANOT_MEDIAPIPE_FACE_MODEL` to the absolute path of a locally approved
`.tflite` model. **The scan does not download models or send footage to the
internet.** The detector only recognizes faces, not text, identifiers, or all
sensitive body regions. The short-range model is intended for relatively close
faces. This optional dependency is not yet bundled in the installer.

1. Select a clip in **Process Video**, then click **Scan faces (AI)**.
2. Use **View**, **Accept box**, or **Reject** for each suggestion.
3. Accepted suggestions become ordinary editable solid censor boxes. The
   position is initially a *sampled estimate*, not verified tracking; use
   **Track censor interval** as needed and inspect the entire interval.
4. Continue through the existing manual review, correcting any missed faces
   or other identifiers. Pending AI suggestions block export.
5. Re-scan a clip if it was trimmed or split: edits invalidate old suggestions.

Sampling scans up to 1,200 frames across a clip (normally 2 frames/second);
a detection gap ends a suggestion, rather than silently bridging it. Even an
accepted region may drift or leave frames uncovered. **The presence or absence
of AI suggestions is never proof of de-identification.** Inspect the complete
rendered output before sharing. Scores describe model detections, not the
probability that a face is safely censored.

## Working with censor boxes

1. Import a video and pause at the intended starting frame.
2. Click **Add censor box**, then drag to place a solid black region.
   Drawing does not start video playback.
3. Adjust the censor region's **Start** and **End** times.
4. Click **Track censor interval** to estimate its position throughout
   that interval. Optical flow and template recovery are experimental.
   Censor box width and height are held fixed during tracking.
5. Review the region's positions, including occlusions and motion. If
   tracking stops before the end, correct or split the interval.
6. Save the editing project and export. Original footage is never modified,
   and audio is removed from the exported MP4.

**Privacy:** Tracking can drift, and a solid censor box can fail to cover an
identifier even when tracking reaches the end. Independently inspect the
entire rendered video before sharing research footage. None of these
features automatically certifies de-identification.

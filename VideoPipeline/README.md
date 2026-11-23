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

## Experimental RetinaFace-only AI first pass

This branch uses the **RetinaFace** detector, independently of YuNet and
MediaPipe. The detector runs in a separate local Python worker process so its
PyTorch/OpenMP libraries do not load into the CoCANoT desktop process. This
isolation does not eliminate possible conflicts between dependencies within
the worker itself; if the scan reports an OpenMP error, its dependency stack
must still be repaired. No unsafe duplicate-OpenMP workaround is used. It preserves the same sampling cadence (approximately two
frames/second, up to 1,200 frames), 20% extra bounding-box padding, suggestion
grouping, review controls, manual tracking, and export safeguards. Matching
threshold values across detectors does not mean their scores are calibrated.

### Install once in CoCANoT's Python environment

On macOS, from the CoCANoT repository root:

```bash
~/Library/cocanot-pipelines/bin/python -m pip install "retina-face" "opencv-python"
```

This uses the serengil/retinaface Python implementation. The current project
documents an ONNX Runtime default backend, but some versions require
TensorFlow/PyTorch or an explicit backend selection. If a backend import
fails, check the installed release's documentation before installing heavy
dependencies. Do not change the normal CoCANoT installers for this experiment.

**Important privacy and setup note:** This package may automatically download
pretrained model weights when first calling `RetinaFace.build_model()`.
Before processing patient footage, initialize it using an approved machine
and a **non-sensitive synthetic test**, then confirm the model works offline.
The implementation passes video frames in memory to the local detector;
it does not contain any upload operation for frames. However, a first-time
weight download may use the network. For strictly offline environments,
preinstall and verify the weights before use; do not run the first scan
on identifiable recordings. Avoid automatically bundling third-party model
weights until their redistribution terms have been checked.

### Motion-linked face tracks (this experiment)

The scanner first samples RetinaFace detections at approximately **2 fps**,
as on the other detector branches. It then uses CoCANoT's existing
**Lucas–Kanade optical-flow tracker on every decoded frame** between nearby
samples. When optical-flow motion and the next RetinaFace detection agree, they
are combined into **one suggested face track** with time-stamped positions,
rather than an independent suggestion for each detection.

- **View track** previews the linked moving box.
- **Accept track** carries the proposed motion keyframes into an editable
  censor region; it does **not** mean the whole video or face was successfully
  de-identified. Carefully check the movement, box size, frame boundaries and
  final rendered video.
- A detection with no successful linked motion remains an **untracked box**
  and must be manually tracked/corrected if it is accepted.
- If optical flow loses the face or the next sampled face detection does not
  corroborate it, the suggested track **ends**. Later detections may begin new
  suggestions. This intentionally does not invent uninterrupted face coverage
  across gaps or occlusions.
- Neither optical flow nor detector matching establishes a person's identity;
  crossing faces can still cause drift or identity switches. **Every face
  and every gap requires human inspection.**

**Performance:** tracking every frame is more expensive than the original
2-fps-only detector. Start with a short non-sensitive clip before attempting
long clinical recordings. The code is experimental and has not been validated
against clinical de-identification standards.

### Review workflow

1. Select the same short test clip and trim interval as on the other branches.
2. Click **Scan faces (AI)** in **Process Video**. RetinaFace detects sampled frames, then optical flow tracks between them.
3. Choose **View track** to see the dashed, unapproved moving suggestion overlay.
4. Use **Accept track** for a linked motion proposal, **Accept box** for an untracked detection, or **Reject** to dismiss.
5. If accepted, **Track censor interval**, manually correct failures, and
   review the entire source and final output. Pending suggestions block export.

An accepted linked face track includes proposed per-frame motion positions, but those positions are **not validated for privacy coverage**; single detections remain stationary boxes. Detection is
not identity recognition and does not detect text or all PHI. Any detection
can miss faces, including profiles, small/obscured faces, and frames
between samples. A scan with zero detections is not proof of de-identification.

For comparison, count missed faces (particularly side/downward poses), false
suggestions, total manual edits, and processing time. The MediaPipe
(`video-ai-pipeline`) and YuNet (`feat/video-yunet-experiment`) branches
are unchanged.

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

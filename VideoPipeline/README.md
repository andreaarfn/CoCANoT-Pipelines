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
MediaPipe. It preserves the same sampling cadence (approximately two
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

### Review workflow

1. Select the same short test clip and trim interval as on the other branches.
2. Click **Scan faces (AI)** in **Process Video**.
3. Choose **View box** to see the dashed, unapproved suggestion overlay.
4. Use **Accept box** to make an editable censor box or **Reject** to dismiss.
5. If accepted, **Track censor interval**, manually correct failures, and
   review the entire source and final output. Pending suggestions block export.

An accepted suggestion starts as a stationary box; sampled positions are
only visual hints and are **not validated motion tracks**. Detection is
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

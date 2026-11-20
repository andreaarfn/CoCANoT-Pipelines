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

## YuNet-only AI face detection experiment

This branch swaps the face detector to **OpenCV YuNet** while preserving the
same user interface and frame-sampling schedule as the MediaPipe test branch.
No MediaPipe dependency is needed for YuNet inference. All processing remains local.

Install OpenCV into the Python environment launching CoCANoT:

```bash
~/Library/cocanot-pipelines/bin/python -m pip install "opencv-python>=4.8,<5"
```

Download the official OpenCV Zoo YuNet model on an approved computer
(before scanning patient videos):

```bash
mkdir -p VideoPipeline/models
curl -fL "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
  -o VideoPipeline/models/face_detection_yunet_2023mar.onnx
```

Alternatively set `COCANOT_YUNET_FACE_MODEL` to the full path of the local
ONNX file. The scanner never uploads video or downloads the model itself.
The OpenCV Zoo model has its own license; review the source repository before
redistributing model weights in a packaged installer.

1. Import and trim a clip in **Process Video**.
2. Click **Scan faces (AI)**. YuNet scans sampled frames using a score
   threshold of 0.50 and pads proposed face boxes by 20%.
3. Select **View box** to inspect an unapproved detection, then **Accept box**
   or **Reject**. Accepted boxes can be moved, resized and tracked through the
   existing manual OpenCV workflow.
4. Review all footage (not just detections), then inspect the rendered export.

**Comparison protocol:** Scan the *same trimmed clip* on both branches.
The sample schedule is unchanged (approximately two frames/second, up to
1,200 frames). Thresholds of 0.50 are *not calibrated across models*, and
raw detector confidence scores should not be compared as equivalent
probabilities. Count detected/missed face instances and record review time.
Neither detector guarantees privacy coverage, especially for profile, tilted,
occluded, or small faces. Pending suggestions block export.

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

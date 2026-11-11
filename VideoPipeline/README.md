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

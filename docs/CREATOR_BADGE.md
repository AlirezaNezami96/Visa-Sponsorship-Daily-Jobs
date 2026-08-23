# Video Creator Badge Overlay Service

The **Video Creator Badge Overlay Service** is a production-ready, standalone media processing service that automatically composites a polished personal creator badge into the bottom-right corner of any video (MP4, MOV, WEBM, etc.).

---

## 🌟 Visual Badge Architecture

The badge is rendered as an anti-aliased, high-DPI transparent composite layer:

```
                ┌──────────────────────────────────┐
                │  Alireza Nezami                  │ (Bold, dark text)
   ( PHOTO )    │  alireza-nezami                  │ (Light grey handle)
                └──────────────────────────────────┘
```

- **Circular Profile Avatar**: Automatically cropped from project candidate images (e.g. `assets/samples/ChatGPT Image Aug 11, 2026, 01_48_27 PM.jpg`), masked with smooth anti-aliased circular alpha curves, overlapping the left edge of the white pill.
- **White Pill Container**: Rounded rectangular background with dynamic corner radii.
- **Dynamic Text Fitting**: Text bounding boxes are measured and dynamically downscaled if necessary to ensure names/usernames never clip or overflow.
- **Proportional Resolution Scaling**: The badge scales dynamically to look balanced on:
  - 1920x1080 (Landscape)
  - 1080x1920 (Portrait / Reels / TikTok)
  - 1080x1080 (Square)
  - 1280x720, 2560x1440, 4K, and arbitrary resolutions.
- **Old Badge / Watermark Coverage**: When `remove_existing_badge=True` (default), the underlying bottom-right area is cleanly covered before overlaying the new creator badge.

---

## 📦 Architecture & Modules

The service is organized cleanly in `src/job_radar/creator_badge/`:

| Module | Responsibility |
|---|---|
| [`service.py`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/src/job_radar/creator_badge/service.py) | Main orchestration service, public APIs (`create_creator_badge_video`, `create_badge_preview`, `generate_video_preview`, batch processing). |
| [`renderer.py`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/src/job_radar/creator_badge/renderer.py) | Dynamic badge layout engine with 2x supersampling and text fitting. |
| [`image_processor.py`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/src/job_radar/creator_badge/image_processor.py) | Profile image discovery, EXIF correction, 1:1 center-cropping, circular masking. |
| [`video_metadata.py`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/src/job_radar/creator_badge/video_metadata.py) | FFprobe video inspection (`width`, `height`, `duration`, `fps`, `has_audio`). |
| [`ffmpeg_service.py`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/src/job_radar/creator_badge/ffmpeg_service.py) | FFmpeg filter graph generation, old watermark covering, audio stream preservation. |
| [`font_manager.py`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/src/job_radar/creator_badge/font_manager.py) | Multi-platform font resolver (macOS, Linux, Windows, bundled fallback). |
| [`config.py`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/src/job_radar/creator_badge/config.py) | Central configuration parameters (`CreatorBadgeConfig`). |
| [`exceptions.py`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/src/job_radar/creator_badge/exceptions.py) | Explicit domain exceptions (`VideoNotFoundError`, `InvalidVideoError`, `ProfileImageNotFoundError`, `FFmpegNotFoundError`, `FFmpegExecutionError`). |
| [`cli.py` / `creator_badge_cmd.py`](file:///Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/src/job_radar/cli/creator_badge_cmd.py) | Command-line interface. |

---

## 🚀 Quickstart & API Usage

### 1. Process Video with Default Settings

```python
from job_radar.creator_badge import create_creator_badge_video

# Automatically loads profile image from assets/samples, scales badge, and covers old watermark
output_path = create_creator_badge_video(
    input_path="input_video.mp4",
    output_path="output_badged.mp4",
)
print(f"Video saved to {output_path}")
```

### 2. Custom Name, Username, or Profile Image

```python
from job_radar.creator_badge import create_creator_badge_video

create_creator_badge_video(
    input_path="tutorial.mov",
    output_path="tutorial_branded.mp4",
    name="Alireza Nezami",
    username="alireza-nezami",
    profile_image_path="path/to/custom_photo.jpg",
    remove_existing_badge=True,
)
```

### 3. Generate Badge Preview (Transparent PNG)

```python
from job_radar.creator_badge import create_badge_preview

# Generate preview for 1920x1080 landscape
create_badge_preview("badge_landscape.png", target_resolution=(1920, 1080))

# Generate preview for 1080x1920 portrait (Reels / TikTok)
create_badge_preview("badge_portrait.png", target_resolution=(1080, 1920))
```

### 4. Fast Short Video Preview (First N Seconds)

```python
from job_radar.creator_badge import generate_video_preview

# Processes only the first 3.0 seconds for quick visual tuning
generate_video_preview("long_video.mp4", "preview_clip.mp4", duration=3.0)
```

### 5. Batch Processing Multiple Videos

```python
from job_radar.creator_badge import CreatorBadgeService

service = CreatorBadgeService()
videos = [
    ("clips/video1.mp4", "output/video1_badged.mp4"),
    ("clips/video2.mp4", "output/video2_badged.mp4"),
]
results = service.process_batch(videos)
```

---

## 💻 CLI Usage

The service exposes the command `job-radar-creator-badge` (registered in `pyproject.toml`):

```bash
# 1. Full video processing
job-radar-creator-badge input.mp4 output.mp4

# 2. Fast 3-second preview clip
job-radar-creator-badge input.mp4 output_preview.mp4 --preview --duration 3.0

# 3. Generate transparent PNG badge only
job-radar-creator-badge preview.png --badge-only --target-res 1920x1080

# 4. Custom name, username, and custom image
job-radar-creator-badge input.mp4 output.mp4 \
    --name "Alireza Nezami" \
    --username "alireza-nezami" \
    --profile-image "assets/samples/ChatGPT Image Aug 11, 2026, 01_48_27 PM.jpg"

# 5. Disable covering old watermark
job-radar-creator-badge input.mp4 output.mp4 --no-cover
```

---

## ⚙️ Configuration Reference (`CreatorBadgeConfig`)

| Option | Default | Description |
|---|---|---|
| `name` | `"Alireza Nezami"` | Primary display name rendered in bold. |
| `username` | `"alireza-nezami"` | Handle rendered below name in smaller font. |
| `profile_image_path` | Auto-detected | Path to avatar picture. Defaults to `assets/samples/`. |
| `badge_scale_ratio` | `0.26` | Proportional sizing relative to video resolution. |
| `right_margin_ratio` | `0.025` | Right margin spacing from video right edge. |
| `bottom_margin_ratio` | `0.035` | Bottom margin spacing from video bottom edge. |
| `remove_existing_badge` | `True` | Whether to cover the underlying bottom-right area. |
| `existing_badge_cover_color` | `"black@1.0"` | Color/opacity of the background cover box. |
| `badge_bg_color` | `"#FFFFFF"` | Background color of the rounded pill. |
| `video_codec` | `"libx264"` | Video encoder. |
| `video_crf` | `18` | Quality CRF factor (18 = visually lossless). |
| `video_preset` | `"medium"` | Encoding speed preset. |
| `audio_codec` | `"copy"` | Audio track preservation mode. |

---

## 🧪 Testing

Run the automated test suite:

```bash
python3 -m pytest tests/test_creator_badge.py -v
```

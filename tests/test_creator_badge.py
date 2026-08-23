"""Comprehensive automated test suite for Creator Badge Overlay Service."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
import pytest
from PIL import Image

from job_radar.creator_badge import (
    CreatorBadgeConfig,
    CreatorBadgeError,
    CreatorBadgeService,
    FFmpegService,
    FontManager,
    InvalidVideoError,
    ProfileImageNotFoundError,
    ProfileImageProcessor,
    VideoMetadataService,
    VideoNotFoundError,
    create_badge_preview,
    create_creator_badge_video,
    generate_video_preview,
)
from job_radar.creator_badge.renderer import BadgeRenderer


def is_ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def generate_synthetic_video(
    output_path: Path,
    width: int = 640,
    height: int = 360,
    duration: float = 1.0,
    with_audio: bool = True,
    fps: int = 24,
) -> Path:
    """Generates a synthetic MP4/MOV test video using FFmpeg lavfi filters."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"testsrc=size={width}x{height}:rate={fps}:duration={duration}",
    ]

    if with_audio:
        cmd.extend([
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={duration}",
            "-c:a", "aac",
        ])

    if width % 2 != 0 or height % 2 != 0:
        cmd.extend(["-c:v", "mjpeg", str(output_path)])
    else:
        cmd.extend([
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ])

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to generate synthetic test video: {res.stderr.decode('utf-8')}")
    return output_path


def create_sample_image(path: Path, width: int = 500, height: int = 500, color: str = "blue") -> Path:
    """Creates a sample test image with specified dimensions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=color)
    img.save(path, format="JPEG")
    return path


# ── 1. Video Metadata Service Tests ──

@pytest.mark.skipif(not is_ffmpeg_available(), reason="FFmpeg not available")
def test_video_metadata_probe_success(tmp_path):
    video_file = tmp_path / "test_1080p.mp4"
    generate_synthetic_video(video_file, width=1920, height=1080, duration=1.0, with_audio=True)

    meta_service = VideoMetadataService()
    meta = meta_service.probe(video_file)

    assert meta.width == 1920
    assert meta.height == 1080
    assert meta.duration > 0.8
    assert meta.has_audio is True
    assert meta.is_landscape is True
    assert meta.is_portrait is False
    assert meta.is_square is False
    assert meta.aspect_ratio == pytest.approx(16 / 9, 0.01)


def test_video_metadata_missing_file():
    meta_service = VideoMetadataService()
    with pytest.raises(VideoNotFoundError):
        meta_service.probe("/non/existent/video.mp4")


def test_video_metadata_corrupt_file(tmp_path):
    corrupt_file = tmp_path / "corrupt.mp4"
    corrupt_file.write_text("not a video content")

    meta_service = VideoMetadataService()
    with pytest.raises(InvalidVideoError):
        meta_service.probe(corrupt_file)


# ── 2. Font Manager & Typography Tests ──

def test_font_manager_resolution():
    name_font, user_font = FontManager.get_badge_fonts(name_size=32, username_size=24)
    assert name_font is not None
    assert user_font is not None


# ── 3. Profile Image Processing Tests ──

def test_profile_image_square_crop_and_circular_mask(tmp_path):
    # Test with a landscape image
    landscape_img = tmp_path / "landscape.jpg"
    create_sample_image(landscape_img, width=800, height=400, color="green")

    avatar = ProfileImageProcessor.create_circular_avatar(
        image_path=landscape_img,
        diameter=100,
        border_color="#FFFFFF",
        border_width=2,
    )

    assert avatar.size == (100, 100)
    assert avatar.mode == "RGBA"
    # Corner pixel should be transparent (0 alpha)
    corner_pixel = avatar.getpixel((0, 0))
    assert corner_pixel[3] == 0
    # Center pixel should be opaque (255 alpha)
    center_pixel = avatar.getpixel((50, 50))
    assert center_pixel[3] == 255


def test_profile_image_missing_raises_error():
    with pytest.raises(ProfileImageNotFoundError):
        ProfileImageProcessor.create_circular_avatar("/invalid/path/avatar.jpg", diameter=80)


# ── 4. Badge Renderer Tests ──

def test_badge_renderer_landscape(tmp_path):
    sample_img = tmp_path / "avatar.jpg"
    create_sample_image(sample_img, width=300, height=300, color="red")

    renderer = BadgeRenderer()
    badge = renderer.render(
        video_width=1920,
        video_height=1080,
        profile_image_path=sample_img,
        name="Alireza Nezami",
        username="alireza-nezami",
    )

    assert badge.mode == "RGBA"
    w, h = badge.size
    assert w > 200
    assert h > 40
    # Ensure badge has both opaque elements and transparent background
    assert badge.getextrema()[3][1] == 255  # Max alpha is 255


def test_badge_renderer_portrait_and_square(tmp_path):
    sample_img = tmp_path / "avatar.jpg"
    create_sample_image(sample_img, width=300, height=300)

    renderer = BadgeRenderer()

    # Portrait 1080x1920
    portrait_badge = renderer.render(
        video_width=1080,
        video_height=1920,
        profile_image_path=sample_img,
    )
    assert portrait_badge.size[0] > 150
    assert portrait_badge.size[1] > 30

    # Square 1080x1080
    square_badge = renderer.render(
        video_width=1080,
        video_height=1080,
        profile_image_path=sample_img,
    )
    assert square_badge.size[0] > 150
    assert square_badge.size[1] > 30


def test_badge_renderer_long_name_text_fitting(tmp_path):
    sample_img = tmp_path / "avatar.jpg"
    create_sample_image(sample_img, width=300, height=300)

    renderer = BadgeRenderer()
    long_badge = renderer.render(
        video_width=1920,
        video_height=1080,
        profile_image_path=sample_img,
        name="Dr. Alireza Bartholomew Christopher Nezami-Esq",
        username="alireza-nezami-long-handle-senior-architect",
    )

    assert long_badge.mode == "RGBA"
    assert long_badge.size[0] < 1920  # Never exceeds video width


# ── 5. End-to-End Video Processing Tests ──

@pytest.mark.skipif(not is_ffmpeg_available(), reason="FFmpeg not available")
def test_create_creator_badge_video_landscape(tmp_path):
    in_video = tmp_path / "input_1080p.mp4"
    out_video = tmp_path / "output_1080p.mp4"
    generate_synthetic_video(in_video, width=640, height=360, duration=1.0, with_audio=True)

    service = CreatorBadgeService()
    result = service.process_video(input_path=in_video, output_path=out_video)

    assert result.exists()
    assert result.stat().st_size > 1000

    # Verify output video metadata
    meta = service.metadata_service.probe(result)
    assert meta.width == 640
    assert meta.height == 360
    assert meta.has_audio is True


@pytest.mark.skipif(not is_ffmpeg_available(), reason="FFmpeg not available")
def test_create_creator_badge_video_no_audio(tmp_path):
    in_video = tmp_path / "input_silent.mp4"
    out_video = tmp_path / "output_silent.mp4"
    generate_synthetic_video(in_video, width=480, height=480, duration=1.0, with_audio=False)

    service = CreatorBadgeService()
    result = service.process_video(input_path=in_video, output_path=out_video)

    assert result.exists()
    meta = service.metadata_service.probe(result)
    assert meta.width == 480
    assert meta.height == 480
    assert meta.has_audio is False


@pytest.mark.skipif(not is_ffmpeg_available(), reason="FFmpeg not available")
def test_create_badge_preview_png(tmp_path):
    out_png = tmp_path / "badge_preview.png"
    result = create_badge_preview(output_path=out_png, target_resolution=(1920, 1080))

    assert result.exists()
    img = Image.open(result)
    assert img.mode == "RGBA"
    assert img.size[0] > 100


@pytest.mark.skipif(not is_ffmpeg_available(), reason="FFmpeg not available")
def test_generate_video_preview_short_clip(tmp_path):
    in_video = tmp_path / "input_long.mp4"
    out_video = tmp_path / "output_preview.mp4"
    generate_synthetic_video(in_video, width=640, height=360, duration=2.0, with_audio=True)

    result = generate_video_preview(input_path=in_video, output_path=out_video, duration=1.0)
    assert result.exists()
    service = VideoMetadataService()
    meta = service.probe(result)
    assert meta.duration <= 1.5


@pytest.mark.skipif(not is_ffmpeg_available(), reason="FFmpeg not available")
def test_batch_processing(tmp_path):
    v1 = tmp_path / "v1.mp4"
    v2 = tmp_path / "v2.mp4"
    out1 = tmp_path / "out1.mp4"
    out2 = tmp_path / "out2.mp4"

    generate_synthetic_video(v1, width=320, height=240, duration=0.5, with_audio=False)
    generate_synthetic_video(v2, width=320, height=240, duration=0.5, with_audio=False)

    service = CreatorBadgeService()
    results = service.process_batch([(v1, out1), (v2, out2)])

    assert len(results) == 2
    assert all(p.exists() and p.stat().st_size > 0 for p in results)


def test_missing_input_video_raises():
    service = CreatorBadgeService()
    with pytest.raises(VideoNotFoundError):
        service.process_video("/missing/video.mp4", "/out.mp4")


@pytest.mark.skipif(not is_ffmpeg_available(), reason="FFmpeg not available")
def test_cli_badge_only_mode(tmp_path):
    out_png = tmp_path / "cli_badge.png"
    from job_radar.cli.creator_badge_cmd import main
    import sys

    orig_argv = sys.argv
    try:
        sys.argv = ["job-radar-creator-badge", str(out_png), "--badge-only", "--target-res", "1080x1920"]
        main()
        assert out_png.exists()
        assert out_png.stat().st_size > 0
    finally:
        sys.argv = orig_argv


@pytest.mark.skipif(not is_ffmpeg_available(), reason="FFmpeg not available")
def test_create_creator_badge_video_odd_dimensions(tmp_path):
    # Tests odd dimensions (e.g. 641x361) which would normally cause libx264 error without padding
    in_video = tmp_path / "odd_input.mov"
    out_video = tmp_path / "odd_output.mp4"
    generate_synthetic_video(in_video, width=641, height=361, duration=0.5, with_audio=False)

    service = CreatorBadgeService()
    result = service.process_video(input_path=in_video, output_path=out_video)

    assert result.exists()
    meta = service.metadata_service.probe(result)
    assert meta.width % 2 == 0
    assert meta.height % 2 == 0



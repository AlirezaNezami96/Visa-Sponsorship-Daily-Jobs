"""Main Creator Badge Service providing standalone video processing and preview APIs."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple
from PIL import Image

from .config import CreatorBadgeConfig, DEFAULT_CONFIG
from .ffmpeg_service import FFmpegService
from .renderer import BadgeRenderer
from .video_metadata import VideoMetadataService

logger = logging.getLogger(__name__)


class CreatorBadgeService:
    """Orchestrates video inspection, dynamic badge rendering, and FFmpeg compositing."""

    def __init__(
        self,
        config: Optional[CreatorBadgeConfig] = None,
        metadata_service: Optional[VideoMetadataService] = None,
        renderer: Optional[BadgeRenderer] = None,
        ffmpeg_service: Optional[FFmpegService] = None,
    ):
        self.config = config or DEFAULT_CONFIG
        self.metadata_service = metadata_service or VideoMetadataService()
        self.renderer = renderer or BadgeRenderer(self.config)
        self.ffmpeg_service = ffmpeg_service or FFmpegService(config=self.config)

    def _apply_overrides(self, **kwargs: Any) -> CreatorBadgeConfig:
        """Returns a new config instance with runtime overrides applied."""
        if not kwargs:
            return self.config

        data = {
            "name": kwargs.get("name", self.config.name),
            "username": kwargs.get("username", self.config.username),
            "profile_image_path": kwargs.get("profile_image_path", self.config.profile_image_path),
            "badge_scale_ratio": kwargs.get("badge_scale_ratio", self.config.badge_scale_ratio),
            "right_margin_ratio": kwargs.get("right_margin_ratio", self.config.right_margin_ratio),
            "bottom_margin_ratio": kwargs.get("bottom_margin_ratio", self.config.bottom_margin_ratio),
            "badge_bg_color": kwargs.get("badge_bg_color", self.config.badge_bg_color),
            "name_color": kwargs.get("name_color", self.config.name_color),
            "username_color": kwargs.get("username_color", self.config.username_color),
            "remove_existing_badge": kwargs.get("remove_existing_badge", self.config.remove_existing_badge),
            "existing_badge_cover_color": kwargs.get("existing_badge_cover_color", self.config.existing_badge_cover_color),
            "video_codec": kwargs.get("video_codec", self.config.video_codec),
            "video_crf": kwargs.get("video_crf", self.config.video_crf),
            "video_preset": kwargs.get("video_preset", self.config.video_preset),
            "audio_codec": kwargs.get("audio_codec", self.config.audio_codec),
            "custom_font_path": kwargs.get("custom_font_path", self.config.custom_font_path),
        }
        return CreatorBadgeConfig(**data)

    def process_video(
        self,
        input_path: str | Path,
        output_path: str | Path,
        duration: Optional[float] = None,
        **kwargs: Any,
    ) -> Path:
        """
        Processes an input video and places the creator badge in the bottom-right corner.

        Args:
            input_path: Path to input video (MP4, MOV, WEBM, etc.)
            output_path: Path where processed video will be saved
            duration: Optional duration limit in seconds (useful for fast preview generation)
            **kwargs: Config overrides (name, username, profile_image_path, remove_existing_badge, etc.)

        Returns:
            Path to the output video.
        """
        effective_config = self._apply_overrides(**kwargs)
        effective_renderer = BadgeRenderer(effective_config)
        effective_ffmpeg = FFmpegService(config=effective_config)

        # 1. Probe input video metadata
        metadata = self.metadata_service.probe(input_path)
        logger.info(
            "Processing video %s: resolution=%dx%d, duration=%.2fs, fps=%.2f, has_audio=%s",
            input_path, metadata.width, metadata.height, metadata.duration, metadata.fps, metadata.has_audio
        )

        # 2. Render resolution-matched badge
        badge_img = effective_renderer.render(
            video_width=metadata.width,
            video_height=metadata.height,
            profile_image_path=effective_config.profile_image_path,
            name=effective_config.name,
            username=effective_config.username,
        )
        badge_w, badge_h = badge_img.size

        # 3. Save temporary badge PNG and run FFmpeg compositing with guaranteed cleanup
        with tempfile.TemporaryDirectory(prefix="creator_badge_") as tmp_dir:
            temp_overlay = Path(tmp_dir) / "badge_overlay.png"
            badge_img.save(temp_overlay, format="PNG")

            out_file = effective_ffmpeg.composite_badge(
                input_video_path=input_path,
                overlay_image_path=temp_overlay,
                output_video_path=output_path,
                metadata=metadata,
                badge_width=badge_w,
                badge_height=badge_h,
                duration=duration,
            )

        logger.info("Successfully produced badged video at: %s", out_file)
        return out_file

    def create_badge_preview(
        self,
        output_path: str | Path,
        target_resolution: Tuple[int, int] = (1920, 1080),
        **kwargs: Any,
    ) -> Path:
        """
        Generates and saves the creator badge as a transparent PNG for visual preview/tuning.

        Args:
            output_path: Destination path for PNG file
            target_resolution: (width, height) of reference video (e.g. 1920x1080, 1080x1920)
            **kwargs: Config overrides (name, username, profile_image_path, etc.)

        Returns:
            Path to the saved PNG preview.
        """
        effective_config = self._apply_overrides(**kwargs)
        effective_renderer = BadgeRenderer(effective_config)

        width, height = target_resolution
        badge_img = effective_renderer.render(
            video_width=width,
            video_height=height,
            profile_image_path=effective_config.profile_image_path,
            name=effective_config.name,
            username=effective_config.username,
        )

        out_file = Path(output_path).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        badge_img.save(out_file, format="PNG")
        logger.info("Saved badge preview image to: %s", out_file)
        return out_file

    def generate_video_preview(
        self,
        input_path: str | Path,
        output_path: str | Path,
        duration: float = 3.0,
        **kwargs: Any,
    ) -> Path:
        """
        Generates a quick short video preview (e.g. first 3 seconds) for visual inspection.
        """
        return self.process_video(input_path, output_path, duration=duration, **kwargs)

    def process_batch(
        self,
        videos: Sequence[Tuple[str | Path, str | Path]],
        **kwargs: Any,
    ) -> List[Path]:
        """
        Processes multiple videos in sequence.

        Args:
            videos: List of (input_video_path, output_video_path) tuples
            **kwargs: Config overrides

        Returns:
            List of generated output video paths.
        """
        results: List[Path] = []
        for in_p, out_p in videos:
            out = self.process_video(in_p, out_p, **kwargs)
            results.append(out)
        return results


# ── Top-level functional API ──

def create_creator_badge_video(
    input_path: str | Path,
    output_path: str | Path,
    profile_image_path: Optional[str | Path] = None,
    name: str = "Alireza Nezami",
    username: str = "alireza-nezami",
    remove_existing_badge: bool = True,
    **kwargs: Any,
) -> Path:
    """
    Convenience function to overlay creator badge on a video.

    Example:
        create_creator_badge_video(
            input_path="input.mp4",
            output_path="output.mp4",
            name="Alireza Nezami",
            username="alireza-nezami"
        )
    """
    service = CreatorBadgeService()
    return service.process_video(
        input_path=input_path,
        output_path=output_path,
        profile_image_path=profile_image_path,
        name=name,
        username=username,
        remove_existing_badge=remove_existing_badge,
        **kwargs,
    )


def create_badge_preview(
    output_path: str | Path,
    target_resolution: Tuple[int, int] = (1920, 1080),
    **kwargs: Any,
) -> Path:
    """Generates a standalone transparent PNG preview of the badge."""
    service = CreatorBadgeService()
    return service.create_badge_preview(
        output_path=output_path,
        target_resolution=target_resolution,
        **kwargs,
    )


def generate_video_preview(
    input_path: str | Path,
    output_path: str | Path,
    duration: float = 3.0,
    **kwargs: Any,
) -> Path:
    """Generates a quick short video preview clip with creator badge applied."""
    service = CreatorBadgeService()
    return service.generate_video_preview(
        input_path=input_path,
        output_path=output_path,
        duration=duration,
        **kwargs,
    )

"""FFmpeg execution and filter-graph orchestration service."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .config import CreatorBadgeConfig, DEFAULT_CONFIG
from .exceptions import FFmpegExecutionError, FFmpegNotFoundError
from .video_metadata import VideoMetadata


class FFmpegService:
    """Builds and executes FFmpeg video processing pipelines."""

    def __init__(
        self,
        ffmpeg_path: Optional[str] = None,
        config: Optional[CreatorBadgeConfig] = None,
    ):
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg"
        self.config = config or DEFAULT_CONFIG

    def check_ffmpeg_available(self) -> None:
        """Verifies that ffmpeg executable is available on system PATH."""
        if not shutil.which(self.ffmpeg_path):
            raise FFmpegNotFoundError("ffmpeg executable not found on system PATH. Please install FFmpeg.")

    def calculate_overlay_position(
        self,
        video_width: int,
        video_height: int,
        badge_width: int,
        badge_height: int,
    ) -> Tuple[int, int, int, int]:
        """Calculates (x, y) coordinates and margins for placing badge in bottom-right."""
        right_margin = max(10, int(video_width * self.config.right_margin_ratio))
        bottom_margin = max(10, int(video_height * self.config.bottom_margin_ratio))

        x = max(0, video_width - badge_width - right_margin)
        y = max(0, video_height - badge_height - bottom_margin)

        return x, y, right_margin, bottom_margin

    def build_filter_complex(
        self,
        video_width: int,
        video_height: int,
        badge_width: int,
        badge_height: int,
    ) -> str:
        """Constructs FFmpeg filter complex string covering old badge and overlaying new badge."""
        x, y, right_m, bottom_m = self.calculate_overlay_position(
            video_width, video_height, badge_width, badge_height
        )

        if self.config.remove_existing_badge:
            pad = int(min(video_width, video_height) * self.config.existing_badge_cover_padding_ratio)
            cover_x = max(0, x - pad)
            cover_y = max(0, y - pad)
            cover_w = video_width - cover_x
            cover_h = video_height - cover_y
            color = self.config.existing_badge_cover_color

            # Drawbox over old watermark area, then overlay new badge and ensure even dimensions
            filter_str = (
                f"[0:v]drawbox=x={cover_x}:y={cover_y}:w={cover_w}:h={cover_h}:color={color}:t=fill[covered];"
                f"[covered][1:v]overlay=x={x}:y={y}[out_overlay];"
                f"[out_overlay]pad=ceil(iw/2)*2:ceil(ih/2)*2[outv]"
            )
        else:
            filter_str = f"[0:v][1:v]overlay=x={x}:y={y}[out_overlay];[out_overlay]pad=ceil(iw/2)*2:ceil(ih/2)*2[outv]"

        return filter_str

    def composite_badge(
        self,
        input_video_path: str | Path,
        overlay_image_path: str | Path,
        output_video_path: str | Path,
        metadata: VideoMetadata,
        badge_width: int,
        badge_height: int,
        duration: Optional[float] = None,
    ) -> Path:
        """Executes FFmpeg to composite the badge onto the input video."""
        self.check_ffmpeg_available()

        in_video = Path(input_video_path).resolve()
        in_overlay = Path(overlay_image_path).resolve()
        out_video = Path(output_video_path).resolve()

        # Ensure output directory exists
        out_video.parent.mkdir(parents=True, exist_ok=True)

        filter_complex = self.build_filter_complex(
            metadata.width, metadata.height, badge_width, badge_height
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", str(in_video),
            "-i", str(in_overlay),
            "-filter_complex", filter_complex,
            "-map", "[outv]",
        ]

        if metadata.has_audio:
            cmd.extend(["-map", "0:a?", "-c:a", self.config.audio_codec])

        cmd.extend([
            "-c:v", self.config.video_codec,
            "-crf", str(self.config.video_crf),
            "-preset", self.config.video_preset,
            "-pix_fmt", self.config.pix_fmt,
            "-movflags", "+faststart",
        ])

        if duration and duration > 0:
            cmd.extend(["-t", str(duration)])

        cmd.append(str(out_video))

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except Exception as e:
            raise FFmpegExecutionError(f"Failed to launch FFmpeg: {e}") from e

        if res.returncode != 0:
            raise FFmpegExecutionError(
                f"FFmpeg processing failed (exit code {res.returncode}):\n{res.stderr.strip()}"
            )

        if not out_video.exists() or out_video.stat().st_size == 0:
            raise FFmpegExecutionError(f"FFmpeg completed but output file is missing or empty: {out_video}")

        return out_video

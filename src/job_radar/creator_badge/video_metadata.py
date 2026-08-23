"""Video metadata inspection service utilizing ffprobe."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .exceptions import FFmpegNotFoundError, InvalidVideoError, VideoNotFoundError


@dataclass
class VideoMetadata:
    """Inspected properties of an input video file."""
    width: int
    height: int
    duration: float
    fps: float
    has_audio: bool
    codec_name: str
    aspect_ratio: float

    @property
    def is_portrait(self) -> bool:
        return self.height > self.width

    @property
    def is_landscape(self) -> bool:
        return self.width > self.height

    @property
    def is_square(self) -> bool:
        return self.width == self.height


class VideoMetadataService:
    """Service to inspect and extract video technical parameters."""

    def __init__(self, ffprobe_path: Optional[str] = None):
        self.ffprobe_path = ffprobe_path or shutil.which("ffprobe") or "ffprobe"

    def probe(self, video_path: str | Path) -> VideoMetadata:
        """Inspects the input video file and returns a VideoMetadata instance."""
        path_obj = Path(video_path)
        if not path_obj.exists():
            raise VideoNotFoundError(f"Input video not found: {video_path}")

        # Check ffprobe availability
        if not shutil.which(self.ffprobe_path):
            raise FFmpegNotFoundError("ffprobe executable not found on system PATH. Please install FFmpeg.")

        cmd = [
            self.ffprobe_path,
            "-v", "error",
            "-show_entries", "stream=width,height,r_frame_rate,codec_type,codec_name,duration:format=duration",
            "-of", "json",
            str(path_obj.resolve()),
        ]

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=30,
            )
        except Exception as e:
            raise InvalidVideoError(f"Failed to execute ffprobe on '{video_path}': {e}") from e

        if res.returncode != 0:
            raise InvalidVideoError(f"ffprobe error for '{video_path}': {res.stderr.strip()}")

        try:
            data: Dict[str, Any] = json.loads(res.stdout)
        except json.JSONDecodeError as e:
            raise InvalidVideoError(f"Malformed ffprobe JSON output for '{video_path}': {e}") from e

        streams = data.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not video_stream:
            raise InvalidVideoError(f"No video stream found in '{video_path}'")

        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        if width <= 0 or height <= 0:
            raise InvalidVideoError(f"Invalid video dimensions ({width}x{height}) in '{video_path}'")

        # Parse FPS
        fps_str = video_stream.get("r_frame_rate", "30/1")
        fps = 30.0
        if "/" in fps_str:
            num, den = fps_str.split("/", 1)
            try:
                den_f = float(den)
                if den_f > 0:
                    fps = float(num) / den_f
            except (ValueError, ZeroDivisionError):
                fps = 30.0
        else:
            try:
                fps = float(fps_str)
            except ValueError:
                fps = 30.0

        # Parse Duration
        duration = 0.0
        dur_str = video_stream.get("duration") or data.get("format", {}).get("duration")
        if dur_str:
            try:
                duration = float(dur_str)
            except ValueError:
                duration = 0.0

        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        codec_name = video_stream.get("codec_name", "unknown")
        aspect_ratio = width / height

        return VideoMetadata(
            width=width,
            height=height,
            duration=duration,
            fps=fps,
            has_audio=has_audio,
            codec_name=codec_name,
            aspect_ratio=aspect_ratio,
        )

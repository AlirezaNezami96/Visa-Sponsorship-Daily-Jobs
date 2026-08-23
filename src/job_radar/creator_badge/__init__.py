"""Creator Badge Overlay Package.

Provides standalone, production-ready services and utilities for automatically
placing or replacing a polished creator badge on social-media and technical videos.
"""
from __future__ import annotations

from .config import CreatorBadgeConfig, DEFAULT_CONFIG
from .exceptions import (
    CreatorBadgeError,
    FFmpegExecutionError,
    FFmpegNotFoundError,
    FontNotFoundError,
    InvalidVideoError,
    ProfileImageNotFoundError,
    VideoNotFoundError,
)
from .ffmpeg_service import FFmpegService
from .font_manager import FontManager
from .image_processor import ProfileImageProcessor
from .renderer import BadgeRenderer
from .service import (
    CreatorBadgeService,
    create_badge_preview,
    create_creator_badge_video,
    generate_video_preview,
)
from .video_metadata import VideoMetadata, VideoMetadataService

__all__ = [
    "CreatorBadgeService",
    "create_creator_badge_video",
    "create_badge_preview",
    "generate_video_preview",
    "CreatorBadgeConfig",
    "DEFAULT_CONFIG",
    "VideoMetadata",
    "VideoMetadataService",
    "ProfileImageProcessor",
    "FontManager",
    "BadgeRenderer",
    "FFmpegService",
    "CreatorBadgeError",
    "VideoNotFoundError",
    "InvalidVideoError",
    "ProfileImageNotFoundError",
    "FFmpegNotFoundError",
    "FFmpegExecutionError",
    "FontNotFoundError",
]

"""Custom exceptions for the Creator Badge Service."""
from __future__ import annotations


class CreatorBadgeError(Exception):
    """Base exception for all creator badge service errors."""
    pass


class VideoNotFoundError(CreatorBadgeError):
    """Raised when the input video file does not exist."""
    pass


class InvalidVideoError(CreatorBadgeError):
    """Raised when the input video is corrupt or cannot be decoded."""
    pass


class ProfileImageNotFoundError(CreatorBadgeError):
    """Raised when the candidate profile image cannot be found."""
    pass


class FFmpegNotFoundError(CreatorBadgeError):
    """Raised when ffmpeg or ffprobe executable is not found on PATH."""
    pass


class FFmpegExecutionError(CreatorBadgeError):
    """Raised when ffmpeg execution fails."""
    pass


class FontNotFoundError(CreatorBadgeError):
    """Raised when no suitable font could be loaded."""
    pass

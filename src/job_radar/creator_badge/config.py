"""Centralized configuration for the Video Creator Badge Overlay Service."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def get_default_profile_image_path() -> str:
    """Finds the default profile image within the repository."""
    # Look for candidate profile image in assets/samples
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    candidate_paths = [
        repo_root / "assets" / "samples" / "ChatGPT Image Aug 11, 2026, 01_48_27 PM.jpg",
        repo_root / "assets" / "samples" / "exact_user_prompt_post.jpg",
    ]
    for p in candidate_paths:
        if p.exists():
            return str(p)

    # Fallback to search assets directory
    assets_dir = repo_root / "assets" / "samples"
    if assets_dir.exists():
        for file in assets_dir.glob("*.jpg"):
            return str(file)
        for file in assets_dir.glob("*.png"):
            return str(file)

    return ""


@dataclass
class CreatorBadgeConfig:
    """Configuration options for rendering and compositing the creator badge."""

    # Candidate Identity
    name: str = "Alireza Nezami"
    username: str = "alireza-nezami"
    profile_image_path: str = field(default_factory=get_default_profile_image_path)

    # Dimensional Ratios relative to video dimensions
    # Base width scale relative to reference minimum video dimension
    badge_scale_ratio: float = 0.26
    right_margin_ratio: float = 0.025
    bottom_margin_ratio: float = 0.035

    # Visual Appearance
    badge_bg_color: str = "#FFFFFF"
    badge_corner_radius_ratio: float = 0.5  # Fully rounded pill
    name_color: str = "#141414"
    username_color: str = "#666666"
    avatar_border_color: str = "#FFFFFF"
    avatar_border_width_ratio: float = 0.04

    # Existing Badge Cover Settings
    remove_existing_badge: bool = True
    existing_badge_cover_color: str = "black@1.0"
    existing_badge_cover_padding_ratio: float = 0.05

    # Video Encoding Settings
    video_codec: str = "libx264"
    video_crf: int = 18
    video_preset: str = "medium"
    audio_codec: str = "copy"
    pix_fmt: str = "yuv420p"

    # Font Settings
    custom_font_path: Optional[str] = None


DEFAULT_CONFIG = CreatorBadgeConfig()

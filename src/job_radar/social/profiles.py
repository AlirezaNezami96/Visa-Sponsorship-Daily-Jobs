"""Declarative platform profiles, cadence configurations, and formatting rules.

Platform profiles define:
- Content Tier (Tier 1: raw batched feed; Tier 2/3: single curated job / insight; Tier 4: long-form article)
- Character & byte constraints
- Output format (markdown_v2, embed_json, plain_text, professional_text, etc.)
- Emoji palettes and density
- Cadence rules with randomized jitter percentages and daily post budgets
- Link placement strategies
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CadenceConfig:
    """Posting cadence, daily quotas, active hours, and randomized jitter."""
    mode: str  # "batch_window" | "fixed_daily_count" | "weekly"
    interval_minutes: float = 60.0
    posts_per_day: int = 10
    posts_per_week: int = 2
    active_hours: tuple[int, int] = (0, 24)  # (start_hour_utc, end_hour_utc)
    jitter_pct: float = 25.0
    max_posts_per_day: int = 10


@dataclass(frozen=True)
class PlatformProfile:
    """Data-driven profile governing a platform's formatting and publication rules."""
    name: str
    tier: int  # 1 (batch feed), 2 (single/insight), 3 (insight), 4 (article)
    char_limit: int
    target_length: str
    format: str  # "markdown_v2" | "embed_json" | "plain_text" | "professional_text" | "short_text_or_thread" | "plain_text_with_hashtags" | "markdown_article"
    batch: bool
    max_jobs_per_post: int
    cadence: CadenceConfig
    emoji_density: str  # "high" | "structured" | "low" | "none"
    emoji_palette: list[str]
    include_link_inline: bool
    link_strategy: str  # "inline_markdown" | "embed_url" | "bio_reference" | "plain_inline" | "short_link" | "plain_with_hashtags" | "article_canonical"
    max_image_bytes: int | None = None
    extra_settings: dict[str, Any] = field(default_factory=dict)


# Master Platform Profiles (Part 2 & Part 3 Specifications)
PLATFORM_PROFILES: dict[str, PlatformProfile] = {
    "telegram": PlatformProfile(
        name="telegram",
        tier=1,
        char_limit=4096,
        target_length="300-600",
        format="markdown_v2",
        batch=True,
        max_jobs_per_post=5,
        cadence=CadenceConfig(
            mode="batch_window",
            interval_minutes=20.0,
            posts_per_day=72,
            active_hours=(0, 24),
            jitter_pct=25.0,
            max_posts_per_day=72,
        ),
        emoji_density="high",
        emoji_palette=["🌍", "🛂", "💼", "📍", "💰", "🔗", "🆕", "✅", "🔥", "📌"],
        include_link_inline=True,
        link_strategy="inline_markdown",
        max_image_bytes=10_000_000,
        extra_settings={"max_prompt_chars": 3800},
    ),
    "discord": PlatformProfile(
        name="discord",
        tier=1,
        char_limit=4096,
        target_length="200-400",
        format="embed_json",
        batch=True,
        max_jobs_per_post=4,
        cadence=CadenceConfig(
            mode="batch_window",
            interval_minutes=30.0,
            posts_per_day=48,
            active_hours=(0, 24),
            jitter_pct=25.0,
            max_posts_per_day=48,
        ),
        emoji_density="structured",
        emoji_palette=["🟢", "🟡", "🔴", "🌍", "💼", "📍", "💰"],
        include_link_inline=True,
        link_strategy="embed_url",
        max_image_bytes=8_000_000,
        extra_settings={"embed_description_limit": 4096, "field_value_limit": 1024},
    ),
    "x": PlatformProfile(
        name="x",
        tier=2,
        char_limit=280,
        target_length="200-260",
        format="plain_text",
        batch=False,
        max_jobs_per_post=1,
        cadence=CadenceConfig(
            mode="fixed_daily_count",
            interval_minutes=270.0,  # ~4.5 hours
            posts_per_day=4,
            active_hours=(8, 22),
            jitter_pct=30.0,
            max_posts_per_day=4,
        ),
        emoji_density="low",
        emoji_palette=["🌍", "💼", "📍"],
        include_link_inline=False,
        link_strategy="bio_reference",
        max_image_bytes=5_000_000,
        extra_settings={"max_target_chars": 260, "max_emojis": 2, "max_hashtags": 1},
    ),
    "linkedin": PlatformProfile(
        name="linkedin",
        tier=2,
        char_limit=3000,
        target_length="600-900",
        format="professional_text",
        batch=False,
        max_jobs_per_post=1,
        cadence=CadenceConfig(
            mode="fixed_daily_count",
            interval_minutes=600.0,  # ~10 hours
            posts_per_day=2,
            active_hours=(7, 19),
            jitter_pct=20.0,
            max_posts_per_day=2,
        ),
        emoji_density="low",
        emoji_palette=["📍", "💼", "✅"],
        include_link_inline=True,
        link_strategy="plain_inline",
        max_image_bytes=10_000_000,
        extra_settings={"max_emojis": 3, "profile_type": "personal"},
    ),
    "bluesky": PlatformProfile(
        name="bluesky",
        tier=2,
        char_limit=300,
        target_length="220-280",
        format="short_text_or_thread",
        batch=False,
        max_jobs_per_post=1,
        cadence=CadenceConfig(
            mode="fixed_daily_count",
            interval_minutes=210.0,  # ~3.5 hours
            posts_per_day=6,
            active_hours=(7, 22),
            jitter_pct=25.0,
            max_posts_per_day=6,
        ),
        emoji_density="low",
        emoji_palette=["🌍", "💼", "📍", "💰"],
        include_link_inline=True,
        link_strategy="short_link",
        max_image_bytes=1_000_000,
        extra_settings={"max_bytes": 3000, "max_emojis": 2, "thread_separator": "|||THREAD|||"},
    ),
    "mastodon": PlatformProfile(
        name="mastodon",
        tier=2,
        char_limit=500,
        target_length="350-480",
        format="plain_text_with_hashtags",
        batch=False,
        max_jobs_per_post=1,
        cadence=CadenceConfig(
            mode="fixed_daily_count",
            interval_minutes=330.0,  # ~5.5 hours
            posts_per_day=4,
            active_hours=(7, 22),
            jitter_pct=25.0,
            max_posts_per_day=4,
        ),
        emoji_density="low",
        emoji_palette=["🌍", "💼", "📍"],
        include_link_inline=True,
        link_strategy="plain_with_hashtags",
        max_image_bytes=8_000_000,
        extra_settings={"max_emojis": 2, "min_hashtags": 2, "max_hashtags": 4, "bot_flag": True},
    ),
    "devto": PlatformProfile(
        name="devto",
        tier=4,
        char_limit=25000,
        target_length="600-1000 words",
        format="markdown_article",
        batch=False,
        max_jobs_per_post=0,  # 0 indicates article mode only, never individual job listings
        cadence=CadenceConfig(
            mode="weekly",
            interval_minutes=3024.0,  # ~2.1 days
            posts_per_day=1,
            posts_per_week=2,
            active_hours=(6, 23),
            jitter_pct=15.0,
            max_posts_per_day=1,
        ),
        emoji_density="none",
        emoji_palette=[],
        include_link_inline=True,
        link_strategy="article_canonical",
        max_image_bytes=10_000_000,
        extra_settings={"min_words": 600, "max_words": 1000, "body_emoji_allowed": False},
    ),
}


def get_profile(platform: str) -> PlatformProfile:
    """Retrieve platform profile by name; raises KeyError on unknown platform."""
    key = platform.lower().strip()
    if key not in PLATFORM_PROFILES:
        raise KeyError(f"Unknown social platform '{platform}'. Available: {list(PLATFORM_PROFILES.keys())}")
    return PLATFORM_PROFILES[key]

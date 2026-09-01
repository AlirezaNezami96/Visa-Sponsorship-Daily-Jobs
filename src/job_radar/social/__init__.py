"""Social subpackage for job_radar with independent platform-native generation & publishing."""
from __future__ import annotations

from job_radar.social.adapters import (
    ADAPTER_REGISTRY,
    BlueskyAdapter,
    DevtoAdapter,
    DiscordAdapter,
    LinkedInAdapter,
    MastodonAdapter,
    PlatformAdapter,
    PublishResult,
    TelegramAdapter,
    XAdapter,
    extract_emojis,
    get_adapter,
    log_post_event,
)
from job_radar.social.profiles import (
    PLATFORM_PROFILES,
    CadenceConfig,
    PlatformProfile,
    get_profile,
)
from job_radar.social.scheduler import (
    CrossPlatformStaggerQueue,
    DailyBudgetTracker,
    PlatformDeduplicator,
    next_post_time,
)
from job_radar.social.tier_router import (
    RoutingError,
    validate_tier_routing,
)

__all__ = [
    "ADAPTER_REGISTRY",
    "PLATFORM_PROFILES",
    "BlueskyAdapter",
    "CadenceConfig",
    "CrossPlatformStaggerQueue",
    "DailyBudgetTracker",
    "DevtoAdapter",
    "DiscordAdapter",
    "LinkedInAdapter",
    "MastodonAdapter",
    "PlatformAdapter",
    "PlatformDeduplicator",
    "PlatformProfile",
    "PublishResult",
    "RoutingError",
    "TelegramAdapter",
    "XAdapter",
    "extract_emojis",
    "get_adapter",
    "get_profile",
    "log_post_event",
    "next_post_time",
    "validate_tier_routing",
]

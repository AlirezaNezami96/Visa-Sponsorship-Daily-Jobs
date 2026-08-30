"""Kill switch and multi-gate publishing control.

Guards every social publish operation behind 3 distinct gates:
1. Global Kill Switch (`SOCIAL_PUBLISHING_ENABLED=true`) - Default: false
2. Dry Run Flag (`PUBLISH_DRY_RUN=false`) - Default: true
3. Database Flag (`platform_post_config.enabled=true`) - Default: false
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def global_enabled() -> bool:
    """Check if the global publishing kill switch is enabled (Default: False)."""
    val = os.getenv("SOCIAL_PUBLISHING_ENABLED", "false").strip().lower()
    return val in ("1", "true", "yes", "on")


def dry_run() -> bool:
    """Check if publishing is in dry-run mode (Default: True)."""
    val = os.getenv("PUBLISH_DRY_RUN", "true").strip().lower()
    return val in ("1", "true", "yes", "on")


def platform_enabled(client: Any, platform: str) -> bool:
    """Check if the specific platform is enabled in platform_post_config table."""
    try:
        resp = (
            client.table("platform_post_config")
            .select("enabled")
            .eq("platform", platform)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            return bool(resp.data.get("enabled", False))
    except Exception as e:
        logger.warning("Failed to read platform_post_config for %s: %s", platform, e)
    return False


def can_publish(client: Any, platform: str) -> tuple[bool, str]:
    """Verify all publishing gates before making any live network calls."""
    if not global_enabled():
        return False, "global kill switch off (SOCIAL_PUBLISHING_ENABLED!=true)"
    if not platform_enabled(client, platform):
        return False, f"{platform} disabled in platform_post_config"
    return True, "ok"

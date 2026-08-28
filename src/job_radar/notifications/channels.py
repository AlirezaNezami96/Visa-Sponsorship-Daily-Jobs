"""Non-email notification channels: Telegram, Discord, Slack.

Follows the `email.py` provider-abstraction pattern: each channel has a
`send_<channel>` helper reading credentials from env, failing safely with a
warning when unconfigured. A `broadcast` helper fans a message out to every
configured channel (auto-post targets per master plan section 6.4).

LinkedIn and X are intentionally NOT here — they route to the social
manual-review queue instead of auto-posting.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

import requests

logger = logging.getLogger(__name__)


def send_telegram(text: str, *, chat_id: str | None = None, bot_token: str | None = None) -> bool:
    """Send a plain-text message via the Telegram Bot API."""
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    target = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not target:
        logger.debug("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set — skipping Telegram send.")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": target, "text": text[:4096], "disable_web_page_preview": True},
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False


def send_discord(text: str, *, webhook_url: str | None = None) -> bool:
    """Send a message to a Discord webhook (2000-char limit, split safely)."""
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        logger.debug("DISCORD_WEBHOOK_URL not set — skipping Discord send.")
        return False
    try:
        for chunk in _chunk(text, 2000):
            r = requests.post(url, json={"content": chunk}, timeout=15)
            r.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Discord send failed: %s", exc)
        return False


def send_slack(text: str, *, webhook_url: str | None = None) -> bool:
    """Send a message to a Slack incoming webhook."""
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        logger.debug("SLACK_WEBHOOK_URL not set — skipping Slack send.")
        return False
    try:
        r = requests.post(url, json={"text": text[:39000]}, timeout=15)
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Slack send failed: %s", exc)
        return False


def _chunk(text: str, limit: int) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [""]


CHANNELS: dict[str, Callable[[str], bool]] = {
    "telegram": lambda text: send_telegram(text),
    "discord": lambda text: send_discord(text),
    "slack": lambda text: send_slack(text),
}


def broadcast(text: str, channels: list[str] | None = None) -> dict[str, bool]:
    """Send `text` to the requested channels (default: all configured).

    Returns {channel: success}. Never raises.
    """
    targets = channels or list(CHANNELS.keys())
    results: dict[str, bool] = {}
    for name in targets:
        sender = CHANNELS.get(name)
        if sender is None:
            logger.warning("Unknown notification channel '%s'", name)
            results[name] = False
            continue
        results[name] = bool(sender(text))
    return results

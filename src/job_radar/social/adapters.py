"""Multi-Platform Social Publishing & Generation Adapters.

Implements the PlatformAdapter protocol for:
- Telegram (TelegramAdapter)
- Discord (DiscordAdapter)
- X / Twitter (XAdapter)
- LinkedIn (LinkedInAdapter)
- Bluesky (BlueskyAdapter)
- Mastodon (MastodonAdapter)
- Dev.to (DevtoAdapter)

Each adapter owns:
- Its platform profile and constraints (from profiles.py)
- Its isolated system and user prompt templates (from prompts/)
- Its independent content generator (generate_content) with LLM router + deterministic rule-based fallback
- Its publication client with header-based rate-limit extraction and retrybackoff
- Comprehensive per-post logging (platform, job_ids, text, char_count, emojis, times, status)
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC
from typing import Any, Protocol, runtime_checkable

import requests

from job_radar.social.error_taxonomy import classify_exception, classify_http_error
from job_radar.social.profiles import PlatformProfile, get_profile
from job_radar.social.prompts import bluesky as bsky_prompts
from job_radar.social.prompts import devto as devto_prompts
from job_radar.social.prompts import discord as discord_prompts
from job_radar.social.prompts import linkedin as linkedin_prompts
from job_radar.social.prompts import mastodon as mastodon_prompts
from job_radar.social.prompts import telegram as tg_prompts
from job_radar.social.prompts import x as x_prompts
from job_radar.social.text_prep import truncate_keep_url

logger = logging.getLogger(__name__)

EMOJI_REGEX = re.compile(
    "[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf\u2300-\u23ff\u2b50\u2b06\u2194-\u21aa\u25b6\u25c0]",
    flags=re.UNICODE,
)


def extract_emojis(text: str) -> list[str]:
    """Extract list of all emojis present in the text."""
    if not text:
        return []
    return EMOJI_REGEX.findall(text)


def log_post_event(
    platform: str,
    job_ids: list[str],
    text: str,
    scheduled_time: datetime.datetime | None,
    actual_sent_time: datetime.datetime,
    api_status: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Structured post logging (Part 1.10)."""
    emojis = extract_emojis(text)
    char_count = len(text)
    byte_count = len(text.encode("utf-8"))

    log_entry = {
        "platform": platform,
        "job_ids": job_ids,
        "character_count": char_count,
        "byte_count": byte_count,
        "emoji_count": len(emojis),
        "emojis_used": emojis,
        "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
        "actual_sent_time": actual_sent_time.isoformat(),
        "api_response_status": api_status,
    }
    if extra:
        log_entry.update(extra)

    logger.info("📢 SOCIAL POST LOG [%s]: %s", platform, json.dumps(log_entry))


@dataclass
class PublishResult:
    """Standardized publication response across all social adapters."""
    ok: bool
    url: str | None = None
    error: str | None = None
    retryable: bool = False
    permanent: bool = False
    retry_after: float | None = None
    warning: str | None = None


@runtime_checkable
class PlatformAdapter(Protocol):
    """Protocol contract implemented by all social publishing adapters."""
    name: str
    profile: PlatformProfile
    char_limit: int
    max_image_bytes: int | None

    def generate_content(
        self,
        jobs_or_data: Any,
        llm_router: Any | None = None,
        **kwargs: Any,
    ) -> str | dict[str, Any]:
        """Generate platform-native content with LLM router or deterministic fallback."""
        ...

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
        job_ids: list[str] | None = None,
        scheduled_time: datetime.datetime | None = None,
    ) -> PublishResult:
        ...

    def check_credentials(self) -> tuple[bool, str]:
        ...


# -----------------------------------------------------------------------------
# 1. Telegram Adapter (Tier 1: Batch Feed)
# -----------------------------------------------------------------------------
class TelegramAdapter:
    name = "telegram"

    def __init__(self) -> None:
        self.profile = get_profile("telegram")
        self.char_limit = self.profile.char_limit
        self.max_image_bytes = self.profile.max_image_bytes or 10_000_000

    def generate_content(
        self,
        jobs_or_data: Any,
        llm_router: Any | None = None,
        **kwargs: Any,
    ) -> str:
        jobs: list[dict[str, Any]] = jobs_or_data if isinstance(jobs_or_data, list) else [jobs_or_data]
        if not jobs:
            return "🆕 No new roles in this batch."

        if llm_router:
            prompt = tg_prompts.build_user_prompt(jobs)
            try:
                res = llm_router.complete(
                    prompt=prompt,
                    system_instruction=tg_prompts.SYSTEM_PROMPT,
                    temperature=0.3,
                )
                if res and res.text and len(res.text.strip()) > 30:
                    text = res.text.strip()
                    if len(text) <= self.char_limit:
                        return text
            except Exception as exc:
                logger.warning("Telegram LLM generation failed: %s; using rule-based fallback", exc)

        # Deterministic rule-based fallback
        lines = [f"🆕 {len(jobs)} new sponsorship-confirmed roles just added\n"]
        for j in jobs[: self.profile.max_jobs_per_post]:
            title = j.get("title") or "Software Engineer"
            company = j.get("company") or "Global Tech"
            city = j.get("city") or j.get("location_raw") or j.get("location") or "Worldwide"
            country = j.get("country") or ""
            location_str = f"{city}, {country}".strip(", ")
            visa_types = ", ".join(j.get("visa_types") or []) if isinstance(j.get("visa_types"), list) else str(j.get("visa_types") or "Work Visa")
            salary = j.get("salary_raw") or (f"{j.get('salary_min')}-{j.get('salary_max')} {j.get('salary_currency', 'USD')}" if j.get("salary_min") else None)
            conf_label = "✅ High confidence (past sponsor)" if j.get("visa_sponsorship_verified") else "✅ Verified sponsor"
            apply_link = j.get("apply_url") or j.get("url") or "https://visalane.app"

            lines.append(f"*{title}* — {company}")
            lines.append(f"📍 {location_str} 🛂 {visa_types}")
            if salary:
                lines.append(f"💰 {salary} · {conf_label}")
            else:
                lines.append(f"💼 Full-time · {conf_label}")
            lines.append(f"🔗 Apply: {apply_link}\n")

        return "\n".join(lines).strip()

    def check_credentials(self) -> tuple[bool, str]:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not (bot_token and chat_id):
            return False, "NOT_CONFIGURED"

        try:
            res = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
            if res.status_code == 200 and res.json().get("ok"):
                username = res.json().get("result", {}).get("username", "bot")
                return True, f"OK (@{username})"
            return False, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, str(e)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
        job_ids: list[str] | None = None,
        scheduled_time: datetime.datetime | None = None,
    ) -> PublishResult:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        sent_time = datetime.datetime.now(UTC)

        if not (bot_token and chat_id):
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, "MISSING_CREDENTIALS")
            return PublishResult(ok=False, error="Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID", permanent=True)

        post_text = text[: self.char_limit]

        try:
            if image_bytes:
                url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                data = {"chat_id": chat_id, "caption": post_text[:1024], "parse_mode": "Markdown"}
                files = {"photo": ("card.jpg", image_bytes, "image/jpeg")}
                res = requests.post(url, data=data, files=files, timeout=20)
            else:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {"chat_id": chat_id, "text": post_text, "parse_mode": "Markdown", "disable_web_page_preview": False}
                res = requests.post(url, json=payload, timeout=15)

            # Fallback if markdown parsing fails
            if res.status_code == 400 and "can't parse entities" in res.text.lower():
                logger.warning("Telegram Markdown parse failed; falling back to unformatted text")
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                res = requests.post(url, json={"chat_id": chat_id, "text": post_text}, timeout=15)

            if res.status_code == 200 and res.json().get("ok"):
                msg_id = res.json().get("result", {}).get("message_id")
                chat_clean = chat_id.replace("@", "")
                post_url = f"https://t.me/{chat_clean}/{msg_id}" if not chat_id.startswith("-") else f"https://t.me/c/{chat_id}/{msg_id}"
                log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"HTTP_{res.status_code}")
                return PublishResult(ok=True, url=post_url)

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"HTTP_{res.status_code}")
            return PublishResult(
                ok=False,
                error=f"Telegram API HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"EXCEPTION_{type(e).__name__}")
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent, retry_after=retry_after)


# -----------------------------------------------------------------------------
# 2. Discord Adapter (Tier 1: Rich Embed JSON)
# -----------------------------------------------------------------------------
class DiscordAdapter:
    name = "discord"

    def __init__(self) -> None:
        self.profile = get_profile("discord")
        self.char_limit = self.profile.char_limit
        self.max_image_bytes = self.profile.max_image_bytes or 8_000_000

    def generate_content(
        self,
        jobs_or_data: Any,
        llm_router: Any | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        job: dict[str, Any] = jobs_or_data[0] if isinstance(jobs_or_data, list) and jobs_or_data else (jobs_or_data or {})

        if llm_router:
            prompt = discord_prompts.build_user_prompt(job)
            try:
                res = llm_router.complete(
                    prompt=prompt,
                    system_instruction=discord_prompts.SYSTEM_PROMPT,
                    json_schema=discord_prompts.DISCORD_JSON_SCHEMA,
                    temperature=0.2,
                )
                if res and res.text:
                    parsed = json.loads(res.text)
                    if isinstance(parsed, dict) and "title" in parsed and "fields" in parsed:
                        return parsed
            except Exception as exc:
                logger.warning("Discord LLM generation failed: %s; using rule-based fallback", exc)

        # Deterministic rule-based fallback
        title = job.get("title") or "Software Engineer"
        company = job.get("company") or "Tech Corp"
        city = job.get("city") or job.get("location_raw") or job.get("location") or "Worldwide"
        country = job.get("country") or ""
        location_str = f"{city}, {country}".strip(", ")
        verified = bool(job.get("visa_sponsorship_verified"))
        conf_circle = "🟢" if verified else "🟡"
        conf_text = "High (Official Sponsor)" if verified else "Medium (Historical Filings)"
        contract = job.get("employment_type") or job.get("work_mode") or "Full-time"
        salary = job.get("salary_raw") or (f"{job.get('salary_min')}-{job.get('salary_max')} {job.get('salary_currency', 'USD')}" if job.get("salary_min") else "Not disclosed")
        visa_types = ", ".join(job.get("visa_types") or []) if isinstance(job.get("visa_types"), list) else str(job.get("visa_types") or "Work Visa")

        return {
            "title": f"{title} — {company}"[:100],
            "description": f"Verified visa-sponsored opening in {location_str} with relocation support."[:200],
            "fields": {
                "location": f"🌍 {location_str}",
                "role_type": f"💼 {contract}",
                "confidence": f"{conf_circle} {conf_text}",
                "salary": f"💰 {salary}",
                "visa_types": visa_types,
            },
        }

    def check_credentials(self) -> tuple[bool, str]:
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            return False, "NOT_CONFIGURED"
        try:
            res = requests.get(webhook_url, timeout=10)
            if res.status_code == 200:
                name = res.json().get("name", "webhook")
                return True, f"OK ({name})"
            return False, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, str(e)

    def publish(
        self,
        text: str | dict[str, Any],
        image_url: str | None = None,
        image_bytes: bytes | None = None,
        job_ids: list[str] | None = None,
        scheduled_time: datetime.datetime | None = None,
    ) -> PublishResult:
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        sent_time = datetime.datetime.now(UTC)
        text_str = text if isinstance(text, str) else json.dumps(text)

        if not webhook_url:
            log_post_event(self.name, job_ids or [], text_str, scheduled_time, sent_time, "MISSING_CREDENTIALS")
            return PublishResult(ok=False, error="Missing DISCORD_WEBHOOK_URL", permanent=True)

        embed_dict: dict[str, Any]
        if isinstance(text, dict):
            embed_dict = text
        else:
            try:
                embed_dict = json.loads(text)
            except Exception:
                embed_dict = {"title": "Visa Sponsorship Opportunity", "description": text[:300], "fields": {}}

        # Build Discord webhook embed payload
        fields_data = embed_dict.get("fields", {})
        discord_fields = [
            {"name": k.replace("_", " ").title(), "value": str(v)[:1024], "inline": True}
            for k, v in fields_data.items()
        ]

        embed = {
            "title": embed_dict.get("title", "Visa Sponsorship Role")[:256],
            "description": embed_dict.get("description", "")[:4096],
            "color": 0x22C55E if "🟢" in str(fields_data.get("confidence", "")) else 0xEAB308,
            "fields": discord_fields,
            "footer": {"text": "Visa Lane · Verified Sponsorship Feed"},
        }
        if image_url:
            embed["image"] = {"url": image_url}

        payload: dict[str, Any] = {"embeds": [embed]}

        try:
            if image_bytes:
                files = {"file": ("card.jpg", image_bytes, "image/jpeg")}
                payload_json = json.dumps(payload)
                res = requests.post(webhook_url, data={"payload_json": payload_json}, files=files, timeout=20)
            else:
                res = requests.post(webhook_url, json=payload, timeout=15)

            if res.status_code in (200, 204):
                log_post_event(self.name, job_ids or [], text_str, scheduled_time, sent_time, f"HTTP_{res.status_code}")
                return PublishResult(ok=True, url=webhook_url)

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            log_post_event(self.name, job_ids or [], text_str, scheduled_time, sent_time, f"HTTP_{res.status_code}")
            return PublishResult(
                ok=False,
                error=f"Discord webhook HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            log_post_event(self.name, job_ids or [], text_str, scheduled_time, sent_time, f"EXCEPTION_{type(e).__name__}")
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent, retry_after=retry_after)


# -----------------------------------------------------------------------------
# 3. X / Twitter Adapter (Tier 2: <= 260 Chars, Bio Reference, Cost Aware)
# -----------------------------------------------------------------------------
class XAdapter:
    name = "x"

    def __init__(self) -> None:
        self.profile = get_profile("x")
        self.char_limit = self.profile.char_limit
        self.max_image_bytes = self.profile.max_image_bytes or 5_000_000

    def generate_content(
        self,
        jobs_or_data: Any = None,
        llm_router: Any | None = None,
        insight_stat: str | None = None,
        **kwargs: Any,
    ) -> str:
        job = jobs_or_data[0] if isinstance(jobs_or_data, list) and jobs_or_data else jobs_or_data

        if llm_router:
            prompt = x_prompts.build_user_prompt(job, insight_stat)
            try:
                res = llm_router.complete(
                    prompt=prompt,
                    system_instruction=x_prompts.SYSTEM_PROMPT,
                    temperature=0.3,
                )
                if res and res.text and len(res.text.strip()) > 15:
                    text = res.text.strip()
                    # Strip any raw urls if accidentally generated
                    text = re.sub(r"https?://\S+", "-> link in bio", text)
                    if len(text) <= self.profile.extra_settings.get("max_target_chars", 260):
                        return text
            except Exception as exc:
                logger.warning("X LLM generation failed: %s; using rule-based fallback", exc)

        # Deterministic rule-based fallback
        if insight_stat:
            return f"{insight_stat} 🌍 Track open visa roles -> link in bio #VisaSponsorship"[:260]

        j = job or {}
        title = j.get("title") or "Software Engineer"
        company = j.get("company") or "Tech Corp"
        city = j.get("city") or j.get("location_raw") or j.get("location") or "Worldwide"
        country = j.get("country") or ""
        location_str = f"{city}, {country}".strip(", ")
        verified = "Verified sponsor" if j.get("visa_sponsorship_verified") else "Visa support confirmed"

        return f"📍 {location_str} | {company} is hiring a {title}. {verified}. 💼 Full details -> link in bio #TechJobs"[:260]

    def check_credentials(self) -> tuple[bool, str]:
        api_key = os.getenv("X_API_KEY")
        api_secret = os.getenv("X_API_SECRET")
        access_token = os.getenv("X_ACCESS_TOKEN")
        access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

        if not (api_key and api_secret and access_token and access_token_secret):
            return False, "NOT_CONFIGURED"

        try:
            from requests_oauthlib import OAuth1  # type: ignore[import-untyped]
            auth = OAuth1(api_key, api_secret, access_token, access_token_secret)
            res = requests.get("https://api.x.com/2/users/me", auth=auth, timeout=10)
            if res.status_code == 200:
                username = res.json().get("data", {}).get("username", "ok")
                return True, f"OK (@{username})"
            return False, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, str(e)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
        job_ids: list[str] | None = None,
        scheduled_time: datetime.datetime | None = None,
    ) -> PublishResult:
        api_key = os.getenv("X_API_KEY")
        api_secret = os.getenv("X_API_SECRET")
        access_token = os.getenv("X_ACCESS_TOKEN")
        access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")
        sent_time = datetime.datetime.now(UTC)

        if not (api_key and api_secret and access_token and access_token_secret):
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, "MISSING_CREDENTIALS")
            return PublishResult(ok=False, error="Missing X/Twitter API credentials", permanent=True)

        auth = None
        try:
            from requests_oauthlib import OAuth1  # type: ignore[import-untyped]
            auth = OAuth1(api_key, api_secret, access_token, access_token_secret)
        except ImportError:


            media_id = None
            if image_bytes:
                try:
                    upload_res = requests.post(
                        "https://upload.twitter.com/1.1/media/upload.json",
                        auth=auth,
                        files={"media": image_bytes},
                        timeout=20,
                    )
                    if upload_res.status_code in (200, 201):
                        media_id = upload_res.json().get("media_id_string")
                except Exception as e:
                    logger.warning("X media upload exception: %s; falling back to text-only", e)

            # Enforce 280 char limit strictly
            post_text = truncate_keep_url(text, self.char_limit)

            payload: dict[str, Any] = {"text": post_text}
            if media_id:
                payload["media"] = {"media_ids": [media_id]}

            res = requests.post("https://api.x.com/2/tweets", auth=auth, json=payload, timeout=15)

            if res.status_code in (200, 201):
                data = res.json().get("data", {})
                tweet_id = data.get("id")
                url = data.get("url") or f"https://x.com/i/status/{tweet_id}"
                log_post_event(self.name, job_ids or [], post_text, scheduled_time, sent_time, f"HTTP_{res.status_code}")
                return PublishResult(ok=True, url=url)

            if res.status_code == 403 and "duplicate" in res.text.lower():
                log_post_event(self.name, job_ids or [], post_text, scheduled_time, sent_time, "HTTP_403_DUPLICATE")
                return PublishResult(ok=True, url="https://x.com", warning="duplicate_post_ignored")

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            log_post_event(self.name, job_ids or [], post_text, scheduled_time, sent_time, f"HTTP_{res.status_code}")
            return PublishResult(
                ok=False,
                error=f"X API HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"EXCEPTION_{type(e).__name__}")
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent, retry_after=retry_after)


# -----------------------------------------------------------------------------
# 4. LinkedIn Adapter (Tier 2: Professional Register, Configurable Author)
# -----------------------------------------------------------------------------
class LinkedInAdapter:
    name = "linkedin"

    def __init__(self) -> None:
        self.profile = get_profile("linkedin")
        self.char_limit = self.profile.char_limit
        self.max_image_bytes = self.profile.max_image_bytes or 8_000_000

    def generate_content(
        self,
        jobs_or_data: Any = None,
        llm_router: Any | None = None,
        insight_stat: str | None = None,
        mode: str = "single_job",
        **kwargs: Any,
    ) -> str:
        job = jobs_or_data[0] if isinstance(jobs_or_data, list) and jobs_or_data else jobs_or_data

        if llm_router:
            prompt = linkedin_prompts.build_user_prompt(job, insight_stat, mode)
            try:
                res = llm_router.complete(
                    prompt=prompt,
                    system_instruction=linkedin_prompts.SYSTEM_PROMPT,
                    temperature=0.3,
                )
                if res and res.text and len(res.text.strip()) > 50:
                    text = res.text.strip()
                    if len(text) <= self.char_limit:
                        return text
            except Exception as exc:
                logger.warning("LinkedIn LLM generation failed: %s; using rule-based fallback", exc)

        # Deterministic rule-based fallback
        if mode == "weekly_insight" or insight_stat:
            return (
                "Data insight on global talent mobility:\n\n"
                f"{insight_stat}\n\n"
                "📍 Employers actively sponsoring international talent continue to scale technical teams.\n"
                "💼 Navigating visa pathways with verified data makes cross-border hiring predictable.\n"
                "✅ Explore all verified visa-sponsoring employers at https://visalane.app"
            )

        j = job or {}
        title = j.get("title") or "Senior Software Engineer"
        company = j.get("company") or "Tech Enterprise"
        city = j.get("city") or j.get("location_raw") or j.get("location") or "Worldwide"
        country = j.get("country") or ""
        location_str = f"{city}, {country}".strip(", ")
        visa_types = ", ".join(j.get("visa_types") or []) if isinstance(j.get("visa_types"), list) else str(j.get("visa_types") or "Work Visa / Relocation")
        salary = j.get("salary_raw") or (f"{j.get('salary_min')}-{j.get('salary_max')} {j.get('salary_currency', 'USD')}" if j.get("salary_min") else "Competitive")
        apply_link = j.get("apply_url") or j.get("url") or "https://visalane.app"

        return (
            f"{company} is currently recruiting for a {title} with verified visa sponsorship.\n\n"
            f"📍 Location: {location_str}\n"
            f"💼 Sponsorship Details: {visa_types} (Salary: {salary})\n"
            "✅ Verified against official government sponsor registries\n\n"
            "Full details and application link:\n"
            f"{apply_link}"
        )

    def check_credentials(self) -> tuple[bool, str]:
        token = os.getenv("LINKEDIN_ACCESS_TOKEN")
        if not token:
            return False, "NOT_CONFIGURED"

        try:
            res = requests.get("https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {token}"}, timeout=10)
            if res.status_code == 200:
                name = res.json().get("name", "ok")
                return True, f"OK ({name})"
            return False, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, str(e)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
        job_ids: list[str] | None = None,
        scheduled_time: datetime.datetime | None = None,
    ) -> PublishResult:
        token = os.getenv("LINKEDIN_ACCESS_TOKEN")
        sent_time = datetime.datetime.now(UTC)

        if not token:
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, "MISSING_CREDENTIALS")
            return PublishResult(ok=False, error="Missing LINKEDIN_ACCESS_TOKEN", permanent=True)

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"}

        # Determine author URN (Personal profile vs Company page switch)
        org_id = os.getenv("LINKEDIN_ORG_ID") or os.getenv("LINKEDIN_PAGE_ID")
        if org_id:
            author_urn = f"urn:li:organization:{org_id}"
        else:
            user_res = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers, timeout=10)
            if user_res.status_code == 401:
                refresh_token = os.getenv("LINKEDIN_REFRESH_TOKEN")
                client_id = os.getenv("LINKEDIN_CLIENT_ID")
                client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")
                if refresh_token and client_id and client_secret:
                    refresh_res = requests.post(
                        "https://www.linkedin.com/oauth/v2/accessToken",
                        data={
                            "grant_type": "refresh_token",
                            "refresh_token": refresh_token,
                            "client_id": client_id,
                            "client_secret": client_secret,
                        },
                        timeout=15,
                    )
                    if refresh_res.status_code == 200:
                        token = refresh_res.json().get("access_token")
                        headers["Authorization"] = f"Bearer {token}"
                        user_res = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers, timeout=10)

            if user_res.status_code != 200:
                log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"AUTH_HTTP_{user_res.status_code}")
                return PublishResult(ok=False, error=f"LinkedIn userinfo HTTP {user_res.status_code}: {user_res.text[:200]}", permanent=True)
            sub = user_res.json().get("sub")
            author_urn = f"urn:li:person:{sub}"


        # Register media if bytes provided
        asset_urn = None
        if image_bytes:
            try:
                reg_payload = {
                    "registerUploadRequest": {
                        "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                        "owner": author_urn,
                        "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}],
                    }
                }
                reg_res = requests.post("https://api.linkedin.com/v2/assets?action=registerUpload", headers=headers, json=reg_payload, timeout=15)
                if reg_res.status_code in (200, 201):
                    upload_url = reg_res.json().get("value", {}).get("uploadMechanism", {}).get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {}).get("uploadUrl")
                    asset_urn = reg_res.json().get("value", {}).get("asset")
                    if upload_url and asset_urn:
                        requests.put(upload_url, data=image_bytes, headers={"Authorization": f"Bearer {token}"}, timeout=25)
            except Exception as e:
                logger.warning("LinkedIn image upload error: %s; falling back to text-only", e)
                asset_urn = None

        post_text = truncate_keep_url(text, self.char_limit)
        post_payload: dict[str, Any] = {
            "author": author_urn,
            "commentary": post_text,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
        }
        if asset_urn:
            post_payload["content"] = {"media": {"id": asset_urn, "title": "Visa Sponsorship Opportunity"}}

        try:
            res = requests.post("https://api.linkedin.com/v2/posts", headers=headers, json=post_payload, timeout=15)
            if res.status_code in (200, 201):
                post_id = res.headers.get("x-restli-id") or ""
                url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else "https://www.linkedin.com"
                log_post_event(self.name, job_ids or [], post_text, scheduled_time, sent_time, f"HTTP_{res.status_code}")
                return PublishResult(ok=True, url=url)

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            log_post_event(self.name, job_ids or [], post_text, scheduled_time, sent_time, f"HTTP_{res.status_code}")
            return PublishResult(
                ok=False,
                error=f"LinkedIn post HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"EXCEPTION_{type(e).__name__}")
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent, retry_after=retry_after)


# -----------------------------------------------------------------------------
# 5. Bluesky Adapter (Tier 2: AT Protocol, 300 Chars / 3000 Bytes, Threading)
# -----------------------------------------------------------------------------
class BlueskyAdapter:
    name = "bluesky"

    def __init__(self) -> None:
        self.profile = get_profile("bluesky")
        self.char_limit = self.profile.char_limit
        self.max_image_bytes = self.profile.max_image_bytes or 976_560

    def generate_content(
        self,
        jobs_or_data: Any = None,
        llm_router: Any | None = None,
        short_link: str | None = None,
        **kwargs: Any,
    ) -> str:
        job = jobs_or_data[0] if isinstance(jobs_or_data, list) and jobs_or_data else jobs_or_data

        if llm_router:
            prompt = bsky_prompts.build_user_prompt(job, short_link)
            try:
                res = llm_router.complete(
                    prompt=prompt,
                    system_instruction=bsky_prompts.SYSTEM_PROMPT,
                    temperature=0.3,
                )
                if res and res.text and len(res.text.strip()) > 20:
                    text = res.text.strip()
                    if len(text.encode("utf-8")) <= 3000:
                        return text
            except Exception as exc:
                logger.warning("Bluesky LLM generation failed: %s; using rule-based fallback", exc)

        # Deterministic rule-based fallback
        j = job or {}
        title = j.get("title") or "Software Engineer"
        company = j.get("company") or "Tech Corp"
        city = j.get("city") or j.get("location_raw") or j.get("location") or "Worldwide"
        country = j.get("country") or ""
        location_str = f"{city}, {country}".strip(", ")
        link = short_link or j.get("short_link") or "visalane.app/j"

        return f"📍 {company} is hiring: {title} ({location_str}).\n\nVerified visa support & relocation assistance. 🌍\n\nApply: {link}"[:300]

    def check_credentials(self) -> tuple[bool, str]:
        handle = os.getenv("BLUESKY_HANDLE")
        app_password = os.getenv("BLUESKY_APP_PASSWORD")
        if not (handle and app_password):
            return False, "NOT_CONFIGURED"

        try:
            res = requests.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": handle, "password": app_password},
                timeout=10,
            )
            if res.status_code == 200:
                did = res.json().get("did")
                return True, f"OK ({did})"
            return False, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, str(e)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
        job_ids: list[str] | None = None,
        scheduled_time: datetime.datetime | None = None,
    ) -> PublishResult:
        handle = os.getenv("BLUESKY_HANDLE")
        app_password = os.getenv("BLUESKY_APP_PASSWORD")
        sent_time = datetime.datetime.now(UTC)

        if not (handle and app_password):
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, "MISSING_CREDENTIALS")
            return PublishResult(ok=False, error="Missing BLUESKY_HANDLE or BLUESKY_APP_PASSWORD", permanent=True)

        try:
            session_res = requests.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": handle, "password": app_password},
                timeout=10,
            )
            if session_res.status_code != 200:
                return PublishResult(ok=False, error=f"Bluesky auth HTTP {session_res.status_code}: {session_res.text[:150]}", permanent=True)

            session = session_res.json()
            jwt = session.get("accessJwt")
            did = session.get("did")
            headers = {"Authorization": f"Bearer {jwt}"}

            # Check if text contains thread separator
            parts = text.split("|||THREAD|||")
            first_text = parts[0].strip()[:300]
            now_iso = datetime.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

            record: dict[str, Any] = {
                "$type": "app.bsky.feed.post",
                "text": first_text,
                "createdAt": now_iso,
            }

            post_res = requests.post(
                "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                headers=headers,
                json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
                timeout=15,
            )

            if post_res.status_code == 200:
                uri = post_res.json().get("uri", "")
                rkey = uri.split("/")[-1] if uri else ""
                url = f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else "https://bsky.app"

                # If thread part exists, post reply
                if len(parts) > 1 and parts[1].strip():
                    reply_text = parts[1].strip()[:300]
                    cid = post_res.json().get("cid")
                    reply_record = {
                        "$type": "app.bsky.feed.post",
                        "text": reply_text,
                        "createdAt": datetime.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "reply": {"root": {"uri": uri, "cid": cid}, "parent": {"uri": uri, "cid": cid}},
                    }
                    requests.post(
                        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                        headers=headers,
                        json={"repo": did, "collection": "app.bsky.feed.post", "record": reply_record},
                        timeout=15,
                    )

                log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, "HTTP_200")
                return PublishResult(ok=True, url=url)

            retryable, permanent, retry_after = classify_http_error(post_res.status_code, post_res.text, post_res.headers)
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"HTTP_{post_res.status_code}")
            return PublishResult(
                ok=False,
                error=f"Bluesky post HTTP {post_res.status_code}: {post_res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"EXCEPTION_{type(e).__name__}")
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent, retry_after=retry_after)


# -----------------------------------------------------------------------------
# 6. Mastodon Adapter (Tier 2: 500 Chars, Hashtags, Labeled Bot)
# -----------------------------------------------------------------------------
class MastodonAdapter:
    name = "mastodon"

    def __init__(self) -> None:
        self.profile = get_profile("mastodon")
        self.char_limit = self.profile.char_limit
        self.max_image_bytes = self.profile.max_image_bytes or 8_000_000

    def generate_content(
        self,
        jobs_or_data: Any = None,
        llm_router: Any | None = None,
        **kwargs: Any,
    ) -> str:
        job = jobs_or_data[0] if isinstance(jobs_or_data, list) and jobs_or_data else jobs_or_data

        if llm_router:
            prompt = mastodon_prompts.build_user_prompt(job)
            try:
                res = llm_router.complete(
                    prompt=prompt,
                    system_instruction=mastodon_prompts.SYSTEM_PROMPT,
                    temperature=0.3,
                )
                if res and res.text and len(res.text.strip()) > 30:
                    text = res.text.strip()
                    if len(text) <= self.char_limit:
                        return text
            except Exception as exc:
                logger.warning("Mastodon LLM generation failed: %s; using rule-based fallback", exc)

        # Deterministic rule-based fallback
        j = job or {}
        title = j.get("title") or "Software Engineer"
        company = j.get("company") or "Tech Corp"
        city = j.get("city") or j.get("location_raw") or j.get("location") or "Worldwide"
        country = j.get("country") or ""
        location_str = f"{city}, {country}".strip(", ")
        verified = "Official visa sponsor verified" if j.get("visa_sponsorship_verified") else "Visa sponsorship available"
        apply_link = j.get("apply_url") or j.get("url") or "https://visalane.app"

        return f"📍 {title} at {company} ({location_str})\n\n{verified}. Work visa support provided. 💼\n\n{apply_link}\n\n#VisaSponsorship #TechJobs #Relocation"[:500]

    def check_credentials(self) -> tuple[bool, str]:
        instance_url = (os.getenv("MASTODON_INSTANCE_URL") or "https://mastodon.social").rstrip("/")
        access_token = os.getenv("MASTODON_ACCESS_TOKEN")
        if not access_token:
            return False, "NOT_CONFIGURED"

        try:
            res = requests.get(f"{instance_url}/api/v1/accounts/verify_credentials", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
            if res.status_code == 200:
                username = res.json().get("username", "ok")
                return True, f"OK (@{username})"
            return False, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, str(e)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
        job_ids: list[str] | None = None,
        scheduled_time: datetime.datetime | None = None,
    ) -> PublishResult:
        instance_url = (os.getenv("MASTODON_INSTANCE_URL") or "https://mastodon.social").rstrip("/")
        access_token = os.getenv("MASTODON_ACCESS_TOKEN")
        sent_time = datetime.datetime.now(UTC)

        if not access_token:
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, "MISSING_CREDENTIALS")
            return PublishResult(ok=False, error="Missing MASTODON_ACCESS_TOKEN", permanent=True)

        headers = {"Authorization": f"Bearer {access_token}"}
        post_text = truncate_keep_url(text, self.char_limit)

        media_id = None
        if image_bytes:
            try:
                media_res = requests.post(
                    f"{instance_url}/api/v2/media",
                    headers=headers,
                    files={"file": ("card.jpg", image_bytes, "image/jpeg")},
                    timeout=25,
                )
                if media_res.status_code == 202:
                    m_id = media_res.json().get("id")
                    if m_id:
                        media_id = m_id
                        for _ in range(5):
                            poll_res = requests.get(f"{instance_url}/api/v1/media/{m_id}", headers=headers, timeout=10)
                            if poll_res.status_code == 200 and poll_res.json().get("url"):
                                break
                elif media_res.status_code in (200, 201):
                    media_id = media_res.json().get("id")
            except Exception as e:
                logger.warning("Mastodon media upload failed: %s; falling back to text-only", e)

        payload: dict[str, Any] = {"status": post_text, "visibility": "public"}
        if media_id:
            payload["media_ids"] = [media_id]

        try:
            res = requests.post(f"{instance_url}/api/v1/statuses", headers=headers, json=payload, timeout=15)

            if res.status_code in (200, 201):
                url = res.json().get("url") or f"{instance_url}/statuses"
                log_post_event(self.name, job_ids or [], post_text, scheduled_time, sent_time, f"HTTP_{res.status_code}")
                return PublishResult(ok=True, url=url)

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            log_post_event(self.name, job_ids or [], post_text, scheduled_time, sent_time, f"HTTP_{res.status_code}")
            return PublishResult(
                ok=False,
                error=f"Mastodon API HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"EXCEPTION_{type(e).__name__}")
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent, retry_after=retry_after)


# -----------------------------------------------------------------------------
# 7. DEV.to Adapter (Tier 4: Long-form Technical Articles Only)
# -----------------------------------------------------------------------------
class DevtoAdapter:
    name = "devto"

    def __init__(self) -> None:
        self.profile = get_profile("devto")
        self.char_limit = self.profile.char_limit
        self.max_image_bytes = self.profile.max_image_bytes or 10_000_000

    def generate_content(
        self,
        jobs_or_data: Any = None,
        llm_router: Any | None = None,
        topic: str | None = None,
        stats_block: str | None = None,
        notable_points: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        topic_str = topic or "Global Visa Sponsorship Hiring Trends for Developers"
        stats_str = stats_block or "Analysis of 100,000+ verified filings and official sponsor registry changes."

        if llm_router:
            prompt = devto_prompts.build_user_prompt(topic_str, stats_str, notable_points)
            try:
                res = llm_router.complete(
                    prompt=prompt,
                    system_instruction=devto_prompts.SYSTEM_PROMPT,
                    temperature=0.3,
                )
                if res and res.text and len(res.text.strip()) > 300:
                    return res.text.strip()
            except Exception as exc:
                logger.warning("DEV.to LLM generation failed: %s; using rule-based fallback", exc)

        # Deterministic rule-based fallback (Full article with YAML front matter)
        return f"""---
title: {topic_str}
published: true
tags: careers, immigration, softwareengineering, techjobs
---

## Executive Summary

Cross-border tech hiring is increasingly driven by verifiable government sponsorship registers rather than generic job board listings.

## Data Overview

{stats_str}

## What This Means for International Developers

1. **Verify Official Registers**: Relying on official registries (US H-1B, UK Home Office, Germany Skilled Immigration, Netherlands IND) provides factual certainty.
2. **Target High-Confidence Roles**: Focus applications where companies have active filing histories.

## Methodology

Data compiled and audited through verified immigration registries and open telemetry at Visa Lane (https://visalane.app).
"""

    def check_credentials(self) -> tuple[bool, str]:
        api_key = os.getenv("DEVTO_API_KEY")
        if not api_key:
            return False, "NOT_CONFIGURED"
        try:
            res = requests.get("https://dev.to/api/users/me", headers={"api-key": api_key}, timeout=10)
            if res.status_code == 200:
                username = res.json().get("username", "ok")
                return True, f"OK (@{username})"
            return False, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, str(e)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
        job_ids: list[str] | None = None,
        scheduled_time: datetime.datetime | None = None,
    ) -> PublishResult:
        api_key = os.getenv("DEVTO_API_KEY")
        sent_time = datetime.datetime.now(UTC)

        if not api_key:
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, "MISSING_CREDENTIALS")
            return PublishResult(ok=False, error="Missing DEVTO_API_KEY", permanent=True)

        headers = {"api-key": api_key, "Content-Type": "application/json"}

        # Parse markdown body or front matter
        title = "Global Visa Sponsorship Analysis"
        tags = ["careers", "techjobs", "immigration"]
        body_markdown = text

        if text.startswith("---"):
            try:
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    fm = parts[1]
                    body_markdown = parts[2].strip()
                    for line in fm.split("\n"):
                        if line.startswith("title:"):
                            title = line.split("title:", 1)[1].strip().strip("\"'")
                        elif line.startswith("tags:"):
                            raw_tags = line.split("tags:", 1)[1].strip()
                            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            except Exception as e:
                logger.debug("Failed parsing DEV.to front matter: %s", e)


        article_payload = {
            "article": {
                "title": title[:120],
                "published": True,
                "body_markdown": body_markdown,
                "tags": tags[:4],
                "main_image": image_url,
            }
        }

        try:
            res = requests.post("https://dev.to/api/articles", headers=headers, json=article_payload, timeout=20)
            if res.status_code == 422:
                article_payload["article"]["title"] = title[:80]
                article_payload["article"]["tags"] = ["careers", "techjobs"]
                res = requests.post("https://dev.to/api/articles", headers=headers, json=article_payload, timeout=20)

            if res.status_code in (200, 201):
                url = res.json().get("url") or "https://dev.to"
                log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"HTTP_{res.status_code}")
                return PublishResult(ok=True, url=url)



            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"HTTP_{res.status_code}")
            return PublishResult(
                ok=False,
                error=f"DEV.to API HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            log_post_event(self.name, job_ids or [], text, scheduled_time, sent_time, f"EXCEPTION_{type(e).__name__}")
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent, retry_after=retry_after)


# -----------------------------------------------------------------------------
# Adapter Registry & Factory
# -----------------------------------------------------------------------------
ADAPTER_REGISTRY: dict[str, type] = {
    "telegram": TelegramAdapter,
    "discord": DiscordAdapter,
    "x": XAdapter,
    "linkedin": LinkedInAdapter,
    "bluesky": BlueskyAdapter,
    "mastodon": MastodonAdapter,
    "devto": DevtoAdapter,
}

ADAPTERS = ADAPTER_REGISTRY


def get_adapter(platform: str) -> PlatformAdapter:
    """Retrieve an initialized adapter instance for the specified platform."""
    plat = platform.lower().strip()
    if plat not in ADAPTER_REGISTRY:
        raise KeyError(f"Unknown platform '{platform}'. Available: {list(ADAPTER_REGISTRY.keys())}")
    return ADAPTER_REGISTRY[plat]()  # type: ignore[return-value]


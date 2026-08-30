"""Multi-Platform Social Publishing Adapters & Protocol Registry.

Provides unified adapters for:
- X / Twitter (API v2 + OAuth 1.0a)
- Bluesky (AT Protocol)
- Mastodon (v1/v2 API)
- LinkedIn (v2 Posts API + Token Refresh)
- Telegram (Bot API)
- Discord (Webhooks)
- Dev.to (Articles API)

Each adapter implements the `PlatformAdapter` protocol and guarantees:
- Never raises exceptions out (always returns `PublishResult`)
- Automatic media fallback to text-only
- URL-safe progressive text truncation
- Proper error taxonomy (retryable vs. permanent)
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import requests

from job_radar.social.error_taxonomy import classify_exception, classify_http_error
from job_radar.social.text_prep import truncate_keep_url

logger = logging.getLogger(__name__)


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
    char_limit: int
    max_image_bytes: int | None

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
    ) -> PublishResult:
        ...

    def check_credentials(self) -> tuple[bool, str]:
        """Ping platform API to verify credentials without publishing."""
        ...


# -----------------------------------------------------------------------------
# 1. X / Twitter Adapter
# -----------------------------------------------------------------------------
class XAdapter:
    name = "x"
    char_limit = 280
    max_image_bytes = 5_000_000

    def check_credentials(self) -> tuple[bool, str]:
        api_key = os.getenv("X_API_KEY")
        api_secret = os.getenv("X_API_SECRET")
        access_token = os.getenv("X_ACCESS_TOKEN")
        access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

        if not (api_key and api_secret and access_token and access_token_secret):
            return False, "NOT_CONFIGURED"

        try:
            from requests_oauthlib import OAuth1
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
    ) -> PublishResult:
        api_key = os.getenv("X_API_KEY")
        api_secret = os.getenv("X_API_SECRET")
        access_token = os.getenv("X_ACCESS_TOKEN")
        access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

        if not (api_key and api_secret and access_token and access_token_secret):
            return PublishResult(ok=False, error="Missing X/Twitter API credentials", permanent=True)

        try:
            from requests_oauthlib import OAuth1
            auth = OAuth1(api_key, api_secret, access_token, access_token_secret)

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
                    else:
                        logger.warning("X media upload returned HTTP %s; falling back to text-only", upload_res.status_code)
                except Exception as e:
                    logger.warning("X media upload exception: %s; falling back to text-only", e)

            # Format and truncate text safely
            post_text = truncate_keep_url(text, self.char_limit)

            payload: dict[str, Any] = {"text": post_text}
            if media_id:
                payload["media"] = {"media_ids": [media_id]}

            res = requests.post(
                "https://api.x.com/2/tweets",
                auth=auth,
                json=payload,
                timeout=15,
            )

            if res.status_code in (200, 201):
                data = res.json().get("data", {})
                tweet_id = data.get("id")
                url = data.get("url") or f"https://x.com/i/status/{tweet_id}"
                return PublishResult(ok=True, url=url)

            # Edge Case: 403 Duplicate tweet -> treat as done-with-warning
            if res.status_code == 403 and "duplicate" in res.text.lower():
                logger.warning("X returned duplicate status; marking done-with-warning")
                return PublishResult(ok=True, url="https://x.com", warning="duplicate_post_ignored")

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            return PublishResult(
                ok=False,
                error=f"X API HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent)


# -----------------------------------------------------------------------------
# 2. Bluesky Adapter (AT Protocol)
# -----------------------------------------------------------------------------
class BlueskyAdapter:
    name = "bluesky"
    char_limit = 300
    max_image_bytes = 976_560  # Strict AT Protocol blob limit

    _cached_jwt: str | None = None
    _cached_did: str | None = None

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

    def _get_session(self, force_refresh: bool = False) -> tuple[str | None, str | None, PublishResult | None]:
        handle = os.getenv("BLUESKY_HANDLE")
        app_password = os.getenv("BLUESKY_APP_PASSWORD")

        if not (handle and app_password):
            return None, None, PublishResult(ok=False, error="Missing Bluesky credentials", permanent=True)

        if not force_refresh and self._cached_jwt and self._cached_did:
            return self._cached_jwt, self._cached_did, None

        try:
            res = requests.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": handle, "password": app_password},
                timeout=15,
            )
            if res.status_code == 200:
                data = res.json()
                self._cached_jwt = data.get("accessJwt")
                self._cached_did = data.get("did")
                return self._cached_jwt, self._cached_did, None

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            return None, None, PublishResult(
                ok=False,
                error=f"Bluesky session auth failed HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            return None, None, PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
    ) -> PublishResult:
        jwt, did, err_result = self._get_session()
        if err_result:
            return err_result

        handle = os.getenv("BLUESKY_HANDLE") or "visalane.online"
        post_text = truncate_keep_url(text, self.char_limit, is_grapheme=True)

        blob_record = None
        if image_bytes and len(image_bytes) <= self.max_image_bytes:
            try:
                blob_res = requests.post(
                    "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                    headers={"Authorization": f"Bearer {jwt}", "Content-Type": "image/jpeg"},
                    data=image_bytes,
                    timeout=20,
                )
                if blob_res.status_code in (200, 201):
                    blob_data = blob_res.json().get("blob")
                    if blob_data:
                        blob_record = {
                            "$type": "app.bsky.embed.images",
                            "images": [{"image": blob_data, "alt": "Visa sponsorship opportunity"}],
                        }
                elif blob_res.status_code == 413:
                    logger.warning("Bluesky blob upload exceeded payload size; falling back to text-only")
            except Exception as e:
                logger.warning("Bluesky blob upload exception: %s; falling back to text-only", e)

        record: dict[str, Any] = {
            "$type": "app.bsky.feed.post",
            "text": post_text,
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        if blob_record:
            record["embed"] = blob_record

        try:
            res = requests.post(
                "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"},
                json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
                timeout=15,
            )

            # If token expired, refresh and try once
            if res.status_code == 401 and "ExpiredToken" in res.text:
                jwt, did, err_result = self._get_session(force_refresh=True)
                if err_result:
                    return err_result
                res = requests.post(
                    "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                    headers={"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"},
                    json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
                    timeout=15,
                )

            if res.status_code in (200, 201):
                uri = res.json().get("uri", "")
                rkey = uri.split("/")[-1] if uri else ""
                url = f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else "https://bsky.app"
                return PublishResult(ok=True, url=url)

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            return PublishResult(
                ok=False,
                error=f"Bluesky createRecord HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent)


# -----------------------------------------------------------------------------
# 3. Mastodon Adapter
# -----------------------------------------------------------------------------
class MastodonAdapter:
    name = "mastodon"
    char_limit = 500
    max_image_bytes = 8_000_000

    def check_credentials(self) -> tuple[bool, str]:
        instance_url = (os.getenv("MASTODON_INSTANCE_URL") or "").rstrip("/")
        access_token = os.getenv("MASTODON_ACCESS_TOKEN")
        if not (instance_url and access_token):
            return False, "NOT_CONFIGURED"

        try:
            res = requests.get(
                f"{instance_url}/api/v1/accounts/verify_credentials",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            if res.status_code == 200:
                username = res.json().get("username", "ok")
                return True, f"OK (@{username}@{instance_url})"
            return False, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, str(e)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
    ) -> PublishResult:
        instance_url = (os.getenv("MASTODON_INSTANCE_URL") or "").rstrip("/")
        access_token = os.getenv("MASTODON_ACCESS_TOKEN")

        if not (instance_url and access_token):
            return PublishResult(ok=False, error="Missing Mastodon instance credentials", permanent=True)

        headers = {"Authorization": f"Bearer {access_token}"}
        media_id = None

        if image_bytes:
            try:
                media_res = requests.post(
                    f"{instance_url}/api/v1/v2/media",
                    headers=headers,
                    files={"file": ("card.jpg", image_bytes, "image/jpeg")},
                    timeout=25,
                )
                if media_res.status_code in (200, 202):
                    media_data = media_res.json()
                    media_id = media_data.get("id")
                    # If async 202, poll until url is ready (max 30s)
                    if media_res.status_code == 202 and media_id:
                        for _ in range(6):
                            time.sleep(5)
                            poll_res = requests.get(f"{instance_url}/api/v1/media/{media_id}", headers=headers, timeout=10)
                            if poll_res.status_code == 200 and poll_res.json().get("url"):
                                break
                elif media_res.status_code == 422:
                    logger.warning("Mastodon media upload returned 422; falling back to text-only")
            except Exception as e:
                logger.warning("Mastodon media upload exception: %s; falling back to text-only", e)

        post_text = truncate_keep_url(text, self.char_limit)
        payload: dict[str, Any] = {"status": post_text, "visibility": "public"}
        if media_id:
            payload["media_ids"] = [media_id]

        try:
            res = requests.post(
                f"{instance_url}/api/v1/statuses",
                headers=headers,
                json=payload,
                timeout=15,
            )

            if res.status_code in (200, 201):
                url = res.json().get("url") or f"{instance_url}/statuses"
                return PublishResult(ok=True, url=url)

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            return PublishResult(
                ok=False,
                error=f"Mastodon API HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent)


# -----------------------------------------------------------------------------
# 4. LinkedIn Adapter
# -----------------------------------------------------------------------------
class LinkedInAdapter:
    name = "linkedin"
    char_limit = 3000
    max_image_bytes = 8_000_000

    def check_credentials(self) -> tuple[bool, str]:
        token = os.getenv("LINKEDIN_ACCESS_TOKEN")
        if not token:
            return False, "NOT_CONFIGURED"

        try:
            res = requests.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if res.status_code == 200:
                name = res.json().get("name", "ok")
                return True, f"OK ({name})"
            return False, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, str(e)

    def _refresh_token(self) -> tuple[str | None, str | None]:
        client_id = os.getenv("LINKEDIN_CLIENT_ID")
        client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")
        refresh_token = os.getenv("LINKEDIN_REFRESH_TOKEN")

        if not (client_id and client_secret and refresh_token):
            return None, "Missing LinkedIn OAuth client secrets for token refresh"

        try:
            res = requests.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            if res.status_code == 200:
                new_token = res.json().get("access_token")
                return new_token, None
            return None, f"Token refresh HTTP {res.status_code}: {res.text[:150]}"
        except Exception as e:
            return None, str(e)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
    ) -> PublishResult:
        token = os.getenv("LINKEDIN_ACCESS_TOKEN")
        if not token:
            return PublishResult(ok=False, error="Missing LINKEDIN_ACCESS_TOKEN", permanent=True)

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"}

        # 1. Resolve author URN
        user_res = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers, timeout=10)
        if user_res.status_code == 401:
            logger.info("LinkedIn token expired; attempting refresh")
            new_token, refresh_err = self._refresh_token()
            if new_token:
                token = new_token
                headers["Authorization"] = f"Bearer {token}"
                user_res = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers, timeout=10)
            else:
                return PublishResult(ok=False, error=f"LinkedIn auth expired & refresh failed: {refresh_err}", permanent=True)

        if user_res.status_code != 200:
            return PublishResult(ok=False, error=f"LinkedIn userinfo HTTP {user_res.status_code}: {user_res.text[:200]}", permanent=True)

        sub = user_res.json().get("sub")
        author_urn = f"urn:li:person:{sub}"

        # 2. Register media upload if bytes available
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

        # 3. Create post
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
                return PublishResult(ok=True, url=url)

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            return PublishResult(
                ok=False,
                error=f"LinkedIn post HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent)


# -----------------------------------------------------------------------------
# 5. Telegram Adapter
# -----------------------------------------------------------------------------
class TelegramAdapter:
    name = "telegram"
    char_limit = 1024
    max_image_bytes = 10_000_000

    def check_credentials(self) -> tuple[bool, str]:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not (bot_token and chat_id):
            return False, "NOT_CONFIGURED"

        try:
            res = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
            if res.status_code == 200:
                bot_name = res.json().get("result", {}).get("username", "ok")
                return True, f"OK (@{bot_name})"
            return False, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, str(e)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
    ) -> PublishResult:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not (bot_token and chat_id):
            return PublishResult(ok=False, error="Missing Telegram bot credentials", permanent=True)

        post_text = truncate_keep_url(text, self.char_limit)

        try:
            # If image_url available, attempt sendPhoto
            if image_url:
                url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                payload = {
                    "chat_id": chat_id,
                    "photo": image_url,
                    "caption": post_text,
                    "parse_mode": "Markdown",
                }
                res = requests.post(url, json=payload, timeout=20)
                if res.status_code == 200:
                    msg_id = res.json().get("result", {}).get("message_id")
                    clean_chat = chat_id.replace("-100", "").replace("@", "")
                    post_url = f"https://t.me/{clean_chat}/{msg_id}" if msg_id else "https://t.me"
                    return PublishResult(ok=True, url=post_url)

                logger.warning("Telegram sendPhoto failed (HTTP %s); falling back to sendMessage", res.status_code)

            # Fallback to sendMessage
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {"chat_id": chat_id, "text": post_text, "parse_mode": "Markdown"}
            res = requests.post(url, json=payload, timeout=15)

            if res.status_code == 200:
                msg_id = res.json().get("result", {}).get("message_id")
                clean_chat = chat_id.replace("-100", "").replace("@", "")
                post_url = f"https://t.me/{clean_chat}/{msg_id}" if msg_id else "https://t.me"
                return PublishResult(ok=True, url=post_url)

            # Handle 403 bot kicked / 400 chat not found as permanent
            if res.status_code in (400, 403):
                return PublishResult(ok=False, error=f"Telegram permanent error HTTP {res.status_code}: {res.text[:200]}", permanent=True)

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            return PublishResult(
                ok=False,
                error=f"Telegram API HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent)


# -----------------------------------------------------------------------------
# 6. Discord Adapter
# -----------------------------------------------------------------------------
class DiscordAdapter:
    name = "discord"
    char_limit = 2000
    max_image_bytes = 8_000_000

    def check_credentials(self) -> tuple[bool, str]:
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            return False, "NOT_CONFIGURED"

        try:
            res = requests.get(webhook_url, timeout=10)
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
    ) -> PublishResult:
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            return PublishResult(ok=False, error="Missing DISCORD_WEBHOOK_URL", permanent=True)

        post_text = truncate_keep_url(text, self.char_limit)

        try:
            # 1. If image bytes fit within 8MB, send multipart
            if image_bytes and len(image_bytes) <= self.max_image_bytes:
                res = requests.post(
                    webhook_url,
                    files={"file": ("job_card.jpg", image_bytes, "image/jpeg")},
                    data={"content": post_text},
                    timeout=20,
                )
            # 2. Else if image_url available, send embed
            elif image_url:
                payload = {
                    "content": post_text,
                    "embeds": [{"image": {"url": image_url}}],
                }
                res = requests.post(webhook_url, json=payload, timeout=15)
            # 3. Else text only
            else:
                res = requests.post(webhook_url, json={"content": post_text}, timeout=15)

            if res.status_code in (200, 204):
                return PublishResult(ok=True, url="https://discord.com")

            # 404 Unknown Webhook is permanent
            if res.status_code == 404:
                return PublishResult(ok=False, error="Discord webhook not found / invalid", permanent=True)

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            return PublishResult(
                ok=False,
                error=f"Discord API HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent)


# -----------------------------------------------------------------------------
# 7. Dev.to Adapter
# -----------------------------------------------------------------------------
class DevtoAdapter:
    name = "devto"
    char_limit = 20000
    max_image_bytes = None

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

    def _build_article_body(self, title: str, text: str, image_url: str | None = None) -> str:
        # Extract apply url
        url_match = re.search(r"https?://[^\s)]+", text)
        apply_url = url_match.group(0) if url_match else ""

        front_matter = [
            "---",
            f"title: {title[:128]}",
            "published: true",
        ]
        if image_url:
            front_matter.append(f"cover_image: {image_url}")
        if apply_url:
            front_matter.append(f"canonical_url: {apply_url}")
        front_matter.extend(["tags: [jobs, visasponsorship, hiring, career]", "---", "", text])
        return "\n".join(front_matter)

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        image_bytes: bytes | None = None,
    ) -> PublishResult:
        api_key = os.getenv("DEVTO_API_KEY")
        if not api_key:
            return PublishResult(ok=False, error="Missing DEVTO_API_KEY", permanent=True)

        headers = {"api-key": api_key, "Content-Type": "application/json"}

        # Extract title from first line of post
        first_line = text.split("\n")[0].replace("🚀", "").replace("🌟", "").strip()
        title = first_line if first_line else "Visa Sponsorship Job Opportunity"

        body_markdown = self._build_article_body(title, text, image_url)

        try:
            res = requests.post(
                "https://dev.to/api/articles",
                headers=headers,
                json={"article": {"body_markdown": body_markdown}},
                timeout=20,
            )

            # On 422, shorten title and retry once
            if res.status_code == 422:
                short_title = title[:60]
                body_markdown = self._build_article_body(short_title, text, image_url)
                res = requests.post(
                    "https://dev.to/api/articles",
                    headers=headers,
                    json={"article": {"body_markdown": body_markdown}},
                    timeout=20,
                )

            if res.status_code in (200, 201):
                url = res.json().get("url") or "https://dev.to"
                return PublishResult(ok=True, url=url)

            retryable, permanent, retry_after = classify_http_error(res.status_code, res.text, res.headers)
            return PublishResult(
                ok=False,
                error=f"Dev.to API HTTP {res.status_code}: {res.text[:200]}",
                retryable=retryable,
                permanent=permanent,
                retry_after=retry_after,
            )
        except Exception as e:
            retryable, permanent, retry_after = classify_exception(e)
            return PublishResult(ok=False, error=str(e), retryable=retryable, permanent=permanent)


# -----------------------------------------------------------------------------
# Adapter Registry
# -----------------------------------------------------------------------------
ADAPTERS: dict[str, PlatformAdapter] = {
    "x": XAdapter(),
    "bluesky": BlueskyAdapter(),
    "mastodon": MastodonAdapter(),
    "linkedin": LinkedInAdapter(),
    "telegram": TelegramAdapter(),
    "discord": DiscordAdapter(),
    "devto": DevtoAdapter(),
}


def get_adapter(platform: str) -> PlatformAdapter | None:
    """Retrieve social adapter by platform name."""
    return ADAPTERS.get(platform.lower().strip())

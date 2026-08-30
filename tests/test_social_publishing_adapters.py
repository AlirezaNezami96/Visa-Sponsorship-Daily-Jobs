"""Comprehensive test suite for Multi-Platform Social Publishing (Mocked HTTP - Zero Real Network).

Tests all 7 platform adapters, kill switches, dry-run mode, image compression,
text truncation, retry backoff, and error taxonomy.
"""
import io
import os
from unittest.mock import MagicMock, patch

from PIL import Image

from job_radar.social.adapters import (
    BlueskyAdapter,
    DevtoAdapter,
    DiscordAdapter,
    LinkedInAdapter,
    MastodonAdapter,
    PublishResult,
    TelegramAdapter,
    XAdapter,
)
from job_radar.social.image_prep import prepare_image_for_platform
from job_radar.social.kill_switch import can_publish, dry_run, global_enabled
from job_radar.social.platform_publisher import publish_next_job
from job_radar.social.retry import execute_with_retry
from job_radar.social.text_prep import get_text_length, truncate_keep_url
from scripts.check_social_credentials import check_credentials_for_platform
from scripts.check_social_credentials import main as check_creds_main


# =============================================================================
# 1. Kill Switch & Enable Flow Tests
# =============================================================================
def test_kill_switch_defaults_to_disabled():
    with patch.dict(os.environ, {}, clear=True):
        assert global_enabled() is False
        assert dry_run() is True


def test_can_publish_gates():
    mock_client = MagicMock()
    # 1. Global disabled -> False
    with patch.dict(os.environ, {"SOCIAL_PUBLISHING_ENABLED": "false"}):
        ok, reason = can_publish(mock_client, "bluesky")
        assert ok is False
        assert "global kill switch" in reason

    # 2. Global enabled but platform disabled in DB -> False
    mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"enabled": False}
    with patch.dict(os.environ, {"SOCIAL_PUBLISHING_ENABLED": "true"}):
        ok, reason = can_publish(mock_client, "bluesky")
        assert ok is False
        assert "disabled in platform_post_config" in reason

    # 3. Both enabled -> True
    mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"enabled": True}
    with patch.dict(os.environ, {"SOCIAL_PUBLISHING_ENABLED": "true"}):
        ok, reason = can_publish(mock_client, "bluesky")
        assert ok is True


def test_publish_next_job_disabled_zero_network_calls():
    mock_client = MagicMock()
    with patch.dict(os.environ, {"SOCIAL_PUBLISHING_ENABLED": "false"}), patch("requests.post") as mock_post:
        res = publish_next_job(mock_client, "x")
        assert res["ok"] is True
        assert res["action"] == "disabled"
        assert mock_post.called is False


def test_publish_next_job_dry_run_zero_network_calls():
    mock_client = MagicMock()
    # Mock DB allow
    mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"enabled": True}
    mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"job_id": "uuid-123", "post_text": '{"bluesky": "Test post"}', "image_url": "https://example.com/img.jpg"}
    ]

    with patch.dict(os.environ, {"SOCIAL_PUBLISHING_ENABLED": "true", "PUBLISH_DRY_RUN": "true"}), \
         patch("job_radar.pipeline.state_machine.transition_stage", return_value={"ok": True}), \
         patch("requests.post") as mock_post:

        res = publish_next_job(mock_client, "bluesky")
        assert res["ok"] is True
        assert res["action"] == "dry_run"
        assert res["url"] == "dry-run"
        assert mock_post.called is False


# =============================================================================
# 2. Text Prep & Image Prep Tests
# =============================================================================
def test_text_prep_truncation_preserves_url():
    long_text = (
        "🚀 Senior Backend Engineer @ Stripe\n"
        "📍 Location: Berlin, Germany\n"
        "💰 Salary: €90,000 - €120,000 / year\n"
        "> Summary: We are building high-scale financial infrastructure across Europe.\n"
        "💡 Key requirements include 5+ years with Python, PostgreSQL, and distributed systems.\n"
        "Apply: https://visalane.online/jobs/stripe-swe-123"
    )

    # 1. Truncate to 140 chars
    shortened = truncate_keep_url(long_text, 140)
    assert len(shortened) <= 140
    assert "https://visalane.online/jobs/stripe-swe-123" in shortened
    assert shortened.endswith("https://visalane.online/jobs/stripe-swe-123")


def test_text_prep_bluesky_grapheme_counting():
    text = "Visa sponsorship in Berlin 🇩🇪 🇪🇺 🌍 https://visalane.online/jobs/123"
    grapheme_len = get_text_length(text, is_grapheme=True)
    char_len = get_text_length(text, is_grapheme=False)
    # Emoji flags have multiple unicode code points per grapheme
    assert grapheme_len < char_len


def test_image_prep_compression_ladder():
    # Create large dummy image in memory
    img = Image.new("RGB", (2000, 2000), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    large_bytes = buf.getvalue()

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = large_bytes
        mock_get.return_value = mock_resp

        # Target max bytes: 100KB
        compressed = prepare_image_for_platform("https://example.com/card.jpg", max_bytes=100_000)
        assert compressed is not None
        assert len(compressed) <= 100_000


# =============================================================================
# 3. Adapter Unit Tests (Mocked HTTP)
# =============================================================================
def test_x_adapter_success_and_fallback():
    adapter = XAdapter()
    env = {
        "X_API_KEY": "k",
        "X_API_SECRET": "s",
        "X_ACCESS_TOKEN": "t",
        "X_ACCESS_TOKEN_SECRET": "ts",
    }

    with patch.dict(os.environ, env), patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"data": {"id": "1890000000000000000", "url": "https://x.com/i/status/189"}}
        mock_post.return_value = mock_resp

        res = adapter.publish("Software Engineer @ Acme https://visalane.online/1")
        assert res.ok is True
        assert "189" in res.url


def test_x_adapter_duplicate_done_with_warning():
    adapter = XAdapter()
    env = {"X_API_KEY": "k", "X_API_SECRET": "s", "X_ACCESS_TOKEN": "t", "X_ACCESS_TOKEN_SECRET": "ts"}
    with patch.dict(os.environ, env), patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = '{"errors":[{"message":"You are not allowed to create a Tweet with duplicate content."}]}'
        mock_post.return_value = mock_resp

        res = adapter.publish("Duplicate post")
        assert res.ok is True
        assert res.warning == "duplicate_post_ignored"


def test_bluesky_adapter_success_and_blob_upload():
    adapter = BlueskyAdapter()
    env = {"BLUESKY_HANDLE": "visalane.online", "BLUESKY_APP_PASSWORD": "pass"}

    with patch.dict(os.environ, env), patch("requests.post") as mock_post:
        def fake_post(url, *args, **kwargs):
            m = MagicMock()
            if "createSession" in url:
                m.status_code = 200
                m.json.return_value = {"accessJwt": "jwt123", "did": "did:plc:123"}
            elif "uploadBlob" in url:
                m.status_code = 200
                m.json.return_value = {"blob": {"$type": "blob", "ref": {"$link": "cid123"}}}
            elif "createRecord" in url:
                m.status_code = 200
                m.json.return_value = {"uri": "at://did:plc:123/app.bsky.feed.post/3kabc123"}
            return m

        mock_post.side_effect = fake_post

        res = adapter.publish("Bluesky job post", image_bytes=b"small_image_bytes")
        assert res.ok is True
        assert "3kabc123" in res.url


def test_mastodon_adapter_async_media_poll():
    adapter = MastodonAdapter()
    env = {"MASTODON_INSTANCE_URL": "https://mastodon.social/", "MASTODON_ACCESS_TOKEN": "tok"}

    with patch.dict(os.environ, env), patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        # Mock media upload (202 async)
        mock_media_resp = MagicMock()
        mock_media_resp.status_code = 202
        mock_media_resp.json.return_value = {"id": "media-999"}
        mock_post.return_value = mock_media_resp

        # Mock media polling (200 with url)
        mock_poll_resp = MagicMock()
        mock_poll_resp.status_code = 200
        mock_poll_resp.json.return_value = {"id": "media-999", "url": "https://mastodon.social/media/999.jpg"}
        mock_get.return_value = mock_poll_resp

        # Mock status post
        mock_status_resp = MagicMock()
        mock_status_resp.status_code = 200
        mock_status_resp.json.return_value = {"url": "https://mastodon.social/@visalane/123456"}
        mock_post.side_effect = [mock_media_resp, mock_status_resp]

        res = adapter.publish("Mastodon post", image_bytes=b"img")
        assert res.ok is True
        assert res.url == "https://mastodon.social/@visalane/123456"


def test_linkedin_adapter_refresh_token_on_401():
    adapter = LinkedInAdapter()
    env = {
        "LINKEDIN_ACCESS_TOKEN": "old_token",
        "LINKEDIN_REFRESH_TOKEN": "ref_token",
        "LINKEDIN_CLIENT_ID": "client_id",
        "LINKEDIN_CLIENT_SECRET": "client_secret",
    }

    with patch.dict(os.environ, env), patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        # userinfo: first call 401, second call 200
        resp_401 = MagicMock(status_code=401, text="Expired token")
        resp_200 = MagicMock(status_code=200, json=lambda: {"sub": "person_123"})
        mock_get.side_effect = [resp_401, resp_200]

        # accessToken refresh response
        resp_refresh = MagicMock(status_code=200, json=lambda: {"access_token": "new_fresh_token"})
        # post creation response
        resp_post = MagicMock(status_code=201, headers={"x-restli-id": "urn:li:share:789"})
        mock_post.side_effect = [resp_refresh, resp_post]

        res = adapter.publish("LinkedIn job posting text")
        assert res.ok is True
        assert "789" in res.url


def test_telegram_adapter_429_retry_after():
    adapter = TelegramAdapter()
    env = {"TELEGRAM_BOT_TOKEN": "bot123", "TELEGRAM_CHAT_ID": "-100123456"}

    with patch.dict(os.environ, env), patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = '{"ok":false,"error_code":429,"description":"Too Many Requests: retry after 25","parameters":{"retry_after":25}}'
        mock_post.return_value = mock_resp

        res = adapter.publish("Telegram post")
        assert res.ok is False
        assert res.retryable is True
        assert res.retry_after == 25.0


def test_discord_adapter_404_permanent():
    adapter = DiscordAdapter()
    env = {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/invalid/token"}

    with patch.dict(os.environ, env), patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = '{"message": "Unknown Webhook", "code": 10015}'
        mock_post.return_value = mock_resp

        res = adapter.publish("Discord notification")
        assert res.ok is False
        assert res.permanent is True


def test_devto_adapter_422_title_retry():
    adapter = DevtoAdapter()
    env = {"DEVTO_API_KEY": "key123"}

    with patch.dict(os.environ, env), patch("requests.post") as mock_post:
        resp_422 = MagicMock(status_code=422, text="Title is too long")
        resp_201 = MagicMock(status_code=201, json=lambda: {"url": "https://dev.to/visalane/article-1"})
        mock_post.side_effect = [resp_422, resp_201]

        res = adapter.publish("🚀 Extremely long job title that triggers validation error\nDetails here")
        assert res.ok is True
        assert res.url == "https://dev.to/visalane/article-1"


def test_retry_helper_skips_permanent_errors():
    call_count = 0

    def failing_permanent():
        nonlocal call_count
        call_count += 1
        return PublishResult(ok=False, error="401 Unauthorized", permanent=True)

    result = execute_with_retry(failing_permanent, max_attempts=3)
    assert result.ok is False
    assert call_count == 1  # No retries on permanent errors


# =============================================================================
# 4. Credential Validation Script Tests
# =============================================================================
def test_check_social_credentials_not_configured():
    with patch.dict(os.environ, {}, clear=True):
        platform, status, details = check_credentials_for_platform("x")
        assert status == "NOT_CONFIGURED"

        # Main exits with 0 when all are not configured
        exit_code = check_creds_main([])
        assert exit_code == 0

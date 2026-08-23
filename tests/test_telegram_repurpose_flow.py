"""Tests for LinkedIn Repurpose Pipeline + Telegram Approval Integration."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from job_radar.repurpose.models import ProcessingStatus, SourcePostRecord
from job_radar.repurpose.orchestrator import RepurposeOrchestrator
from job_radar.social.publisher import check_and_publish_post, trigger_repurpose_workflow


@pytest.fixture
def mock_supabase():
    mock = MagicMock()
    post_dict = {
        "id": 42,
        "source_post_id": "test_post_42",
        "author_name": "Ramm Codes",
        "content": "Original technical post about Python and AI.",
        "media_type": "image",
        "media_count": 1,
        "processing_status": "available",
    }
    mock.get_available_post.return_value = post_dict
    mock.reserve_next_post.return_value = post_dict
    mock.claim_post_for_processing.return_value = True
    return mock


def test_send_telegram_repurpose_draft_markup(tmp_path):
    orchestrator = RepurposeOrchestrator()
    post = SourcePostRecord(
        id=42,
        source_post_id="post_42",
        source_url="https://linkedin.com/posts/post_42",
        author_name="Ramm Codes",
        content="Original content",
        media_type="image",
    )

    test_img = tmp_path / "preview.jpg"
    test_img.write_bytes(b"mock_image_bytes")

    with patch("requests.post") as mock_post:
        # Mock sendPhoto and sendMessage
        mock_resp_photo = MagicMock(status_code=200)
        mock_resp_photo.json.return_value = {"result": {"message_id": 1001}}
        mock_resp_msg = MagicMock(status_code=200)
        mock_resp_msg.json.return_value = {"result": {"message_id": 1002}}
        mock_post.side_effect = [mock_resp_photo, mock_resp_msg]

        ok, msg_id = orchestrator.send_telegram_draft(
            post=post,
            adapted_text="Adapted post text for LinkedIn.",
            media_files=[test_img],
            bot_token="test_token",
            chat_id="123456",
        )

        assert ok is True
        assert msg_id == 1002

        # Verify buttons in sendMessage payload
        call_args = mock_post.call_args_list[1]
        payload = call_args.kwargs.get("json", {})
        keyboard = payload.get("reply_markup", {}).get("inline_keyboard", [])
        
        assert len(keyboard) == 2
        assert keyboard[0][0]["text"] == "✅ Accept"
        assert keyboard[0][0]["callback_data"] == "approve"
        assert keyboard[1][0]["text"] == "❌ Reject"
        assert keyboard[1][0]["callback_data"] == "reject"
        assert keyboard[1][1]["text"] == "🔄 Reject & Generate Another"
        assert keyboard[1][1]["callback_data"] == "reject_regen"


def test_orchestrator_stages_pending_approval(mock_supabase, tmp_path):
    orchestrator = RepurposeOrchestrator(supabase_client=mock_supabase)
    test_img = tmp_path / "image_1.jpg"
    test_img.write_bytes(b"mock_image_bytes")

    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot_token_123", "TELEGRAM_CHAT_ID": "chat_456"}), \
         patch.object(orchestrator.media_mgr, "prepare_post_media", return_value=(True, [test_img], None)), \
         patch.object(orchestrator.rewriter, "adapt_post", return_value=(True, "Rewritten post", None)), \
         patch.object(orchestrator, "send_telegram_draft", return_value=(True, 5555)), \
         patch("job_radar.repurpose.orchestrator.Path.mkdir"), \
         patch("job_radar.filters.dedupe.atomic_save_json") as mock_save_json:

        res = orchestrator.run(dry_run=False, auto_publish=False)

        assert res.success is True
        assert res.status == "pending_approval"
        mock_supabase.update_post_status.assert_called_with(
            post_id=42,
            status=ProcessingStatus.PENDING_APPROVAL.value,
            execution_id=mock_supabase.update_post_status.call_args.kwargs["execution_id"],
            generated_content="Rewritten post",
        )
        assert mock_save_json.called


def test_check_and_publish_repurpose_approve(tmp_path):
    pending_file = tmp_path / "pending_linkedin_post.json"
    pending_state = {
        "is_repurpose": True,
        "database_id": 42,
        "source_post_id": "post_42",
        "text": "Approved repurposed post text",
        "media_type": "none",
        "media_files": [],
        "message_id": 8888,
        "chat_id": "123456",
        "execution_id": "worker-1",
    }
    pending_file.write_text(json.dumps(pending_state), encoding="utf-8")

    env_vars = {
        "TELEGRAM_BOT_TOKEN": "bot123",
        "TELEGRAM_CHAT_ID": "123456",
        "TELEGRAM_AUTHORIZED_USER_ID": "999",
        "LINKEDIN_ACCESS_TOKEN": "token_li",
        "CLIENT_PAYLOAD": json.dumps({"action": "approve", "message_id": 8888, "user_id": 999}),
    }

    with patch.dict(os.environ, env_vars), \
         patch("job_radar.social.publisher.PENDING_FILE", str(pending_file)), \
         patch("job_radar.repurpose.publisher.LinkedInRepurposePublisher.publish_post", return_value=(True, 201, "urn:li:share:123", "{}", "https://linkedin.com/feed/update/urn:li:share:123")), \
         patch("job_radar.storage.supabase_client.SupabaseStorageClient.update_post_status") as mock_update_status, \
         patch("job_radar.social.publisher.edit_telegram_message") as mock_edit_tg, \
         patch("job_radar.social.publisher.send_telegram_message") as mock_send_tg:

        check_and_publish_post()

        mock_update_status.assert_called_with(
            post_id=42,
            status=ProcessingStatus.PUBLISHED.value,
            execution_id="worker-1",
            published_linkedin_post_id="urn:li:share:123",
            published_linkedin_url="https://linkedin.com/feed/update/urn:li:share:123",
            published_at="now()",
            final_content="Approved repurposed post text",
        )
        assert mock_edit_tg.called
        assert mock_send_tg.called


def test_check_and_publish_repurpose_reject_regen(tmp_path):
    pending_file = tmp_path / "pending_linkedin_post.json"
    pending_state = {
        "is_repurpose": True,
        "database_id": 42,
        "source_post_id": "post_42",
        "text": "Rejected repurposed post text",
        "media_type": "none",
        "media_files": [],
        "message_id": 8888,
        "chat_id": "123456",
        "execution_id": "worker-1",
    }
    pending_file.write_text(json.dumps(pending_state), encoding="utf-8")

    env_vars = {
        "TELEGRAM_BOT_TOKEN": "bot123",
        "TELEGRAM_CHAT_ID": "123456",
        "TELEGRAM_AUTHORIZED_USER_ID": "999",
        "LINKEDIN_ACCESS_TOKEN": "token_li",
        "CLIENT_PAYLOAD": json.dumps({"action": "reject_regen", "message_id": 8888, "user_id": 999}),
    }

    with patch.dict(os.environ, env_vars), \
         patch("job_radar.social.publisher.PENDING_FILE", str(pending_file)), \
         patch("job_radar.storage.supabase_client.SupabaseStorageClient.update_post_status") as mock_update_status, \
         patch("job_radar.social.publisher.edit_telegram_message") as mock_edit_tg, \
         patch("job_radar.social.publisher.send_telegram_message") as mock_send_tg, \
         patch("job_radar.social.publisher.trigger_repurpose_workflow") as mock_trigger:

        check_and_publish_post()

        mock_update_status.assert_called_with(
            post_id=42,
            status=ProcessingStatus.SKIPPED.value,
            execution_id="worker-1",
            skipped_reason="Rejected via Telegram (requested regeneration)",
        )
        assert mock_edit_tg.called
        assert mock_send_tg.called
        assert mock_trigger.called

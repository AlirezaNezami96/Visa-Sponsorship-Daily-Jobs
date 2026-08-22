"""Unit tests for Telegram interactive job inbox and callback query actions."""
import pytest
from unittest.mock import MagicMock, patch

from job_radar.crm.models import JobStatus
from job_radar.crm.db import init_crm_db, upsert_crm_job, get_job_by_id
from job_radar.notifications.telegram_inbox import send_telegram_job_card, handle_telegram_job_callback


def test_send_telegram_job_card(tmp_path):
    db_file = tmp_path / "test_crm.db"
    init_crm_db(db_file)

    job = {
        "company": "DeepMind",
        "title": "Senior AI Engineer",
        "location": "London",
        "visa_confidence": "on_sponsor_list",
        "composite": 89.2,
        "ats_score": 85,
        "url": "https://deepmind.google/careers/123",
        "snippet": "Join our research team to build foundation models.",
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp) as mock_post:
        with patch("job_radar.notifications.telegram_inbox.upsert_crm_job", return_value=upsert_crm_job(job, db_path=db_file)):
            sent = send_telegram_job_card(job, bot_token="fake_token", chat_id="fake_chat")
            assert sent is True
            assert mock_post.called
            # Verify payload contains inline buttons
            payload = mock_post.call_args[1]["json"]
            assert "reply_markup" in payload
            assert len(payload["reply_markup"]["inline_keyboard"][0]) == 3


def test_handle_telegram_job_callback(tmp_path):
    db_file = tmp_path / "test_crm.db"
    init_crm_db(db_file)

    created = upsert_crm_job(
        {
            "company": "Stripe",
            "title": "Backend SWE",
            "url": "https://stripe.com/jobs/1",
        },
        db_path=db_file,
    )

    with patch("job_radar.notifications.telegram_inbox.update_job_status") as mock_update:
        # Test apply callback
        ok, msg = handle_telegram_job_callback(
            callback_data=f"job:apply:{created.id}",
            callback_query_id="query_123",
            bot_token="fake_token",
        )
        assert ok is True
        assert "APPLIED" in msg
        mock_update.assert_called_with(created.id, JobStatus.APPLIED, notes="Applied via Telegram")

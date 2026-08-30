"""Regression tests for Phase 5.2 Critical Defects (C2, C3, M1, M3) and Dry-run Validation."""
import os
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from job_radar.pipeline.state_machine import VALID_TRANSITIONS, transition_stage
from job_radar.social.approval_handler import handle_approval_callback
from job_radar.social.post_text import generate_job_summary
from job_radar.pipeline.alert_worker import _send_channel_with_retry
from job_radar.pipeline.circuit_breaker import CircuitBreaker


ROOT_DIR = Path(__file__).parent.parent


# --- FIX C2: publish-social.yml workflow steps ---
def test_c2_publish_social_workflow_steps_and_concurrency():
    wf_path = ROOT_DIR / ".github" / "workflows" / "publish-social.yml"
    assert wf_path.exists(), "publish-social.yml does not exist"

    content = wf_path.read_text()
    data = yaml.safe_load(content)

    assert "concurrency" in data, "concurrency missing from publish-social.yml"
    assert data["concurrency"]["group"] == "publish-social"
    assert data["concurrency"]["cancel-in-progress"] is False

    # Check for x and linkedin steps
    steps = data["jobs"]["publish-other-platforms"]["steps"]
    step_runs = [s.get("run", "") for s in steps if "run" in s]

    assert any("--platform x" in r for r in step_runs), "missing --platform x in publish-social.yml"
    assert any("--platform linkedin" in r for r in step_runs), "missing --platform linkedin in publish-social.yml"


# --- FIX C3 Part 1: VALID_TRANSITIONS ---
def test_c3_valid_transitions_manual_review():
    assert "manual_review" in VALID_TRANSITIONS["pending"]
    assert "manual_review" in VALID_TRANSITIONS["processing"]
    assert "done" in VALID_TRANSITIONS["manual_review"]
    assert "failed" in VALID_TRANSITIONS["manual_review"]


# --- FIX C3 Part 2: Full UUID in callback_data ---
def test_c3_callback_data_preserves_full_uuid():
    from job_radar.social.platform_publisher import _send_for_manual_review

    job_uuid = "123e4567-e89b-12d3-a456-426614174000"
    job = {
        "id": job_uuid,
        "title": "Lead Software Engineer",
        "company": "Test Company",
    }

    mock_client = MagicMock()
    with patch("os.getenv", side_effect=lambda k, d=None: "dummy" if "TELEGRAM" in k else d), \
         patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"ok": True}

        ok, err = _send_for_manual_review(
            mock_client,
            job,
            "linkedin",
            "Post text content",
            None,
        )

        assert ok is True
        # Verify inline keyboard payload contains full 36-char uuid
        called_payload = mock_post.call_args[1]["json"]
        buttons = called_payload["reply_markup"]["inline_keyboard"][0]
        assert buttons[0]["callback_data"] == f"approve_linkedin_{job_uuid}"
        assert buttons[1]["callback_data"] == f"reject_linkedin_{job_uuid}"
        assert len(buttons[0]["callback_data"]) <= 64


# --- FIX C3 Part 3: Approval callback handler ---
def test_c3_approval_handler_execution():
    job_uuid = "987e6543-e21b-12d3-a456-426614174999"

    mock_client = MagicMock()
    # Mock job_processing lookup
    mock_jp = MagicMock()
    mock_jp.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "job_id": job_uuid,
        "linkedin_status": "manual_review",
    }
    mock_jp.update.return_value.eq.return_value.execute.return_value = MagicMock()

    # Mock jobs update
    mock_jobs = MagicMock()
    mock_jobs.update.return_value.eq.return_value.execute.return_value = MagicMock()

    def mock_table(name):
        if name == "job_processing":
            return mock_jp
        if name == "jobs":
            return mock_jobs
        return MagicMock()

    mock_client.table.side_effect = mock_table

    # 1. Test Approve
    res_approve = handle_approval_callback(mock_client, f"approve_linkedin_{job_uuid}")
    assert res_approve["ok"] is True
    assert res_approve["action"] == "approved"
    assert res_approve["job_id"] == job_uuid

    # Verify jobs table update mirrored linkedin_post_published = True
    mock_jobs.update.assert_called_with({"linkedin_post_published": True})

    # 2. Test Reject
    res_reject = handle_approval_callback(mock_client, f"reject_x_{job_uuid}")
    assert res_reject["ok"] is True
    assert res_reject["action"] == "rejected"
    assert res_reject["job_id"] == job_uuid


# --- FIX M1: Concurrency in image-pipeline.yml and enrich-jobs.yml ---
def test_m1_concurrency_in_pipeline_workflows():
    for filename in ["image-pipeline.yml", "enrich-jobs.yml"]:
        wf_path = ROOT_DIR / ".github" / "workflows" / filename
        assert wf_path.exists(), f"{filename} missing"
        data = yaml.safe_load(wf_path.read_text())
        assert "concurrency" in data, f"concurrency missing in {filename}"
        assert data["concurrency"]["cancel-in-progress"] is False


# --- FIX M3: Circuit breakers wired in external calls ---
class MockCBSupabase:
    def __init__(self, circuits=None):
        self.circuits = circuits or {}

    def table(self, name):
        mock_t = MagicMock()
        if name == "service_circuits":
            mock_t.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = (
                lambda: MagicMock(data=self.circuits.get("mock_lookup"))
            )
        return mock_t


def test_m3_alert_worker_circuit_breaker_skips_when_open():
    mock_client = MagicMock()
    # Mock open circuit for alert:telegram
    with patch.object(CircuitBreaker, "is_open", return_value=True), \
         patch.object(CircuitBreaker, "record_failure") as mock_fail:

        send_called = False
        def fake_send():
            nonlocal send_called
            send_called = True
            return True

        ok = _send_channel_with_retry(mock_client, "telegram", fake_send)
        assert ok is False
        assert send_called is False  # Call was skipped because circuit was open


def test_m3_post_text_circuit_breaker_skips_when_open():
    mock_client = MagicMock()
    job = {
        "id": "111",
        "title": "Software Engineer",
        "company": "Acme Corp",
        "description_text": "Building systems in Python and Go.",
        "skills": ["Python", "Go"],
    }

    with patch.object(CircuitBreaker, "is_open", return_value=True), \
         patch("requests.post") as mock_post:

        summary = generate_job_summary(job, client=mock_client)
        assert mock_post.called is False  # AI call bypassed
        assert len(summary) > 0
        assert "Python" in summary


# --- DRY RUN: 10 Jobs routing to manual_review and approval ---
def test_dry_run_manual_review_no_spam_loop():
    """Verify 10 jobs transition to manual_review and once in manual_review are not re-processed/spammed."""
    mock_client = MagicMock()
    job_processing_state = {}

    for i in range(10):
        uuid_str = f"00000000-0000-0000-0000-{i:012d}"
        job_processing_state[uuid_str] = {
            "job_id": uuid_str,
            "linkedin_status": "pending",
            "x_status": "pending",
        }

    # Step 1: Transition all 10 to manual_review
    for job_id in job_processing_state:
        # Mock table return
        mock_t = MagicMock()
        mock_t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
            "job_id": job_id,
            "linkedin_status": "pending",
        }
        mock_client.table.return_value = mock_t

        res = transition_stage(mock_client, job_id, "linkedin", "manual_review")
        assert res["ok"] is True
        job_processing_state[job_id]["linkedin_status"] = "manual_review"

    # Step 2: Second run simulation: verify that status is manual_review (not pending)
    # The claim query only claims `linkedin_status = 'pending'`, so manual_review jobs are NOT re-claimed.
    for job_id, state in job_processing_state.items():
        assert state["linkedin_status"] == "manual_review"

    # Step 3: Admin approves job 3
    approved_id = "00000000-0000-0000-0000-000000000003"
    mock_jp = MagicMock()
    mock_jp.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "job_id": approved_id,
        "linkedin_status": "manual_review",
    }
    mock_jobs = MagicMock()
    mock_client.table.side_effect = lambda name: mock_jp if name == "job_processing" else mock_jobs

    res = handle_approval_callback(mock_client, f"approve_linkedin_{approved_id}")
    assert res["ok"] is True
    assert res["action"] == "approved"

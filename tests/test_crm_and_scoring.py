"""Unit tests for Composite Scoring calculation and CRM lifecycle transitions."""
import time
import pytest
from pathlib import Path

from job_radar.scoring.composite import compute_composite_score, calculate_visa_score, calculate_recency_score
from job_radar.crm.models import JobStatus
from job_radar.crm.db import init_crm_db, upsert_crm_job, update_job_status, list_crm_jobs, get_due_followups


def test_composite_score_math():
    job = {
        "title": "Machine Learning Engineer",
        "company": "DeepMind",
        "visa_confidence": "on_sponsor_list",
        "salary_min": 90000,
        "remote_scope": "worldwide",
        "date_posted": None,
        "first_seen_at": time.time(),
        "sponsor_meta": {"rating": "A"},
    }

    score = compute_composite_score(job, ats_score=80)
    # 0.30*80 (24) + 0.25*80 (20) + 0.15*100 (15) + 0.10*100 (10) + 0.10*100 (10) + 0.10*75 (7.5) = 86.5
    assert 80 <= score <= 95


def test_crm_state_transitions(tmp_path):
    db_file = tmp_path / "test_crm.db"
    init_crm_db(db_file)

    job_data = {
        "_fingerprint": "stripe|ml_engineer|remote",
        "url": "https://stripe.com/jobs/123",
        "company": "Stripe",
        "title": "ML Engineer",
        "composite": 88.5,
        "visa_confidence": "on_sponsor_list",
    }

    # 1. Upsert new job
    created = upsert_crm_job(job_data, db_path=db_file)
    assert created.status == JobStatus.NEW
    assert created.company == "Stripe"

    # 2. Transition to APPLYING
    applying = update_job_status(created.id, JobStatus.APPLYING, db_path=db_file)
    assert applying.status == JobStatus.APPLYING

    # 3. Transition to APPLIED (triggers applied_at and followup_at)
    applied = update_job_status(created.id, JobStatus.APPLIED, db_path=db_file)
    assert applied.status == JobStatus.APPLIED
    assert applied.applied_at is not None
    assert applied.followup_at is not None
    assert "follow-up" in applied.next_action.lower()

    # 4. Check list jobs
    jobs = list_crm_jobs(status=JobStatus.APPLIED, db_path=db_file)
    assert len(jobs) == 1
    assert jobs[0].id == created.id


def test_crm_due_followups(tmp_path):
    db_file = tmp_path / "test_crm.db"
    init_crm_db(db_file)

    # Insert a job applied 4 days ago
    past_time = time.time() - (4 * 86400)
    created = upsert_crm_job(
        {
            "_fingerprint": "meta|swe|remote",
            "url": "https://meta.com/jobs/456",
            "company": "Meta",
            "title": "Software Engineer",
            "composite": 85.0,
        },
        db_path=db_file,
    )
    # Force followup_at in the past
    applied = update_job_status(created.id, JobStatus.APPLIED, db_path=db_file)
    with pytest.MonkeyPatch.context() as mp:
        import sqlite3
        conn = sqlite3.connect(str(db_file))
        conn.execute("UPDATE crm_jobs SET followup_at = ? WHERE id = ?", (past_time, created.id))
        conn.commit()
        conn.close()

    due = get_due_followups(db_path=db_file)
    assert len(due) == 1
    assert due[0].company == "Meta"

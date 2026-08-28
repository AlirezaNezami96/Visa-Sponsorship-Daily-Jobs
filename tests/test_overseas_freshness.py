"""Overseas freshness: jobs without a posted date must survive the freshness filter.

Overseas sources frequently omit dates. Dropping them would nuke most of the
expansion yield, so `posted_at=None` fails open (is kept). See pipeline/filter.py.
"""
import datetime

from job_radar.models.config import JobSearchConfig
from job_radar.pipeline.filter import filter_job, is_job_fresh


def _overseas_job(posted_at=None):
    from job_radar.models.job import Job

    return Job(
        id="ov-x.example-abc",
        source="overseas",
        ats="x.example",
        title="Mason",
        company="Agency",
        description="Masonry work in Dubai, food and accommodation provided.",
        country="UAE",
        apply_url="https://x.example/jobs/1",
        posted_at=posted_at,
        metadata={"overseas": True, "source_category": "manpower_agency"},
    )


def test_missing_posted_at_survives_freshness_with_30_day_window():
    job = _overseas_job(posted_at=None)
    assert is_job_fresh(job, 30) is True
    cfg = JobSearchConfig(posted_within_days=30)
    assert filter_job(job, cfg) is True


def test_recent_posted_at_survives():
    now = datetime.datetime.now(datetime.timezone.utc)
    job = _overseas_job(posted_at=now - datetime.timedelta(days=2))
    assert is_job_fresh(job, 30) is True


def test_stale_posted_at_is_dropped():
    now = datetime.datetime.now(datetime.timezone.utc)
    job = _overseas_job(posted_at=now - datetime.timedelta(days=60))
    assert is_job_fresh(job, 30) is False


def test_missing_date_fails_open_even_with_tight_window():
    job = _overseas_job(posted_at=None)
    assert is_job_fresh(job, 1) is True

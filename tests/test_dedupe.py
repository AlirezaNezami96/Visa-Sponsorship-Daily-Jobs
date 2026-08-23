"""Tests for within-run deduplication and fingerprint matching."""
from job_radar.models.job import Job
from job_radar.pipeline.dedupe import deduplicate_jobs


def test_deduplication_removes_identical_jobs():
    job1 = Job(
        id="gh-1",
        source="greenhouse",
        company="Stripe, Inc.",
        title="Senior Android Engineer",
        location="Berlin, Germany",
        description="Short description",
    )
    job2 = Job(
        id="remoteok-2",
        source="remoteok",
        company="Stripe",
        title="Senior Android Engineer",
        location="Berlin, Germany",
        description="Much longer and detailed description with requirements and benefits",
    )
    job3 = Job(
        id="gh-3",
        source="greenhouse",
        company="Stripe",
        title="Backend Engineer",
        location="Berlin, Germany",
        description="Different title",
    )

    deduped, dup_count = deduplicate_jobs([job1, job2, job3])
    assert dup_count == 1
    assert len(deduped) == 2

    # Should retain the ATS source version or richer description
    titles = [j.title for j in deduped]
    assert "Senior Android Engineer" in titles
    assert "Backend Engineer" in titles

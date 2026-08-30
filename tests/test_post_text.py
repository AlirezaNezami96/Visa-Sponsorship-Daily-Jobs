"""Regression tests for post text generation, Twitter 280 char limit with URL integrity, and summary boundary trimming."""
import pytest

from job_radar.social.post_text import (
    get_rotating_hook,
    generate_job_summary,
    build_platform_post_text,
    _extractive_summary,
    _trim_summary,
    HOOK_POOL,
)


def test_hook_rotation_deterministic():
    """Verify that hook selection is deterministic by job_id."""
    hook1 = get_rotating_hook("job-uuid-1")
    hook2 = get_rotating_hook("job-uuid-1")
    assert hook1 == hook2
    assert hook1 in HOOK_POOL


def test_extractive_summary_fallback():
    """Verify clean summary generation without AI."""
    desc = "We are seeking a Senior Backend Engineer to build scalable microservices in Python and Kubernetes. You will collaborate with product teams."
    skills = ["Python", "Kubernetes", "AWS"]

    summary = _extractive_summary(desc, skills)
    assert "Senior Backend Engineer" in summary
    assert "Python" in summary
    assert len(summary) <= 280


def test_summary_trim_at_sentence_boundary():
    """Verify summary trimming stops cleanly at sentence/word boundary."""
    long_text = "This is the first sentence that is complete. " + "Word " * 60
    trimmed = _trim_summary(long_text, 280)
    assert len(trimmed) <= 280
    assert not trimmed.endswith("Word Word")


def test_x_post_url_preservation_adversarial_10_cases():
    """Verify 10 adversarial long-field job cases strictly obey <=280 chars AND end with intact URL."""
    adversarial_jobs = [
        {
            "id": f"uuid-long-{i}",
            "title": "Senior Principal Staff Infrastructure Distributed Systems Cloud Architecture Engineer " * (i + 1),
            "company": "Supercalifragilistic International Global Enterprise Technology Consulting Solutions Inc " * (i + 1),
            "country": "United Kingdom of Great Britain and Northern Ireland",
            "location": "Greater London Metropolitan Area, England, United Kingdom",
            "work_mode": "Hybrid (3 days in Shoreditch Tech City Office, 2 days remote)",
            "salary_min": 150000,
            "salary_max": 220000,
            "salary_currency": "GBP",
            "apply_url": f"https://visalane.online/jobs/very-long-custom-slug-with-many-tracking-parameters-and-utm-tags-1234567890-case-{i}",
            "description_text": "Detailed requirements for building high performance distributed systems at scale.",
            "skills": ["Python", "C++", "Rust", "Distributed Systems", "Kubernetes", "Terraform", "AWS"],
        }
        for i in range(10)
    ]

    for job in adversarial_jobs:
        text = build_platform_post_text(job, "x")
        expected_url = job["apply_url"]
        assert len(text) <= 280, f"Failed length check: {len(text)} > 280 for case {job['id']}"
        assert text.endswith(expected_url), f"Failed URL integrity check: text does not end with {expected_url}"


def test_telegram_discord_post_content():
    """Verify rich formatting for Telegram and Discord."""
    job = {
        "id": "test-id-1",
        "title": "Full Stack Developer",
        "company": "Tech Corp",
        "location": "Berlin, Germany",
        "work_mode": "remote",
        "apply_url": "https://visalane.online/apply/123",
        "skills": ["React", "TypeScript", "Node.js"],
        "description_text": "Building modern web applications.",
    }

    text = build_platform_post_text(job, "telegram")
    assert "Full Stack Developer" in text
    assert "Tech Corp" in text
    assert "Berlin, Germany" in text
    assert "React" in text
    assert "https://visalane.online/apply/123" in text

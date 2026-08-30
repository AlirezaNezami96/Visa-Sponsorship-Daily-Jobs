"""Tests for social post text generation, hook rotation, character limits, and extractive fallback."""
import pytest

from job_radar.social.post_text import (
    get_rotating_hook,
    generate_job_summary,
    build_platform_post_text,
    _extractive_summary,
    HOOK_POOL,
)


def test_hook_rotation_deterministic():
    """Verify that hook selection is deterministic by job_id and covers the pool."""
    hook1 = get_rotating_hook("job-uuid-1")
    hook2 = get_rotating_hook("job-uuid-1")
    assert hook1 == hook2
    assert hook1 in HOOK_POOL

    # Different IDs should produce variety
    hooks = {get_rotating_hook(f"job-{i}") for i in range(50)}
    assert len(hooks) > 3


def test_extractive_summary_fallback():
    """Verify clean summary generation without AI."""
    desc = "We are seeking a Senior Backend Engineer to build scalable microservices in Python and Kubernetes. You will collaborate with product teams."
    skills = ["Python", "Kubernetes", "AWS"]

    summary = _extractive_summary(desc, skills)
    assert "Senior Backend Engineer" in summary
    assert "Python" in summary
    assert len(summary) <= 280


def test_x_post_character_limit():
    """Verify Twitter/X posts strictly obey the 280 char limit."""
    job = {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "title": "Senior Principal Machine Learning Research Engineer",
        "company": "Supercalifragilistic Global Enterprise Technology Solutions Inc",
        "country": "United Kingdom",
        "location": "London, England, United Kingdom",
        "work_mode": "Hybrid",
        "salary_min": 120000,
        "salary_max": 180000,
        "salary_currency": "GBP",
        "apply_url": "https://visalane.online/jobs/very-long-custom-slug-with-many-parameters-123456789",
        "description_text": "A very long detailed job description that should not overflow the 280 character hard limit on Twitter.",
        "skills": ["Python", "PyTorch", "Transformers", "Distributed Systems", "CUDA"],
    }

    text = build_platform_post_text(job, "x")
    assert len(text) <= 280
    assert "Visa Sponsored" in text or "🛂" in text


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

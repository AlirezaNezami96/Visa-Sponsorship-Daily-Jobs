"""Tests for JobSearchConfig instantiation and defaults."""
from job_radar.models.config import JobSearchConfig


def test_job_search_config_defaults():
    cfg = JobSearchConfig()
    assert cfg.keywords == []
    assert cfg.visa_sponsorship_only is True
    assert cfg.visa_registry_countries == ["UK", "US"]
    assert cfg.min_visa_confidence == "unknown"
    assert cfg.exclude_explicit_no_sponsorship is True
    assert cfg.posted_within_days == 30
    assert cfg.max_results == 200
    assert cfg.sort_by == "composite_score"
    assert cfg.sort_order == "desc"
    assert cfg.enable_ai_classification is False
    assert cfg.max_ai_calls == 200


def test_job_search_config_custom():
    cfg = JobSearchConfig(
        keywords=["Kotlin", "Android"],
        countries=["Germany"],
        remote_only=True,
        enable_ai_classification=True,
        max_results=50,
    )
    assert cfg.keywords == ["Kotlin", "Android"]
    assert cfg.countries == ["Germany"]
    assert cfg.remote_only is True
    assert cfg.enable_ai_classification is True
    assert cfg.max_results == 50

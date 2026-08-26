"""Unit tests for config mapper hardening, default source fallbacks, and AI key gating."""
import asyncio
import pytest
from apify_actor.config_mapper import input_to_config
from apify_actor.defaults import DEFAULT_SOURCES
from job_radar.pipeline.classify import classify_jobs_stage
from job_radar.models.job import Job


def _make_job(job_id: str = "1") -> Job:
    return Job(
        id=job_id,
        title="ML Engineer",
        company="Anthropic",
        url="https://example.com/job/1",
        description="Machine learning researcher position working with Python and PyTorch.",
    )


def test_default_sources_fallback():
    """Verify that when sources is omitted or empty from input, DEFAULT_SOURCES (all 12 sources) is automatically applied."""
    cfg = input_to_config({})
    assert len(cfg.sources) == 12
    assert cfg.sources == DEFAULT_SOURCES
    assert "greenhouse" in cfg.sources
    assert "himalayas" in cfg.sources
    assert "workable" in cfg.sources
    assert "smartrecruiters" in cfg.sources

    cfg_empty = input_to_config({"sources": []})
    assert len(cfg_empty.sources) == 12
    assert cfg_empty.sources == DEFAULT_SOURCES


def test_custom_sources_respected():
    """Verify that user-provided sources override DEFAULT_SOURCES."""
    cfg = input_to_config({"sources": ["greenhouse", "lever"]})
    assert cfg.sources == ["greenhouse", "lever"]


def test_ai_options_mapped_properly():
    """Verify mapping of LLM provider and API key fields."""
    cfg = input_to_config({
        "enableAIClassification": True,
        "llmProvider": "groq",
        "llmApiKey": "gsk_test12345",
        "maxAICalls": 25,
    })
    assert cfg.enable_ai_classification is True
    assert cfg.llm_provider == "groq"
    assert cfg.llm_api_key == "gsk_test12345"
    assert cfg.max_ai_calls == 25


def test_ai_zero_liability_bypass_without_key(monkeypatch):
    """Verify that when enable_ai_classification=True but no key exists, jobs are passed unclassified without errors."""
    async def _test():
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        cfg = input_to_config({
            "enableAIClassification": True,
            # No key provided
        })
        jobs = [_make_job("1"), _make_job("2")]
        result_jobs, classified_count = await classify_jobs_stage(jobs, cfg)
        
        assert classified_count == 0
        assert len(result_jobs) == 2
        assert result_jobs[0].relevance_score is None

    asyncio.run(_test())

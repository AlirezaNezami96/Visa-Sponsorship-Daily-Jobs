"""Unit tests for the unified LLM router and provider waterfall."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_radar.llm.router import LLMRouter, LLMResult, complete


def test_router_deterministic_cache(tmp_path):
    cache_file = tmp_path / "test_cache.json"
    tracker_file = tmp_path / "test_tracker.json"
    router = LLMRouter(cache_path=cache_file, tracker_path=tracker_file, daily_cap=100)

    # Inject fake cached entry
    key = router._compute_cache_key("test prompt", None, None)
    router._cache[key] = '{"test": "ok"}'
    router._save_cache()

    res = router.complete("test prompt")
    assert res.cached is True
    assert res.text == '{"test": "ok"}'
    assert res.provider == "cache"


def test_router_daily_cap(tmp_path):
    cache_file = tmp_path / "test_cache.json"
    tracker_file = tmp_path / "test_tracker.json"
    router = LLMRouter(cache_path=cache_file, tracker_path=tracker_file, daily_cap=2)

    # 1st call
    assert router._check_and_increment_daily_cap() is True
    # 2nd call
    assert router._check_and_increment_daily_cap() is True
    # 3rd call exceeds cap
    assert router._check_and_increment_daily_cap() is False


def test_router_groq_fallback(tmp_path, monkeypatch):
    cache_file = tmp_path / "test_cache.json"
    tracker_file = tmp_path / "test_tracker.json"
    router = LLMRouter(cache_path=cache_file, tracker_path=tracker_file, daily_cap=100)

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake_groq_key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"groq": "success"}'}}]
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = router.complete("Hello from test", json_schema={"type": "object"})
        assert res.provider == "groq"
        assert res.text == '{"groq": "success"}'
        assert mock_post.called


def test_router_fail_open(tmp_path, monkeypatch):
    cache_file = tmp_path / "test_cache.json"
    tracker_file = tmp_path / "test_tracker.json"
    router = LLMRouter(cache_path=cache_file, tracker_path=tracker_file, daily_cap=100)

    # No keys configured
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OLLAMA_HOST", "")

    res = router.complete("Any prompt", json_schema={"type": "object"})
    assert res.provider == "fallback"
    assert res.text == "{}"

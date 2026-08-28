"""Tests for the Python repair-then-waterfall loop (GAP 3.2 mirror)."""

from __future__ import annotations

import json
from typing import Any

from job_radar.llm.router import LLMResult, ProviderAttempt
from job_radar.llm.validated import (
    build_repair_prompt,
    parse_ai_json,
    run_validated_completion,
)


class FakeRouter:
    """Scripted per-provider responses; records every call."""

    def __init__(self, responses: dict[str, list[str | None]]):
        self.responses = responses
        self.calls: list[tuple[str, str, bool]] = []

    def try_provider(
        self,
        provider: str,
        prompt: str,
        *,
        json_schema=None,
        system_instruction=None,
        temperature: float = 0.2,
        use_cache: bool = True,
    ) -> ProviderAttempt:
        self.calls.append((provider, prompt, use_cache))
        queue = self.responses.get(provider, [])
        text = queue.pop(0) if queue else None
        if text is None:
            return ProviderAttempt(None, "provider unavailable")
        return ProviderAttempt(LLMResult(text=text, model_used=f"{provider}-model", provider=provider))

    def evict_cache(self, provider: str, prompt: str, json_schema=None) -> None:
        if not hasattr(self, "evicted"):
            self.evicted: list[tuple[str, str]] = []
        self.evicted.append((provider, prompt))


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


GOOD = {"sections": {"experience": [{"company": "Acme"}]}}


def test_parse_ai_json_plain():
    assert parse_ai_json('{"a": 1}') == {"a": 1}


def test_parse_ai_json_fenced():
    assert parse_ai_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_ai_json_prose_wrapped():
    assert parse_ai_json('Sure! Here it is: {"a": 1} hope that helps') == {"a": 1}


def test_parse_ai_json_rejects_arrays_and_garbage():
    assert parse_ai_json("[1, 2]") is None
    assert parse_ai_json("no json here") is None
    assert parse_ai_json("") is None


def test_repair_prompt_contains_violations():
    out = build_repair_prompt("BASE", "employer X invented")
    assert "BASE" in out
    assert "employer X invented" in out
    assert "REJECTED" in out


def test_first_provider_valid_passes_without_repair():
    router = FakeRouter({"gemini": [_json(GOOD)]})
    events: list[tuple[str, dict]] = []

    result = run_validated_completion(
        "make it",
        lambda parsed: None,
        router=router,
        event_sink=lambda name, meta: events.append((name, meta)),
    )

    assert result.ok
    assert result.parsed == GOOD
    assert result.provider == "gemini"
    assert result.repair_attempts == 0
    assert events == []
    assert len(router.calls) == 1


def test_repair_retry_resolves_on_same_provider():
    bad = {"sections": {"experience": [{"company": "InventedCo"}]}}
    router = FakeRouter({"gemini": [_json(bad), _json(GOOD)]})
    events: list[tuple[str, dict]] = []

    def validate(parsed):
        companies = (parsed or {}).get("sections", {}).get("experience", [])
        if any(e.get("company") == "InventedCo" for e in companies):
            return 'employer "InventedCo" does not exist'
        return None

    result = run_validated_completion(
        "make it",
        validate,
        router=router,
        event_sink=lambda name, meta: events.append((name, meta)),
    )

    assert result.ok
    assert result.parsed == GOOD
    assert result.provider == "gemini"
    assert result.repair_attempts == 1
    # repair call must bypass cache and carry the violation list
    assert router.calls[1][2] is False
    assert "InventedCo" in router.calls[1][1]
    repair_events = [e for e in events if e[0] == "ai_validation_repair"]
    assert len(repair_events) == 1
    assert repair_events[0][1]["resolved"] is True
    assert not any(e[0] == "ai_fallback_triggered" for e in events)


def test_repair_failure_advances_waterfall():
    bad = {"bad": True}
    router = FakeRouter(
        {
            "gemini": [_json(bad), _json(bad)],
            "groq": [_json(GOOD)],
        }
    )
    events: list[tuple[str, dict]] = []

    result = run_validated_completion(
        "make it",
        lambda parsed: None if parsed == GOOD else "still bad",
        router=router,
        event_sink=lambda name, meta: events.append((name, meta)),
    )

    assert result.ok
    assert result.provider == "groq"
    assert result.repair_attempts == 1
    assert result.fallbacks == ["gemini -> groq"]
    assert any(e[0] == "ai_fallback_triggered" and e[1]["from_provider"] == "gemini" for e in events)
    repair_events = [e for e in events if e[0] == "ai_validation_repair"]
    assert repair_events[0][1]["resolved"] is False


def test_provider_outage_skips_directly_to_next():
    router = FakeRouter({"openrouter": [_json(GOOD)]})
    events: list[tuple[str, dict]] = []

    result = run_validated_completion(
        "make it",
        lambda parsed: None,
        router=router,
        event_sink=lambda name, meta: events.append((name, meta)),
    )

    assert result.ok
    assert result.provider == "openrouter"
    # gemini + groq outages each recorded a fallback advance
    fallbacks = [e for e in events if e[0] == "ai_fallback_triggered"]
    assert [e[1]["from_provider"] for e in fallbacks] == ["gemini", "groq"]


def test_all_providers_exhausted_returns_failure_with_ai_error():
    router = FakeRouter({})
    events: list[tuple[str, dict]] = []

    result = run_validated_completion(
        "make it",
        lambda parsed: None,
        router=router,
        event_sink=lambda name, meta: events.append((name, meta)),
    )

    assert not result.ok
    assert result.parsed is None
    assert any(e[0] == "ai_error" for e in events)


def test_non_json_response_triggers_repair_path():
    router = FakeRouter({"gemini": ["not json at all", _json(GOOD)]})

    result = run_validated_completion(
        "make it",
        lambda parsed: None,
        router=router,
        event_sink=lambda name, meta: None,
    )

    assert result.ok
    assert result.parsed == GOOD
    assert result.repair_attempts == 1


def test_invalid_json_skips_validate_and_reports_not_valid_json():
    seen: list[Any] = []

    def validate(parsed):
        seen.append(parsed)

    router = FakeRouter({"gemini": ["garbage"]})
    events: list[tuple[str, dict]] = []
    result = run_validated_completion(
        "make it",
        validate,
        router=router,
        event_sink=lambda name, meta: events.append((name, meta)),
    )

    # validate must NOT run on unparseable output (TS parity); the repair
    # path reports the JSON failure and the loop exhausts to ai_error.
    assert not result.ok
    assert seen == []
    errors = [e for e in events if e[0] == "ai_error"]
    assert errors and "not valid JSON" in errors[0][1]["message"]


def test_default_event_sink_is_fail_open_without_supabase(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    router = FakeRouter({})

    result = run_validated_completion("make it", lambda parsed: None, router=router)

    assert not result.ok

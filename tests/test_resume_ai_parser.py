"""Unit tests for AI-powered structured resume parsing."""
from __future__ import annotations

from unittest.mock import MagicMock

from job_radar.resume.ai_parser import (
    AIResumeParser,
    build_resume_parse_prompt,
    parse_resume_with_ai,
    validate_resume_parse_output,
)


def test_build_resume_parse_prompt():
    prompt = build_resume_parse_prompt("John Doe\nSoftware Engineer at Meta")
    assert "John Doe" in prompt
    assert "HARD RULES" in prompt
    assert "JSON SCHEMA" in prompt
    assert "full_name" in prompt


def test_validate_resume_parse_output():
    assert validate_resume_parse_output({"full_name": "Alice"}) is None
    assert validate_resume_parse_output(["not", "a", "dict"]) is not None
    assert validate_resume_parse_output("string response") is not None


def test_ai_resume_parser_execution():
    import json
    from job_radar.llm.router import LLMResult, ProviderAttempt

    mock_router = MagicMock()
    mock_data = {
        "full_name": "Bob Builder",
        "email": "bob@example.com",
        "job_titles": ["Civil Engineer"],
        "skills": ["CAD", "Project Management"],
        "experience": [{"company": "ConstructCo", "title": "Lead Engineer"}],
        "education": [{"institution": "Engineering Univ", "degree": "BS"}],
    }
    mock_router.try_provider.return_value = ProviderAttempt(
        result=LLMResult(
            text=json.dumps(mock_data),
            model_used="test-model",
            provider="gemini",
        ),
        reason="",
    )
    mock_router.complete_json.return_value = mock_data

    parser = AIResumeParser(llm_router=mock_router)
    res = parser.parse("Bob Builder\nCivil Engineer\nConstructCo", user_id="user_123")

    assert res["full_name"] == "Bob Builder"
    assert res["email"] == "bob@example.com"
    assert "CAD" in res["skills"]
    assert len(res["experience"]) == 1


def test_parse_resume_with_ai_empty_text():
    assert parse_resume_with_ai("") == {}
    assert parse_resume_with_ai("   ") == {}

"""Unit tests for AI resume generator, professional & own formats, and validators."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from job_radar.ai.own_format import build_own_format_tailoring_prompt
from job_radar.ai.professional_format import build_professional_tailoring_prompt
from job_radar.ai.resume_generator import ResumeGenerator, generate_idempotency_key
from job_radar.ai.template_fetcher import get_professional_template
from job_radar.ai.validators import (
    validate_cover_letter_content,
    validate_outreach_message,
    validate_resume_grounding,
)
from job_radar.errors.base import ValidationError
from job_radar.llm.router import LLMResult, ProviderAttempt


def test_template_fetcher_fallback():
    template = get_professional_template()
    assert template["template_id"] == "visalane_ats_standard_v1"
    assert "skills" in template["section_order"]
    assert "experience" in template["section_order"]


def test_idempotency_key_generation():
    key1 = generate_idempotency_key("u1", "j1", "professional", "2026-08-29T10:00:00Z")
    key2 = generate_idempotency_key("u1", "j1", "professional", "2026-08-29T10:00:00Z")
    key3 = generate_idempotency_key("u1", "j1", "own", "2026-08-29T10:00:00Z")
    assert key1 == key2
    assert key1 != key3


def test_validate_resume_grounding_success_and_hallucination():
    source_profile = {
        "experience": [{"company": "Amazon Web Services", "title": "SDE 2"}],
        "education": [{"institution": "University of Washington", "degree": "BS"}],
    }

    # Valid tailored resume
    valid_resume = {
        "experience": [{"company": "Amazon", "title": "Software Engineer"}],
        "education": [{"institution": "University of Washington", "degree": "BS CS"}],
    }
    assert validate_resume_grounding(valid_resume, source_profile) is None

    # Hallucinated company
    hallucinated_company = {
        "experience": [{"company": "Netflix", "title": "Senior Engineer"}],
        "education": [{"institution": "University of Washington"}],
    }
    err = validate_resume_grounding(hallucinated_company, source_profile)
    assert err is not None
    assert "Netflix" in err

    # Hallucinated school
    hallucinated_school = {
        "experience": [{"company": "Amazon"}],
        "education": [{"institution": "Harvard University"}],
    }
    err2 = validate_resume_grounding(hallucinated_school, source_profile)
    assert err2 is not None
    assert "Harvard" in err2


def test_validate_cover_letter_rules():
    # Valid cover letter
    body = "Dear Hiring Team at Google,\n\n" + ("I have built scalable distributed systems with high reliability. " * 20) + "\nBest regards."
    assert validate_cover_letter_content(body, company_name="Google") is None

    # Missing company
    assert validate_cover_letter_content(body, company_name="Microsoft") is not None

    # Blocklisted phrase
    blocked = "Dear Hiring Team at Google,\n\nI am writing to apply for this role. " + ("Experience with Python and Go. " * 20)
    assert validate_cover_letter_content(blocked, company_name="Google") is not None


def test_validate_outreach_message_limits():
    linkedin_valid = "Hi Alex, noticed you are hiring for Backend Lead at VisaLane. With 6y building Python APIs, I'd love to connect!"
    email_valid = "Subject: Backend Lead Application\n\nHi Alex,\n\nI saw your opening and wanted to reach out."
    assert validate_outreach_message(linkedin_valid, email_valid) is None

    linkedin_too_long = "x" * 305
    assert validate_outreach_message(linkedin_too_long, email_valid) is not None


def test_resume_generator_fresher_block():
    generator = ResumeGenerator()
    fresher_profile = {"is_fresher": True, "skills": [], "experience": []}
    job = {"id": "j1", "title": "SWE", "company": "Acme"}

    with pytest.raises(ValidationError):
        generator.generate_tailored_resume(
            user_id="usr_123",
            profile_data=fresher_profile,
            job_data=job,
        )


def test_resume_generator_successful_flow():
    mock_router = MagicMock()
    profile = {
        "full_name": "Sarah Connor",
        "skills": ["Python", "SQL", "Docker"],
        "experience": [{"company": "Cyberdyne", "title": "Systems Engineer", "highlights": ["Security"]}],
        "education": [{"institution": "MIT", "degree": "BS"}],
    }
    job = {
        "id": "j_999",
        "title": "Senior Python Engineer",
        "company": "Cyberdyne",
        "skills": ["Python", "Docker", "PostgreSQL"],
        "description": "Looking for Senior Python Engineer to build cloud systems.",
    }

    tailored_json = {
        "full_name": "Sarah Connor",
        "summary": "Accomplished Senior Python Engineer specializing in scalable cloud systems.",
        "skills": ["Python", "Docker", "SQL", "PostgreSQL"],
        "experience": [{"company": "Cyberdyne", "title": "Senior Systems Engineer", "highlights": ["Secured cloud infra"]}],
        "education": [{"institution": "MIT", "degree": "BS"}],
    }

    mock_router.try_provider.return_value = ProviderAttempt(
        result=LLMResult(text=json.dumps(tailored_json), model_used="gemini-flash", provider="gemini"),
        reason="",
    )

    generator = ResumeGenerator(llm_router=mock_router)
    res = generator.generate_tailored_resume(
        user_id="user_777",
        profile_data=profile,
        job_data=job,
        format_type="professional",
    )

    assert res["success"] is True
    assert res["format_type"] == "professional"
    assert res["ats_score_after"] >= res["ats_score_before"]
    assert res["tailored_resume"]["full_name"] == "Sarah Connor"

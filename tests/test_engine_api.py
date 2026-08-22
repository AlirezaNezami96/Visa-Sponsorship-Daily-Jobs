"""Unit tests for engine API endpoints and 100% ATS keyword reporting."""
import pytest
from engine.api.models import ATSReport, CoverLetterRequest, GeminiResumeOutput, RewrittenResume
from engine.api.main import _compute_ats_report


def test_compute_ats_report_100_percent():
    output = GeminiResumeOutput(
        ats_keywords={
            "required": ["Kotlin", "Jetpack Compose", "Clean Architecture"],
            "preferred": ["Coroutines", "KMM"],
            "implicit": ["SOLID"],
        },
        matched_keywords=["Kotlin", "Jetpack Compose"],
        missing_entirely=["Clean Architecture"],
        rewritten_resume=RewrittenResume(),
    )

    report = _compute_ats_report(output)
    assert report.ats_score_estimate == 100
    assert len(report.missing_entirely) == 0
    assert "Clean Architecture" in report.matched_keywords
    assert "Coroutines" in report.matched_keywords


def test_cover_letter_request_defaults():
    req = CoverLetterRequest(
        session_id="test_session_123",
        job_description="We need a senior mobile engineer with Android and Flutter experience.",
    )
    assert req.company_name == "Company"
    assert req.job_title == "Software Engineer"
    assert req.user_name == "Alireza Nezami"
    assert req.tone == "professional"

"""Fixture-based tests using the real owner resume (tests/fixtures/resumes).

The fixtures let the AI resume-generation flows be exercised against real
profile data instead of toy strings. The PDF is the canonical artifact; the
text extraction feeds the same `resume_text` input the parse-resume Edge
Function and `match_resume_to_job` consume.

Live-AI tests are opt-in: set VISALANE_LIVE_AI=1 (requires at least one of
GEMINI_API_KEY / GROQ_API_KEY / OPENROUTER_API_KEY in the environment).
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "resumes"
RESUME_PDF = FIXTURES_DIR / "Alireza_Nezami_Resume.pdf"
RESUME_TXT = FIXTURES_DIR / "Alireza_Nezami_Resume.txt"

MOBILE_JOB = {
    "company": "Spotify",
    "title": "Senior Android Engineer",
    "url": "https://example.com/jobs/spotify-senior-android",
    "location": "Stockholm, Sweden (Remote, EU)",
    "description": (
        "We are looking for a senior Android engineer with strong Kotlin, "
        "Jetpack Compose and MVVM/Clean Architecture experience. Experience "
        "with Kotlin Multiplatform or Flutter is a strong plus. "
        "Visa sponsorship available for this role."
    ),
}

_VALID_MATCH_RESPONSE = {
    "ats_score": 82,
    "score_rationale": ("Strong Kotlin/Compose background; KMM and Flutter directly match the plus requirements."),
    "keywords_to_add": ["Kotlin Multiplatform", "Jetpack Compose", "MVVM"],
    "keywords_to_deemphasize": [],
    "section_suggestions": [
        {
            "section": "Experience — Devotel / Senior Android & Flutter Developer",
            "suggestion": "Lead with the Kotlin Platform Channel work to foreground native Android depth.",
        }
    ],
    "resume_editing_prompt": (
        "Reframe the Devotel bullets so Kotlin Platform Channel and KMM work appears "
        "before Flutter-only work. Do not change dates, employer names, or job titles."
    ),
}


def _resume_text() -> str:
    return RESUME_TXT.read_text(encoding="utf-8")


def _live_ai_enabled() -> bool:
    if os.getenv("VISALANE_LIVE_AI") != "1":
        return False
    return any(os.getenv(k) for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"))


class TestResumeFixtures(unittest.TestCase):
    """Sanity checks on the committed resume fixtures."""

    def test_pdf_fixture_exists(self):
        self.assertTrue(RESUME_PDF.is_file(), f"missing {RESUME_PDF}")
        self.assertEqual(RESUME_PDF.read_bytes()[:4], b"%PDF")

    def test_txt_fixture_exists(self):
        self.assertTrue(RESUME_TXT.is_file(), f"missing {RESUME_TXT}")

    def test_txt_meets_parse_contract(self):
        # parse-resume Edge Function requires resume_text >= 20 chars
        self.assertGreaterEqual(len(_resume_text().strip()), 20)

    def test_txt_contains_expected_content(self):
        text = _resume_text()
        for marker in ("Alireza Nezami", "Kotlin", "Flutter", "Android"):
            self.assertIn(marker, text)

    def test_txt_is_not_degenerate_extraction(self):
        text = _resume_text()
        self.assertGreater(len(text.split()), 300)
        # A real resume extraction should carry an experience section, not just headers
        self.assertGreater(text.count("\n"), 40)


class TestMatchWithRealResume(unittest.TestCase):
    """match_resume_to_job fed with the real resume text (mocked LLM)."""

    @patch("job_radar.resume.matcher._call_gemini_resume")
    def test_match_returns_structured_output(self, mock_call):
        from job_radar.resume.matcher import match_resume_to_job

        mock_call.return_value = json.dumps(_VALID_MATCH_RESPONSE)
        cache = MagicMock()
        cache.get.return_value = None

        result = match_resume_to_job(MOBILE_JOB, resume_text=_resume_text(), cache=cache)

        self.assertIsNotNone(result)
        self.assertEqual(result["ats_score"], 82)
        self.assertIn("Kotlin Multiplatform", result["keywords_to_add"])
        # The prompt sent to the AI must embed the real resume text
        sent_prompt = mock_call.call_args[0][0]
        self.assertIn("=== CANDIDATE RESUME ===", sent_prompt)
        self.assertIn("Alireza Nezami", sent_prompt)
        self.assertIn("Senior Android & Flutter Developer", sent_prompt)

    @patch("job_radar.resume.matcher._call_gemini_resume")
    def test_match_failure_returns_none(self, mock_call):
        from job_radar.resume.matcher import match_resume_to_job

        mock_call.side_effect = RuntimeError("quota exceeded")
        cache = MagicMock()
        cache.get.return_value = None

        result = match_resume_to_job(MOBILE_JOB, resume_text=_resume_text(), cache=cache)
        self.assertIsNone(result)


@unittest.skipUnless(_live_ai_enabled(), "set VISALANE_LIVE_AI=1 with an AI key to run")
class TestLiveAIResumeGeneration(unittest.TestCase):
    """End-to-end AI run against the real resume — costs API quota."""

    def test_live_match_produces_valid_score(self):
        from job_radar.resume.matcher import match_resume_to_job

        cache = MagicMock()
        cache.get.return_value = None

        result = match_resume_to_job(MOBILE_JOB, resume_text=_resume_text(), cache=cache)

        # Live providers must return a parseable contract response for this resume
        self.assertIsNotNone(result, "live AI call failed or returned unparseable output")
        self.assertIsInstance(result["ats_score"], int)
        self.assertTrue(0 <= result["ats_score"] <= 100)
        self.assertIsInstance(result.get("keywords_to_add"), list)

    def test_live_match_scores_mobile_job_high(self):
        """A senior Android/Flutter resume must clearly match a senior Android job."""
        from job_radar.resume.matcher import match_resume_to_job

        cache = MagicMock()
        cache.get.return_value = None

        result = match_resume_to_job(MOBILE_JOB, resume_text=_resume_text(), cache=cache)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["ats_score"], 60)


if __name__ == "__main__":
    unittest.main()

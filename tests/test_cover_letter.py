"""Unit tests for cover letter anti-AI-voice validation and pain point extraction."""
import pytest
from unittest.mock import MagicMock, patch

from job_radar.cover.generator import validate_cover_letter_voice, generate_research_grounded_cover_letter


def test_validate_cover_letter_detects_forbidden_phrases():
    cliche_letter = """
I am excited to apply for the Senior Engineer role at Google.
As a passionate developer, I believe my skills align with your mission.
I look forward to hearing from you soon.
"""
    violations = validate_cover_letter_voice(cliche_letter)
    assert len(violations) >= 2


def test_validate_cover_letter_accepts_clean_voice():
    clean_letter = """
Allegro's work scaling Kotlin multiplatform services across mobile systems caught my attention.
At my previous company, I architected a modular architecture serving 400K MAU with a 99.8% crash-free rate.
I would be glad to discuss how this background translates to your platform team.
"""
    violations = validate_cover_letter_voice(clean_letter)
    assert len(violations) == 0


def test_generate_cover_letter_word_cap():
    mock_result = MagicMock()
    mock_result.text = "word " * 300

    with patch("job_radar.cover.generator.complete", return_value=mock_result):
        letter = generate_research_grounded_cover_letter(
            resume_text="Resume text",
            job_description="JD text",
            company_name="Acme",
            job_title="SWE",
            max_words=100,
        )
        assert len(letter.split()) <= 105

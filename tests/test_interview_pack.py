"""Unit tests for Interview Pack generation and fallback behavior."""
import pytest
from job_radar.interview.generator import generate_interview_pack, InterviewPack


def test_interview_pack_generation_fallback():
    pack = generate_interview_pack(
        resume_text="Senior Engineer with 8 years building Flutter and Kotlin apps.",
        job_description="Looking for Mobile Software Engineer to scale checkout platform.",
        company_name="Allegro",
        job_title="Mobile Software Engineer",
    )
    assert isinstance(pack, InterviewPack)
    assert len(pack.core_pain_points) >= 1
    assert len(pack.star_stories) >= 1
    assert len(pack.questions_to_ask_interviewer) >= 2

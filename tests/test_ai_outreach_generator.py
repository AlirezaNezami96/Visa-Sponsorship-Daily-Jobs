"""Unit tests for persona-specific custom outreach message generation."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from job_radar.ai.outreach_generator import (
    OutreachGenerator,
    build_outreach_prompt,
    generate_outreach,
)
from job_radar.llm.router import LLMResult, ProviderAttempt


def test_build_outreach_prompt_for_recruiter_and_hiring_manager():
    contact = {"name": "Bob Smith", "title": "Technical Recruiter"}
    prompt_recruiter = build_outreach_prompt(
        profile_data={"full_name": "Carol"},
        job_data={"company": "Airbnb", "title": "Senior Engineer"},
        contact=contact,
        persona_type="recruiter",
    )
    assert "Bob Smith" in prompt_recruiter
    assert "RECRUITER" in prompt_recruiter

    prompt_hm = build_outreach_prompt(
        profile_data={"full_name": "Carol"},
        job_data={"company": "Airbnb", "title": "Senior Engineer"},
        contact={"name": "David", "title": "Director of Engineering"},
        persona_type="hiring_manager",
    )
    assert "HIRING_MANAGER" in prompt_hm


def test_outreach_generator_flow():
    mock_router = MagicMock()
    mock_messages = {
        "persona_type": "recruiter",
        "contact_name": "Bob Smith",
        "linkedin_connection": "Hi Bob, noticed you are recruiting for the Senior Engineer role at Airbnb. I have 6y Python exp and would love to connect!",
        "linkedin_inmail": "Hi Bob,\n\nI saw the Senior Engineer role at Airbnb and wanted to reach out. With 6 years building distributed Python services, I believe my background aligns well with your team's current focus.\n\nWould you be open to a brief chat this week?\n\nBest,\nCarol",
        "cold_email": {
            "subject": "Senior Engineer Opening - Carol Profile",
            "body": "Hi Bob,\n\nI hope your week is going well. I recently came across the Senior Engineer opening at Airbnb and wanted to introduce myself.\n\nOver the past 6 years, I have architected high-throughput backend services and scaled cloud infrastructure. My technical stack directly matches your requirements.\n\nWould you be open to a quick 15-minute conversation to explore fit?\n\nBest regards,\nCarol",
        },
        "followup_email": {
            "subject": "Re: Senior Engineer Opening - Carol Profile",
            "body": "Hi Bob,\n\nFollowing up on my note last week regarding the Senior Engineer opening. I'd still love to connect if you have 10 minutes.\n\nBest,\nCarol",
        },
    }

    mock_router.try_provider.return_value = ProviderAttempt(
        result=LLMResult(text=json.dumps(mock_messages), model_used="llama-3.3-70b", provider="groq"),
        reason="",
    )

    generator = OutreachGenerator(llm_router=mock_router)
    res = generator.generate_messages(
        profile_data={"full_name": "Carol"},
        job_data={"company": "Airbnb", "title": "Senior Engineer"},
        contact={"name": "Bob Smith", "title": "Technical Recruiter"},
        persona_type="recruiter",
    )

    assert res["success"] is True
    assert res["persona_type"] == "recruiter"
    assert len(res["messages"]["linkedin_connection"]) <= 300
    assert "Airbnb" in res["messages"]["cold_email"]["body"]

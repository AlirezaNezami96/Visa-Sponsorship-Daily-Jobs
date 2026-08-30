"""Unit tests for cover letter generation and validation."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from job_radar.ai.cover_letter_generator import (
    CoverLetterGenerator,
    build_cover_letter_prompt,
    generate_cover_letter,
)
from job_radar.llm.router import LLMResult, ProviderAttempt


def test_build_cover_letter_prompt():
    prompt = build_cover_letter_prompt(
        profile_data={"full_name": "Alice Smith"},
        job_data={"company": "Spotify", "title": "Staff Backend Engineer"},
    )
    assert "Spotify" in prompt
    assert "Staff Backend Engineer" in prompt
    assert "Alice Smith" in prompt
    assert "WORD COUNT: 250 to 400 words" in prompt


def test_cover_letter_generator_flow():
    mock_router = MagicMock()
    cl_text = (
        "Dear Hiring Team at Spotify,\n\n"
        "Having scaled distributed streaming backend architectures to handle millions of queries, I was immediately drawn to Spotify's audio infrastructure.\n\n"
        "Over the past 6 years, I have architected high-throughput Python and Go microservices, improving latency by 35% and automating CI/CD deployments across multi-region Kubernetes clusters. My expertise in real-time data streaming and distributed caching directly aligns with your requirements for the Staff Backend Engineer position.\n\n"
        "I am particularly impressed by Spotify's innovative approach to real-time recommendation engines and would welcome the opportunity to bring my hands-on backend leadership to your team.\n\n"
        "Thank you for your time and consideration. I look forward to the possibility of discussing how my technical background can support Spotify's engineering goals.\n\n"
        "Sincerely,\nAlice Smith"
    )

    mock_cl_data = {
        "salutation": "Dear Hiring Team at Spotify,",
        "opening_hook": "Having scaled distributed streaming backend architectures...",
        "body_paragraphs": ["Over the past 6 years...", "I am particularly impressed..."],
        "closing_call_to_action": "Thank you for your time...",
        "sign_off": "Sincerely,\nAlice Smith",
        "full_text": cl_text,
    }

    mock_router.try_provider.return_value = ProviderAttempt(
        result=LLMResult(text=json.dumps(mock_cl_data), model_used="llama-3.3-70b", provider="groq"),
        reason="",
    )

    generator = CoverLetterGenerator(llm_router=mock_router)
    res = generator.generate(
        profile_data={"full_name": "Alice Smith", "skills": ["Python", "Go"]},
        job_data={"company": "Spotify", "title": "Staff Backend Engineer", "skills": ["Python", "Go"]},
    )

    assert res["success"] is True
    assert res["company"] == "Spotify"
    assert res["word_count"] > 50
    assert "Spotify" in res["cover_letter"]["full_text"]

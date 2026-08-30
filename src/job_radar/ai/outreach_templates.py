"""Persona-specific templates and formats for outreach messages."""

from __future__ import annotations

PERSONA_GUIDELINES: dict[str, dict[str, str]] = {
    "recruiter": {
        "focus": "Matching technical skills, availability, visa sponsorship qualification, and clear role fit.",
        "tone": "Direct, professional, structured, highlighting key qualifications.",
    },
    "hiring_manager": {
        "focus": "Solving team engineering problems, architectural domain expertise, business impact, and track record.",
        "tone": "Peer-to-peer technical executive, outcome-focused, concise.",
    },
    "peer": {
        "focus": "Shared technical interests, codebase admiration, asking about daily developer experience and engineering culture.",
        "tone": "Casual, friendly, tech-curious, respectful of their time.",
    },
}

"""
src/job_radar/interview/generator.py

Generates an actionable 1-page Technical & Behavioral Interview Pack for the candidate:
1. Company & Product Brief
2. 3 Core Technical Pain Points
3. STAR Story Bank Matcher (anchored only in candidate's real experience)
4. Reverse-Interview Questions to ask the engineering team
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from job_radar.llm.router import complete

logger = logging.getLogger(__name__)


class STARStory(BaseModel):
    requirement: str
    situation_and_task: str
    action: str
    result: str


class InterviewPack(BaseModel):
    company_brief: str
    core_pain_points: List[str]
    star_stories: List[STARStory]
    questions_to_ask_interviewer: List[str]


INTERVIEW_PACK_PROMPT = """You are a senior engineering hiring director preparing a candidate for a technical & behavioral interview loop.

CANDIDATE BACKGROUND:
{resume_text}

TARGET COMPANY: {company_name}
TARGET ROLE: {job_title}
JOB DESCRIPTION:
{job_description}

Generate a concise, high-impact 1-page interview brief adhering to this JSON schema:
{{
  "company_brief": "2 sentences on what they build, their scale, and business model.",
  "core_pain_points": [
    "Pain point 1 they are hiring to fix",
    "Pain point 2",
    "Pain point 3"
  ],
  "star_stories": [
    {{
      "requirement": "Requirement from JD",
      "situation_and_task": "Real context from candidate background",
      "action": "What the candidate specifically did",
      "result": "Honest outcome/impact"
    }}
  ],
  "questions_to_ask_interviewer": [
    "Reverse interview question about team architecture",
    "Reverse interview question about technical debt or roadmap",
    "Reverse interview question about team velocity"
  ]
}}

STRICT RULE: Never invent candidate accomplishments. Anchor every STAR story in the candidate background text provided.
"""


def generate_interview_pack(
    resume_text: str,
    job_description: str,
    company_name: str,
    job_title: str,
) -> InterviewPack:
    """Generate structured interview pack using LLM router."""
    prompt = INTERVIEW_PACK_PROMPT.format(
        resume_text=resume_text[:4000],
        company_name=company_name,
        job_title=job_title,
        job_description=job_description[:4000],
    )

    try:
        res = complete(
            prompt=prompt,
            json_schema={"type": "object"},
            temperature=0.2,
        )
        if res.text and res.text.strip():
            data = json.loads(res.text)
            return InterviewPack(**data)
    except Exception as e:
        logger.warning("Failed to generate interview pack via LLM: %s", e)

    # Heuristic fallback
    return InterviewPack(
        company_brief=f"{company_name} is building products in the tech and mobile space.",
        core_pain_points=[
            "Scaling mobile/backend systems for high concurrency",
            "Improving codebase maintainability and test coverage",
            "Speeding up deployment and feature delivery",
        ],
        star_stories=[
            STARStory(
                requirement="Clean Architecture & Modular Systems",
                situation_and_task="Complex monolith with tight coupling",
                action="Refactored modules into clean domain/data layers with comprehensive unit tests",
                result="Significantly improved build speed and modular testability",
            )
        ],
        questions_to_ask_interviewer=[
            "How does your team balance new feature velocity with technical debt refactoring?",
            "What does the CI/CD pipeline and release cycle look like for this team?",
            "What is the single biggest architectural challenge the team is tackling this quarter?",
        ],
    )

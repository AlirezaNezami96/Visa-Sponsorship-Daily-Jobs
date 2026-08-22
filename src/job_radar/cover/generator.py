"""
src/job_radar/cover/generator.py

Research-grounded, human-toned cover letter generator with anti-AI-voice rules
and candidate word cap constraints.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from job_radar.llm.router import complete

logger = logging.getLogger(__name__)

COVER_PROMPT_PATH = Path("engine/prompts/cover_letter_v1.txt")

FORBIDDEN_PHRASES = [
    r"i am (excited|thrilled|delighted|pleased) to apply",
    r"i am passionate about",
    r"i believe my skills align with",
    r"i am eager to contribute",
    r"^as a \w+ \w+",
    r"i would love the opportunity to",
    r"i look forward to hearing from you",
    r"in conclusion",
]

_FORBIDDEN_REGEX = re.compile("|".join(FORBIDDEN_PHRASES), re.IGNORECASE)


def extract_job_pain_point(job_description: str, role_title: str) -> str:
    """Extracts the core technical pain point the company is hiring to solve."""
    prompt = f"""
ROLE: {role_title}
JOB DESCRIPTION:
{job_description[:3000]}

In 1 sentence: what specific engineering or business problem gets worse if this seat remains empty for 6 months?
"""
    res = complete(prompt=prompt, max_tokens=150)
    return res.text.strip() or "Scaling mission-critical services under heavy real-time load"


def generate_research_grounded_cover_letter(
    resume_text: str,
    job_description: str,
    company_name: str,
    job_title: str,
    tone: str = "professional",
    max_words: int = 180,
) -> str:
    """
    Generates a 3-paragraph human-toned cover letter strictly adhering to anti-AI-voice rules.
    """
    system_prompt = ""
    if COVER_PROMPT_PATH.exists():
        with open(COVER_PROMPT_PATH, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    else:
        system_prompt = "Write a direct, 3-paragraph technical cover letter without generic fluff or AI clichés."

    system_prompt = system_prompt.replace("{tone}", tone)

    pain_point = extract_job_pain_point(job_description, job_title)

    user_prompt = f"""
COMPANY: {company_name}
ROLE: {job_title}
IDENTIFIED CORE PAIN POINT: {pain_point}

===== CANDIDATE MASTER RESUME =====
{resume_text.strip()}

===== TARGET JOB DESCRIPTION =====
{job_description.strip()[:6000]}
"""

    res = complete(
        prompt=user_prompt,
        system_instruction=system_prompt,
        max_tokens=600,
        temperature=0.3,
    )

    letter = (res.text or "").strip()

    # Clean markdown fences if any
    if letter.startswith("```"):
        letter = letter.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    # Enforce word cap
    words = letter.split()
    if len(words) > max_words + 30:
        logger.info("Trimming cover letter to max %d words (was %d words)", max_words, len(words))
        letter = " ".join(words[:max_words])

    return letter


def validate_cover_letter_voice(letter_text: str) -> List[str]:
    """Checks for forbidden generic AI phrases in the letter."""
    violations = []
    for pattern in FORBIDDEN_PHRASES:
        if re.search(pattern, letter_text, re.IGNORECASE):
            violations.append(pattern)
    return violations

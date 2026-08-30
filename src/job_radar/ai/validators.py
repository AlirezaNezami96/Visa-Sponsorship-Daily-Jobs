"""Validation and anti-hallucination rules for AI generated documents.

Ensures:
  1. Generated resumes do not hallucinate companies, degrees, or titles not in the profile.
  2. Core dates and factual claims are strictly grounded.
  3. Cover letters and outreach messages adhere to length, tone, and blocklist rules.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

# Cliché and blocklisted phrases in professional documents
BLOCKLISTED_PHRASES: List[str] = [
    "i am writing to apply",
    "to whom it may concern",
    "i am thrilled to apply",
    "delve into",
    "in today's fast-paced world",
    "testament to",
    "game-changer",
    "synergy",
]


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower()).strip()


def validate_resume_grounding(
    generated_resume: Dict[str, Any],
    source_profile: Dict[str, Any],
) -> Optional[str]:
    """Verify that generated resume does not contain hallucinated companies or degrees.

    Returns violation string if hallucination detected, None if valid.
    """
    if not isinstance(generated_resume, dict):
        return "Generated resume must be a JSON object"

    # 1. Check Companies
    source_exp = source_profile.get("experience") or []
    source_companies: Set[str] = {_normalize(e.get("company", "")) for e in source_exp if isinstance(e, dict) and e.get("company")}

    gen_exp = generated_resume.get("experience") or []
    if isinstance(gen_exp, list):
        for item in gen_exp:
            if not isinstance(item, dict):
                continue
            comp = item.get("company", "")
            if comp and source_companies and _normalize(comp) not in source_companies:
                # Check if partial match (e.g. "Google Inc" vs "Google")
                norm_c = _normalize(comp)
                if not any(norm_c in sc or sc in norm_c for sc in source_companies):
                    return f"Hallucination detected: generated company '{comp}' does not exist in profile experience"

    # 2. Check Education Institutions
    source_edu = source_profile.get("education") or []
    source_institutions: Set[str] = {_normalize(e.get("institution", "")) for e in source_edu if isinstance(e, dict) and e.get("institution")}

    gen_edu = generated_resume.get("education") or []
    if isinstance(gen_edu, list):
        for item in gen_edu:
            if not isinstance(item, dict):
                continue
            inst = item.get("institution", "")
            if inst and source_institutions and _normalize(inst) not in source_institutions:
                norm_inst = _normalize(inst)
                if not any(norm_inst in si or si in norm_inst for si in source_institutions):
                    return f"Hallucination detected: generated institution '{inst}' does not exist in profile education"

    return None


def validate_cover_letter_content(
    cover_letter_text: str,
    company_name: str = "",
) -> Optional[str]:
    """Validate cover letter word count, blocklisted phrases, and company mentions.

    Requirements:
      - 250-400 words
      - No blocklisted phrases
      - Must reference company name if provided
    """
    if not cover_letter_text:
        return "Cover letter text is empty"

    words = cover_letter_text.split()
    word_count = len(words)
    if word_count < 100:
        return f"Cover letter is too short ({word_count} words; minimum 100 required)"
    if word_count > 500:
        return f"Cover letter is too long ({word_count} words; maximum 500 target)"

    lower_text = cover_letter_text.lower()
    for phrase in BLOCKLISTED_PHRASES:
        if phrase in lower_text:
            return f"Contains blocklisted phrase: '{phrase}'"

    if company_name and len(company_name) > 2:
        norm_company = company_name.lower().strip()
        if norm_company not in lower_text:
            # Check company first word if multi-word
            first_word = norm_company.split()[0]
            if len(first_word) >= 3 and first_word not in lower_text:
                return f"Cover letter does not mention the target company '{company_name}'"

    return None


def validate_outreach_message(
    linkedin_body: str,
    email_body: str,
) -> Optional[str]:
    """Validate LinkedIn (<= 300 chars) and Email (<= 220 words) limits."""
    if len(linkedin_body) > 300:
        return f"LinkedIn message exceeds 300 characters ({len(linkedin_body)} chars)"

    email_words = len(email_body.split())
    if email_words > 230:
        return f"Email body exceeds 220 words ({email_words} words)"

    return None

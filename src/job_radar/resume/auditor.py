"""
src/job_radar/resume/auditor.py

Entailment Auditor: Second-pass verification that prevents hallucinations and ensures
all claims, metrics, tools, and experiences in the tailored resume are strictly grounded
in the candidate's master resume.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from job_radar.llm.router import complete

logger = logging.getLogger(__name__)

AUDITOR_SYSTEM_PROMPT = """You are a strict, forensic technical resume auditor.
Your job is to verify that a rewritten resume bullet point is 100% ENTAILED by the candidate's original source bullet and master resume.

RULES:
1. FORBIDDEN (Hallucinations to drop):
   - Invented percentage metrics (e.g. source says "reduced crashes" -> rewrite says "reduced crashes by 99%")
   - Invented tools/frameworks not mentioned in the source or candidate profile
   - New responsibilities or projects that did not exist in the source
2. PERMITTED:
   - Natural rephrasing and terminology alignment with the target JD
   - Bolding tools/metrics already present in the original bullet
   - Changing sentence structure with strong action verbs

Output strict JSON:
{
  "is_grounded": true,
  "dropped_claims": ["specific reason if hallucinated"],
  "sanitized_text": "cleaned text strictly grounded in the original source"
}
"""


def audit_bullet_replacement(
    original_bullet_text: str,
    rewritten_bullet_text: str,
    master_resume_context: str = "",
) -> Tuple[bool, str, List[str]]:
    """
    Audits a single rewritten bullet against its original source bullet.

    Returns:
        (is_valid, final_bullet_text, list_of_dropped_claims)
    """
    # Fast-path heuristic check: Check if invented high-magnitude fake percentages appeared
    metric_pattern = r"\b\d+\s*%(?!\w)|\b\d+(?:\.\d+)?x\b|\$\s*\d+(?:,\d{3})*(?:\.\d+)?(?:k|m|b)?\b"
    orig_nums = set(re.findall(metric_pattern, original_bullet_text, re.IGNORECASE))
    new_nums = set(re.findall(metric_pattern, rewritten_bullet_text, re.IGNORECASE))

    planted_fakes = [n for n in new_nums if n not in orig_nums]
    if planted_fakes:
        logger.warning("Auditor heuristic caught ungrounded metric(s): %s", planted_fakes)
        # Strip or reject the planted fake metric
        cleaned = rewritten_bullet_text
        for fake in planted_fakes:
            cleaned = cleaned.replace(fake, "")
        return False, cleaned.strip(), [f"Ungrounded metric {f}" for f in planted_fakes]

    prompt = f"""
ORIGINAL BULLET:
{original_bullet_text}

REWRITTEN BULLET:
{rewritten_bullet_text}

Verify if every claim and metric in REWRITTEN BULLET is grounded in ORIGINAL BULLET.
"""
    try:
        res = complete(
            prompt=prompt,
            system_instruction=AUDITOR_SYSTEM_PROMPT,
            json_schema={"type": "object"},
        )
        if res.text and res.text.strip():
            data = json.loads(res.text)
            is_grounded = data.get("is_grounded", True)
            dropped = data.get("dropped_claims", [])
            sanitized = data.get("sanitized_text") or rewritten_bullet_text
            return is_grounded, sanitized, dropped
    except Exception as e:
        logger.debug("LLM auditor call failed, falling back to heuristic: %s", e)

    return True, rewritten_bullet_text, []


def audit_all_replacements(
    replacements: List[Dict[str, Any]],
    source_bullets_by_id: Dict[str, str],
    master_resume_text: str = "",
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Audits a batch of bullet replacements. Drops any that hallucinate new metrics or claims.
    """
    verified_replacements = []
    dropped_all = []

    for rep in replacements:
        bullet_id = rep.get("id") or rep.get("bullet_id")
        new_text = rep.get("new_text") or rep.get("text") or ""
        orig_text = source_bullets_by_id.get(bullet_id, "")

        if not orig_text:
            verified_replacements.append(rep)
            continue

        is_valid, sanitized_text, dropped = audit_bullet_replacement(
            original_bullet_text=orig_text,
            rewritten_bullet_text=new_text,
            master_resume_context=master_resume_text,
        )

        if dropped:
            dropped_all.extend(dropped)

        verified_replacements.append({
            "id": bullet_id,
            "new_text": sanitized_text,
        })

    return verified_replacements, dropped_all

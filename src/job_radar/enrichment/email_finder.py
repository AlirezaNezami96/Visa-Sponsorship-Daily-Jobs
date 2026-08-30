"""Email finder and extractor for job postings and hiring contacts.

Extracts explicit emails from job descriptions and links domain patterns.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from .pattern_matcher import generate_email_patterns

_EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

_GENERIC_LOCAL_PARTS = {"careers", "jobs", "talent", "recruiting", "hr", "info", "contact", "support", "hiring", "apply"}


def extract_emails_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract email addresses from job posting text with confidence scoring."""
    if not text:
        return []

    found = _EMAIL_REGEX.findall(text)
    seen: Set[str] = set()
    results: List[Dict[str, Any]] = []

    for email in found:
        cleaned = email.lower().strip().rstrip(".")
        if cleaned in seen:
            continue
        # Avoid common image or schema false positives
        if any(cleaned.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"]):
            continue

        seen.add(cleaned)
        local_part = cleaned.split("@")[0]

        is_generic = local_part in _GENERIC_LOCAL_PARTS
        status = "generic" if is_generic else "verified"
        confidence = 80 if is_generic else 90

        results.append({
            "email": cleaned,
            "email_status": status,
            "confidence": confidence,
            "source_type": "job_posting_text",
        })

    return results


def find_emails_for_contact(
    first_name: str,
    last_name: str,
    company_domain: str,
    job_description_text: str = "",
) -> List[Dict[str, Any]]:
    """Find all potential email addresses for a specific contact and company."""
    explicit_emails = extract_emails_from_text(job_description_text)
    pattern_emails = generate_email_patterns(first_name, last_name, company_domain)

    return explicit_emails + pattern_emails

"""Hallucination cross-check validators (Python mirror of _shared/validators.ts).

Kept in sync with the TS runtime so both reject identical hallucinations.
Every validator returns None (pass) or a violation-list string (reject).

Rules (GAP 3.1):
- Tailored resume: employers, job titles, and years must exist in the input
  profile snapshot; education institutions must be real. Never a new employer,
  never a new degree.
- Cover letter: 250-400 words, blocklisted openers rejected, must reference
  >=1 company-specific token AND >=1 user metric/fact.
- Outreach: LinkedIn <= 300 chars (hard), email <= 220 words, tone kept.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("utf-8")
    return re.sub(r"[^a-z0-9]+", " ", text).lower().strip()


COVER_LETTER_BLOCKLIST = [
    "i am writing to apply",
    "i would like to express my interest",
    "to whom it may concern",
    "i hope this finds you well",
    "delve",
    "thrilled to apply",
]

LINKEDIN_HARD_LIMIT = 300
EMAIL_WORD_LIMIT = 220
COVER_LETTER_MIN_WORDS = 250
COVER_LETTER_MAX_WORDS = 400

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_METRIC_RE = re.compile(r"\d+\s*%|\d+\s*\+|\$\s?\d+|\d+\s*(?:k|m)\b|\b\d{2,}\b")
_PRESENT_MARKERS = {"", "present", "current", "now", "today"}

_SECTION_KEYS = ("summary", "skills", "experience", "education", "links")


def resolve_sections(parsed: dict[str, Any]) -> dict[str, Any]:
    """Normalize AI output shape: accept {"sections": {...}} or flat sections.

    Models vary between the wrapped and the flat layout; validators and the
    PDF builder must treat both identically (a flat payload must never slip
    past grounding checks).
    """
    if not isinstance(parsed, dict):
        return {}
    inner = parsed.get("sections")
    if isinstance(inner, dict) and any(inner.get(k) for k in _SECTION_KEYS):
        return inner
    if any(parsed.get(k) for k in _SECTION_KEYS):
        return {k: parsed[k] for k in _SECTION_KEYS if parsed.get(k)}
    return {}


def _years(value: Any) -> list[str]:
    return _YEAR_RE.findall(str(value or ""))


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w])


def _present_in(needle: Any, haystack: list[Any]) -> bool:
    n = _norm(needle)
    if not n:
        return False
    for item in haystack:
        h = _norm(item)
        if h and (h == n or h in n or n in h):
            return True
    return False


def _is_present_marker(value: Any) -> bool:
    return _norm(value) in _PRESENT_MARKERS


def validate_tailored_resume(parsed: dict[str, Any], snapshot: dict[str, Any] | None) -> str | None:
    """Reject invented employers/titles/dates/degrees vs the profile snapshot."""
    violations: list[str] = []
    sections = resolve_sections(parsed)
    experience = sections.get("experience") or []
    snap_experience = (snapshot or {}).get("experience") or []
    snap_education = (snapshot or {}).get("education") or []

    if isinstance(experience, list) and experience and snap_experience:
        snap_companies = [e.get("company") for e in snap_experience if isinstance(e, dict)]
        snap_titles = [e.get("title") for e in snap_experience if isinstance(e, dict)]
        known_years = set()
        for e in snap_experience:
            if isinstance(e, dict):
                known_years.update(_years(e.get("start")))
                known_years.update(_years(e.get("end")))
        for e in snap_education:
            if isinstance(e, dict):
                known_years.update(_years(e.get("year")))

        for entry in experience:
            if not isinstance(entry, dict):
                continue
            company = str(entry.get("company") or "")
            title = str(entry.get("title") or "")
            if company and not _present_in(company, snap_companies):
                violations.append(f'employer "{company}" does not exist in the candidate profile')
            if title and not _present_in(title, snap_titles):
                violations.append(f'job title "{title}" does not exist in the candidate profile')
            for field in ("start", "end"):
                raw = entry.get(field)
                if _is_present_marker(raw):
                    continue
                for year in _years(raw):
                    if year not in known_years:
                        violations.append(f'year "{year}" in {field} not present in profile dates')

    education = sections.get("education") or []
    if isinstance(education, list) and education and snap_education:
        snap_institutions = [e.get("institution") for e in snap_education if isinstance(e, dict)]
        for entry in education:
            if not isinstance(entry, dict):
                continue
            institution = str(entry.get("institution") or "")
            if institution and not _present_in(institution, snap_institutions):
                violations.append(f'education institution "{institution}" was invented')

    if violations:
        return "Hallucination check failed: " + "; ".join(violations)
    return None


def validate_cover_letter(
    parsed: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
    company: str = "",
    company_hook_context: str = "",
) -> str | None:
    """Word count, blocklist, company reference and user-fact grounding."""
    if not isinstance(parsed, dict):
        return "output is not a dictionary"
    markdown = str(parsed.get("cover_letter_markdown") or "")
    if not markdown.strip():
        return "missing cover_letter_markdown"
    violations: list[str] = []

    words = _word_count(markdown)
    if words < COVER_LETTER_MIN_WORDS or words > COVER_LETTER_MAX_WORDS:
        violations.append(f"word count {words} outside {COVER_LETTER_MIN_WORDS}-{COVER_LETTER_MAX_WORDS}")

    lower = markdown.lower()
    for phrase in COVER_LETTER_BLOCKLIST:
        if phrase in lower:
            violations.append(f'blocklisted opener/phrase "{phrase}"')

    lowered = _norm(markdown)
    tokens = [t for t in [company, *company_hook_context.split()] if t and len(_norm(t)) >= 4]
    if tokens and not any(_norm(t) in lowered for t in tokens):
        violations.append("letter never references the company (company-specific token missing)")

    user_skills = [_norm(s) for s in ((snapshot or {}).get("skills") or []) if _norm(s)]
    has_metric = bool(_METRIC_RE.search(markdown))
    has_user_fact = any(s in lowered for s in user_skills)
    if not has_metric and not has_user_fact:
        violations.append("letter contains no user metric or profile fact")

    if violations:
        return "Cover letter check failed: " + "; ".join(violations)
    return None


def validate_outreach(parsed: dict[str, Any] | None, expected_tone: str = "natural") -> str | None:
    """LinkedIn hard cap, email word cap, tone consistency."""
    if not isinstance(parsed, dict):
        return "output is not a dictionary"
    violations: list[str] = []
    if not isinstance(parsed.get("email"), dict):
        violations.append("missing email object")
    if not isinstance(parsed.get("linkedin"), dict):
        violations.append("missing linkedin object")
    email = parsed.get("email") or {}
    linkedin = parsed.get("linkedin") or {}

    email_body = str(email.get("body") or "")
    if not email_body.strip():
        violations.append("missing email.body")
    elif _word_count(email_body) > EMAIL_WORD_LIMIT:
        violations.append(f"email body {_word_count(email_body)} words exceeds {EMAIL_WORD_LIMIT}")

    linkedin_body = str(linkedin.get("body") or "")
    if not linkedin_body.strip():
        violations.append("missing linkedin.body")
    elif len(linkedin_body) > LINKEDIN_HARD_LIMIT:
        violations.append(f"linkedin body {len(linkedin_body)} chars exceeds hard cap {LINKEDIN_HARD_LIMIT}")

    for name, tone in (("email", email.get("tone")), ("linkedin", linkedin.get("tone"))):
        if tone and str(tone) != expected_tone:
            violations.append(f'{name} tone "{tone}" does not match requested "{expected_tone}"')

    if violations:
        return "Outreach check failed: " + "; ".join(violations)
    return None

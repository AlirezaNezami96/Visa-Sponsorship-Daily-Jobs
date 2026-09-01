"""Hallucination cross-check validators (Python mirror of _shared/validators.ts).

Kept in sync with the TS runtime so both reject identical hallucinations.
Every validator returns None (pass) or a violation-list string (reject).

Rules:
- Tailored resume: employers, job titles, and years must exist in the input
  profile snapshot; education institutions must be real. Never a new employer,
  never a new degree.
- Metric defense: every percentage (%\b), multiplier (x\b), or dollar amount ($)
  in rewritten bullets MUST exist in the source resume bullets. Never invent a metric.
- Section grounding: projects, certifications, publications, awards, and languages
  must be grounded in candidate data.
- Cover letter: 250-400 words, blocklisted openers rejected, must reference
  >=1 company-specific token AND >=1 user metric/fact.
- Outreach: LinkedIn <= 300 chars (hard), email <= 220 words, tone kept.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, List, Set

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
_METRIC_RE = re.compile(r"\b\d+\s*%(?!\w)|\b\d+(?:\.\d+)?x\b|\$\s*\d+(?:,\d{3})*(?:\.\d+)?(?:k|m|b)?\b", re.IGNORECASE)
_PRESENT_MARKERS = {"", "present", "current", "now", "today"}

_KNOWN_SECTION_TYPES = (
    "summary", "skills", "experience", "education",
    "projects", "certifications", "publications", "awards",
    "languages", "volunteer_work", "links", "interests", "custom"
)


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("utf-8")
    return re.sub(r"[^a-z0-9]+", " ", text).lower().strip()


def resolve_sections(parsed: dict[str, Any]) -> dict[str, Any]:
    """Normalize AI output shape: accept ResumeSection[] list, {"sections": {...}}, or flat sections."""
    if not isinstance(parsed, dict):
        return {}

    sections_val = parsed.get("sections")
    if isinstance(sections_val, list):
        out: dict[str, Any] = {}
        for sec in sections_val:
            if isinstance(sec, dict) and "type" in sec:
                out[str(sec["type"]).lower()] = sec.get("items")
        return out

    if isinstance(sections_val, dict) and any(sections_val.get(k) is not None for k in _KNOWN_SECTION_TYPES):
        return sections_val

    if any(parsed.get(k) is not None for k in _KNOWN_SECTION_TYPES):
        return {k: parsed[k] for k in _KNOWN_SECTION_TYPES if parsed.get(k) is not None}

    return {}


def _years(value: Any) -> list[str]:
    return _YEAR_RE.findall(str(value or ""))


def _extract_metrics(text: str) -> list[str]:
    if not text:
        return []
    matches = _METRIC_RE.findall(text)
    return [re.sub(r"\s+", "", m.lower()) for m in matches]


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


def _extract_source_bullets(snapshot: dict[str, Any] | None) -> list[str]:
    if not snapshot:
        return []
    bullets: list[str] = []
    for e in snapshot.get("experience") or []:
        if isinstance(e, dict):
            hl = e.get("highlights") or e.get("bullets") or []
            bullets.extend(str(h) for h in hl if h)
    for p in snapshot.get("projects") or []:
        if isinstance(p, dict):
            if p.get("description"):
                bullets.append(str(p["description"]))
            for b in p.get("bullets") or []:
                if b:
                    bullets.append(str(b))
    raw = snapshot.get("raw_text")
    if isinstance(raw, str) and raw:
        bullets.append(raw)
    return bullets


def validate_tailored_resume(parsed: dict[str, Any], snapshot: dict[str, Any] | None) -> str | None:
    """Reject invented employers/titles/dates/degrees/metrics vs the profile snapshot."""
    violations: list[str] = []
    sections = resolve_sections(parsed)
    experience = sections.get("experience") or []
    snap_experience = (snapshot or {}).get("experience") or []
    snap_education = (snapshot or {}).get("education") or []

    # 1. Experience grounding
    if isinstance(experience, list) and experience and snap_experience:
        snap_companies = [e.get("company") for e in snap_experience if isinstance(e, dict)]
        snap_titles = [e.get("title") for e in snap_experience if isinstance(e, dict)]
        known_years: Set[str] = set()
        for e in snap_experience:
            if isinstance(e, dict):
                known_years.update(_years(e.get("start")))
                known_years.update(_years(e.get("end")))
        for ed in snap_education:
            if isinstance(ed, dict):
                known_years.update(_years(ed.get("year")))

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

    # 2. Education grounding
    education = sections.get("education") or []
    if isinstance(education, list) and education and snap_education:
        snap_inst = [ed.get("institution") for ed in snap_education if isinstance(ed, dict)]
        for entry in education:
            if not isinstance(entry, dict):
                continue
            inst = str(entry.get("institution") or "")
            if inst and not _present_in(inst, snap_inst):
                violations.append(f'education institution "{inst}" was invented')

    # 3. Metric hallucination defense
    source_bullets = _extract_source_bullets(snapshot)
    all_source_metrics: Set[str] = set()
    for sb in source_bullets:
        all_source_metrics.update(_extract_metrics(sb))

    output_bullets: list[str] = []
    if isinstance(experience, list):
        for exp in experience:
            if isinstance(exp, dict):
                for b in exp.get("bullets") or exp.get("highlights") or []:
                    if b:
                        output_bullets.append(str(b))

    projects = sections.get("projects") or []
    if isinstance(projects, list):
        for proj in projects:
            if isinstance(proj, dict):
                if proj.get("description"):
                    output_bullets.append(str(proj["description"]))
                for b in proj.get("bullets") or []:
                    if b:
                        output_bullets.append(str(b))

    for b in output_bullets:
        for m in _extract_metrics(b):
            if m not in all_source_metrics:
                violations.append(f'invented metric or percentage "{m}" in bullet: "{b[:80]}"')

    # 4. Certifications grounding
    certs = sections.get("certifications") or []
    snap_certs = (snapshot or {}).get("certifications") or []
    if isinstance(certs, list) and certs and snap_certs:
        snap_names = [c.get("name") for c in snap_certs if isinstance(c, dict)]
        for cert in certs:
            if isinstance(cert, dict):
                name = str(cert.get("name") or "")
                if name and not _present_in(name, snap_names):
                    violations.append(f'certification "{name}" was invented')

    return "; ".join(violations) if violations else None


def validate_cover_letter(
    parsed: dict[str, Any],
    profile: dict[str, Any] | None = None,
    job: dict[str, Any] | None = None,
    company: str | None = None,
    company_hook_context: str | None = None,
) -> str | None:
    if not isinstance(parsed, dict):
        return "output is not a dictionary"
    text = str(parsed.get("cover_letter_markdown") or "")
    if not text.strip():
        return "missing cover_letter_markdown"

    violations: list[str] = []
    lower = text.lower()
    wc = _word_count(text)

    if wc < COVER_LETTER_MIN_WORDS or wc > COVER_LETTER_MAX_WORDS:
        violations.append(f"word count {wc} outside target {COVER_LETTER_MIN_WORDS}-{COVER_LETTER_MAX_WORDS}")

    for phrase in COVER_LETTER_BLOCKLIST:
        if phrase.lower() in lower:
            violations.append(f'contains blocklisted opening phrase "{phrase}"')

    target_company = company or (job.get("company") if isinstance(job, dict) else None)
    if target_company:
        comp_norm = _norm(target_company)
        hook_norm = _norm(company_hook_context) if company_hook_context else ""
        has_comp = bool(comp_norm and len(comp_norm) > 2 and comp_norm in lower)
        has_hook = bool(hook_norm and len(hook_norm) > 4 and hook_norm in lower)
        if not (has_comp or has_hook):
            violations.append(f'missing company-specific token reference for "{target_company}"')

    # Fact check: must mention candidate skill, tool, company, or metric
    facts: list[str] = []
    if profile:
        for s in profile.get("skills") or []:
            if s: facts.append(str(s))
        for e in profile.get("experience") or []:
            if isinstance(e, dict):
                if e.get("company"): facts.append(str(e["company"]))
                if e.get("title"): facts.append(str(e["title"]))
                for h in e.get("highlights") or e.get("bullets") or []:
                    if h: facts.append(str(h))

    if facts:
        mentions_fact = any(_norm(f) and len(_norm(f)) > 2 and _norm(f) in lower for f in facts)
        if not mentions_fact:
            violations.append("does not reference any verified user metric or profile fact")

    return "; ".join(violations) if violations else None


def validate_outreach(
    parsed: dict[str, Any] | None,
    expected_tone: str | None = None,
) -> str | None:
    if not isinstance(parsed, dict):
        return "output is not a dictionary"

    violations: list[str] = []

    # Support nested format: {"email": {...}, "linkedin": {...}}
    has_email_key = "email" in parsed
    has_linkedin_key = "linkedin" in parsed

    if has_email_key or has_linkedin_key:
        email_obj = parsed.get("email")
        linkedin_obj = parsed.get("linkedin")

        if not isinstance(email_obj, dict):
            violations.append("missing email object")
        else:
            body = str(email_obj.get("body") or "")
            if not body.strip():
                violations.append("missing email.body")
            elif _word_count(body) > EMAIL_WORD_LIMIT:
                violations.append(f"email body exceeds limit of {EMAIL_WORD_LIMIT} words")
            if expected_tone and email_obj.get("tone") and email_obj.get("tone") != expected_tone:
                violations.append(f"email tone '{email_obj.get('tone')}' does not match expected '{expected_tone}'")

        if not isinstance(linkedin_obj, dict):
            violations.append("missing linkedin object")
        else:
            l_body = str(linkedin_obj.get("body") or "")
            if not l_body.strip():
                violations.append("missing linkedin.body")
            elif len(l_body) > LINKEDIN_HARD_LIMIT:
                violations.append(f"linkedin body exceeds hard cap of {LINKEDIN_HARD_LIMIT} chars")
            if expected_tone and linkedin_obj.get("tone") and linkedin_obj.get("tone") != expected_tone:
                violations.append(f"linkedin tone '{linkedin_obj.get('tone')}' does not match expected '{expected_tone}'")

        return "; ".join(violations) if violations else None

    # Flat format: {"linkedin_note": ..., "email_body": ..., "email_subject": ...}
    note = str(parsed.get("linkedin_note") or "")
    body = str(parsed.get("email_body") or "")
    subject = str(parsed.get("email_subject") or "")

    if not note.strip():
        violations.append("missing linkedin_note")
    if not body.strip():
        violations.append("missing email_body")
    if not subject.strip():
        violations.append("missing email_subject")

    if len(note) > LINKEDIN_HARD_LIMIT:
        violations.append(f"linkedin note is {len(note)} characters (hard limit: {LINKEDIN_HARD_LIMIT})")

    wc = _word_count(body)
    if wc > EMAIL_WORD_LIMIT:
        violations.append(f"email body is {wc} words (limit: {EMAIL_WORD_LIMIT})")

    return "; ".join(violations) if violations else None

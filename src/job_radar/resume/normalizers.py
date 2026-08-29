"""Resume data normalizers.

Normalizes extracted and AI-parsed resume fields:
  - Dates: convert various formats to YYYY-MM or YYYY
  - Phone numbers: normalize to E.164-like format
  - Email addresses: lowercase + validate
  - URLs: ensure https scheme
  - Skills: deduplicate, strip noise, normalize case
  - Names: title-case, strip extra whitespace
"""
from __future__ import annotations

import re
from typing import Any

# Date patterns
_MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    "january": "01", "february": "02", "march": "03", "april": "04",
    "june": "06", "july": "07", "august": "08", "september": "09",
    "october": "10", "november": "11", "december": "12",
}
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_MONTH_RE = re.compile(r"\b(" + "|".join(_MONTH_MAP.keys()) + r")\b", re.IGNORECASE)

# Email regex (RFC-simplified)
_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")

# Phone: international + local formats
_PHONE_DIGITS_RE = re.compile(r"[\d\s\-\.\+\(\)]+")
_MIN_PHONE_DIGITS = 7
_MAX_PHONE_DIGITS = 15

# URL
_HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)


def normalize_date(value: Any) -> str | None:
    """Normalize a date string to 'YYYY-MM' or 'YYYY'.

    Returns None if the date cannot be parsed.
    Special values like 'Present', 'Current', '' are returned as-is (lowercase).
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Present / Current markers
    lower = s.lower()
    if lower in ("present", "current", "now", "today", "ongoing"):
        return "Present"

    # Try numeric MM/YYYY or YYYY/MM or YYYY-MM
    parts = re.split(r"[/\-\.]", s)
    if len(parts) == 2:
        a, b = parts[0].strip(), parts[1].strip()
        if len(a) == 4 and a.isdigit() and b.isdigit() and 1 <= int(b) <= 12:
            return f"{a}-{b.zfill(2)}"
        if len(b) == 4 and b.isdigit() and a.isdigit() and 1 <= int(a) <= 12:
            return f"{b}-{a.zfill(2)}"

    year_match = _YEAR_RE.search(s)
    month_match = _MONTH_RE.search(s)

    year = year_match.group(0) if year_match else None
    month = _MONTH_MAP.get(month_match.group(0).lower()) if month_match else None

    if year and month:
        return f"{year}-{month}"
    if year:
        return year

    return None


def normalize_email(value: Any) -> str | None:
    """Extract and normalize an email address."""
    if not value:
        return None
    s = str(value).strip().lower()
    match = _EMAIL_RE.search(s)
    return match.group(0) if match else None


def normalize_phone(value: Any) -> str | None:
    """Normalize a phone number by stripping non-digit chars (except leading +)."""
    if not value:
        return None
    s = str(value).strip()
    has_plus = s.startswith("+")
    digits_only = re.sub(r"\D", "", s)
    if len(digits_only) < _MIN_PHONE_DIGITS or len(digits_only) > _MAX_PHONE_DIGITS:
        return None
    return ("+" if has_plus else "") + digits_only


def normalize_url(value: Any) -> str | None:
    """Ensure a URL has an https:// scheme."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not _HTTP_RE.match(s):
        s = "https://" + s
    return s


def normalize_skills(skills: list[Any]) -> list[str]:
    """Deduplicate and clean a skills list.

    Rules:
      - Strip whitespace, remove empty strings
      - Deduplicate case-insensitively (keep first occurrence's casing)
      - Remove skills that are > 60 chars (likely a sentence, not a skill)
      - Remove skills that are < 2 chars
    """
    seen: set[str] = set()
    result: list[str] = []
    for raw in skills:
        skill = str(raw).strip()
        if not skill or len(skill) < 2 or len(skill) > 60:
            continue
        key = skill.lower()
        if key not in seen:
            seen.add(key)
            result.append(skill)
    return result


def normalize_name(value: Any) -> str | None:
    """Title-case a full name and strip extra whitespace."""
    if not value:
        return None
    name = " ".join(str(value).split())
    return name.title() if name else None


def normalize_parsed_data(data: dict[str, Any]) -> dict[str, Any]:
    """Apply all normalizers to an AI-parsed resume dict in-place."""
    out: dict[str, Any] = dict(data)

    # Top-level fields
    out["full_name"] = normalize_name(data.get("full_name"))
    out["email"] = normalize_email(data.get("email"))
    out["phone"] = normalize_phone(data.get("phone"))

    # Top-level URLs
    for url_field in ("linkedin_url", "github_url", "website_url", "portfolio_url"):
        if data.get(url_field):
            out[url_field] = normalize_url(data.get(url_field))

    # Skills
    if isinstance(data.get("skills"), list):
        out["skills"] = normalize_skills(data["skills"])

    # Links dict
    links = data.get("links") or {}
    if isinstance(links, dict):
        out["links"] = {k: normalize_url(v) for k, v in links.items() if v}

    # Projects
    projects = data.get("projects") or []
    if isinstance(projects, list):
        normalized_proj = []
        for p in projects:
            if not isinstance(p, dict):
                continue
            proj = dict(p)
            if isinstance(proj.get("technologies"), list):
                proj["technologies"] = normalize_skills(proj["technologies"])
            normalized_proj.append(proj)
        out["projects"] = normalized_proj

    # Experience dates
    experience = data.get("experience") or []
    if isinstance(experience, list):
        normalized_exp = []
        for entry in experience:
            if not isinstance(entry, dict):
                continue
            e = dict(entry)
            e["start"] = normalize_date(e.get("start"))
            e["end"] = normalize_date(e.get("end"))
            normalized_exp.append(e)
        out["experience"] = normalized_exp

    # Education dates
    education = data.get("education") or []
    if isinstance(education, list):
        normalized_edu = []
        for entry in education:
            if not isinstance(entry, dict):
                continue
            e = dict(entry)
            e["year"] = normalize_date(e.get("year") or e.get("graduation_year"))
            normalized_edu.append(e)
        out["education"] = normalized_edu

    return out

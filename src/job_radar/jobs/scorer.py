"""Job scorer — pure scoring functions (no I/O).

All functions are deterministic, stateless, and fully unit-testable.
The scorer produces a composite match score (0–100) used by the
job matcher and the search-jobs edge function.

Scoring breakdown (totals to 100):
  - Title relevance:       20 points
  - Skills overlap:        50 points
  - Experience level:      10 points
  - Visa sponsorship:      10 points
  - Location preference:   10 points
"""
from __future__ import annotations

import re
from typing import Any

# Normalization helper
_NORM_RE = re.compile(r"[^a-z0-9\s]")


def _normalize(text: str) -> str:
    return _NORM_RE.sub("", text.lower()).strip()


def _norm_set(items: list[str]) -> set[str]:
    return {_normalize(s) for s in items if s}


# ── Component scorers ──────────────────────────────────────────────────────────

def score_title_relevance(
    user_titles: list[str],
    job_title: str,
    max_points: int = 20,
) -> int:
    """Score based on how well the job title matches user's target titles."""
    if not user_titles or not job_title:
        return max_points // 2  # neutral when unknown

    job_norm = _normalize(job_title)
    job_words = set(job_norm.split())

    best = 0
    for title in user_titles:
        tnorm = _normalize(title)
        t_words = set(tnorm.split())
        if tnorm == job_norm:
            return max_points  # exact match
        if tnorm in job_norm or job_norm in tnorm:
            best = max(best, max_points - 2)
        elif t_words & job_words:
            overlap = len(t_words & job_words) / max(len(t_words), len(job_words))
            best = max(best, int(overlap * (max_points - 4)))

    return min(best, max_points)


def score_skills_overlap(
    user_skills: list[str],
    job_skills: list[str],
    max_points: int = 50,
) -> int:
    """Score based on skills overlap between user profile and job requirements.

    Uses a weighted Jaccard: skills the user has that the job requires count
    more than skills the job requires that the user lacks.
    """
    if not job_skills:
        return max_points // 2  # no job skills listed → neutral

    user_set = _norm_set(user_skills)
    job_set = _norm_set(job_skills)

    if not user_set:
        return 0  # user has no skills listed

    # How many of the job's required skills does the user have?
    matched = user_set & job_set
    if not matched:
        return 0

    coverage = len(matched) / len(job_set)  # 0.0 – 1.0

    # Bonus: user has extra relevant skills (caps at 10% bonus)
    extra_ratio = min(len(user_set - job_set) / max(len(user_set), 1), 0.1)

    raw = coverage + extra_ratio
    return min(int(raw * max_points), max_points)


def score_experience_level(
    user_years: int | None,
    job_min_years: int | None,
    job_max_years: int | None,
    max_points: int = 10,
) -> int:
    """Score experience level match.

    Returns max_points if user's experience is within the job's range,
    partial credit for being slightly outside, 0 for large mismatches.
    """
    if user_years is None or (job_min_years is None and job_max_years is None):
        return max_points // 2  # neutral when unknown

    min_req = job_min_years or 0
    max_req = job_max_years or 20

    if min_req <= user_years <= max_req:
        return max_points

    # Under-qualified
    if user_years < min_req:
        gap = min_req - user_years
        if gap <= 1:
            return max_points - 2
        if gap <= 2:
            return max_points // 2
        return 0

    # Over-qualified (usually fine, minor penalty)
    gap = user_years - max_req
    if gap <= 2:
        return max_points - 1
    return max(max_points - gap, 0)


def score_visa_sponsorship(
    job_verified: bool | None,
    job_confidence: int | None,
    max_points: int = 10,
) -> int:
    """Score visa sponsorship availability."""
    if job_verified:
        return max_points
    if job_confidence is not None and job_confidence >= 70:
        return max_points - 2
    if job_confidence is not None and job_confidence >= 50:
        return max_points // 2
    return 0


def score_location_preference(
    user_preferred_countries: list[str] | None,
    user_preferred_work_modes: list[str] | None,
    job_country: str | None,
    job_work_mode: str | None,
    max_points: int = 10,
) -> int:
    """Score location and work mode match."""
    pts = 0
    half = max_points // 2

    # Work mode check (worth half the points)
    if user_preferred_work_modes and job_work_mode:
        if job_work_mode.lower() in [m.lower() for m in user_preferred_work_modes]:
            pts += half
        elif "remote" in [m.lower() for m in user_preferred_work_modes] and "hybrid" == job_work_mode.lower():
            pts += half // 2
    else:
        pts += half  # neutral

    # Country check (worth other half)
    if user_preferred_countries and job_country:
        if job_country.upper() in [c.upper() for c in user_preferred_countries]:
            pts += half
    else:
        pts += half  # neutral

    return min(pts, max_points)


def compute_match_score(
    user_profile: dict[str, Any],
    job: dict[str, Any],
) -> int:
    """Compute composite match score (0–100) for a (user, job) pair.

    Args:
        user_profile: Profile dict with skills, job_titles, experience_years,
                      preferred_countries, preferred_work_modes.
        job: Job dict with skills, title, work_mode, country,
             visa_sponsorship_verified, visa_sponsorship_confidence,
             min_experience_years, max_experience_years.

    Returns:
        Integer score 0–100.
    """
    user_skills: list[str] = user_profile.get("skills_cache") or user_profile.get("skills") or []
    if not isinstance(user_skills, list):
        user_skills = list(user_skills)

    user_titles: list[str] = user_profile.get("job_titles") or []
    user_years: int | None = user_profile.get("experience_years")
    user_countries: list[str] | None = user_profile.get("preferred_countries")
    user_modes: list[str] | None = user_profile.get("preferred_work_modes")

    job_skills: list[str] = job.get("skills") or []
    job_title: str = str(job.get("title") or "")
    job_country: str | None = job.get("country") or job.get("country_code")
    job_mode: str | None = job.get("work_mode")
    job_visa: bool | None = job.get("visa_sponsorship_verified")
    job_confidence: int | None = job.get("visa_sponsorship_confidence")
    job_min_yrs: int | None = job.get("min_experience_years")
    job_max_yrs: int | None = job.get("max_experience_years")

    title_score = score_title_relevance(user_titles, job_title, max_points=20)
    skills_score = score_skills_overlap(user_skills, job_skills, max_points=50)
    exp_score = score_experience_level(user_years, job_min_yrs, job_max_yrs, max_points=10)
    visa_score = score_visa_sponsorship(job_visa, job_confidence, max_points=10)
    loc_score = score_location_preference(user_countries, user_modes, job_country, job_mode, max_points=10)

    return min(100, title_score + skills_score + exp_score + visa_score + loc_score)

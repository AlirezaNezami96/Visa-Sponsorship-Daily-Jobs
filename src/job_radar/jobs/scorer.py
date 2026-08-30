"""Job scorer — pure scoring functions (no I/O).

All functions are deterministic, stateless, and fully unit-testable.
The scorer produces a composite match score (0–100) used by the
job matcher and the search-jobs edge function.

Scoring breakdown (spec §3.2):
  Base components (100):
    - Title relevance:       40 points
    - Skills overlap:        50 points
    - Experience level:      10 points
  Bonuses (capped at 100 total):
    - Location preference:   +10 points
    - Visa sponsorship:       +5 points

Common skills carry slightly less weight than rare skills inside the
skills component (rarity weighting, spec §3.4): overlap on rare skills
contributes more per-skill than overlap on ubiquitous ones.
"""
from __future__ import annotations

import re
from typing import Any

# Normalization helper
_NORM_RE = re.compile(r"[^a-z0-9\s]")
_VERSION_RE = re.compile(r"\s*v?\d+(?:\.\d+)*\b")

# Ubiquitous skills: seen in the majority of postings, so overlap on them
# is a weak signal. Rare skills (anything else) are a strong signal.
_COMMON_SKILLS = {
    "git", "agile", "sql", "rest api", "communication", "docker",
    "javascript", "python", "aws", "leadership", "mentoring",
    "teamwork", "collaboration", "problem solving", "time management",
    "scrum", "project management",
}

_SKILL_SYNONYMS: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "node": "nodejs",
    "node js": "nodejs",
    "nodejs": "nodejs",
    "reactjs": "react",
    "react js": "react",
    "vuejs": "vue",
    "vue js": "vue",
    "angularjs": "angular",
    "angular js": "angular",
    "nextjs": "nextjs",
    "next js": "nextjs",
    "nuxtjs": "nuxtjs",
    "nuxt js": "nuxtjs",
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "postgres": "postgresql",
    "psql": "postgresql",
    "aws": "aws",
    "amazon web services": "aws",
    "gcp": "gcp",
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    "golang": "go",
    "cpp": "cpp",
    "c": "cpp",
    "csharp": "csharp",
    "c#": "csharp",
    "dotnet": "dotnet",
    "net": "dotnet",
    "dot net": "dotnet",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "cicd": "cicd",
    "ci cd": "cicd",
    "ci/cd": "cicd",
}


def _normalize(text: str) -> str:
    cleaned = _NORM_RE.sub("", text.lower()).strip()
    # Strip version numbers e.g. python3.9 -> python, angular16 -> angular
    base = _VERSION_RE.sub("", cleaned).strip()
    target = base or cleaned
    return _SKILL_SYNONYMS.get(target, _SKILL_SYNONYMS.get(cleaned, target))


def _norm_set(items: list[str]) -> set[str]:
    return {_normalize(s) for s in items if s and _normalize(s)}


# ── Component scorers ──────────────────────────────────────────────────────────

def score_title_relevance(
    user_titles: list[str],
    job_title: str,
    max_points: int = 40,
) -> int:
    """Score based on how well the job title matches user's target titles."""
    if not user_titles or not job_title:
        return max_points // 4  # neutral when unknown

    job_norm = _normalize(job_title)
    job_words = set(job_norm.split())

    best = 0
    for title in user_titles:
        tnorm = _normalize(title)
        t_words = set(tnorm.split())
        if tnorm == job_norm:
            return max_points  # exact match
        if tnorm in job_norm or job_norm in tnorm:
            best = max(best, max_points - 4)
        elif t_words & job_words:
            overlap = len(t_words & job_words) / max(len(t_words), len(job_words))
            best = max(best, int(overlap * (max_points - 8)))

    return min(best, max_points)


def score_skills_overlap(
    user_skills: list[str],
    job_skills: list[str],
    max_points: int = 50,
) -> int:
    """Score based on skills overlap between user profile and job requirements.

    Rarity-weighted (spec §3.4): overlapping rare skills count more per
    skill than overlapping common ones (JavaScript, Python, Git, …),
    because everyone lists those. Weights: common skill = 1.0,
    rare skill = 1.5, normalized over the job's requirement list.
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

    # Rarity weighting: rare matches weigh 1.5, common weigh 1.0
    weighted_matched = sum(1.5 if s not in _COMMON_SKILLS else 1.0 for s in matched)
    weighted_total = sum(1.5 if s not in _COMMON_SKILLS else 1.0 for s in job_set)
    coverage = weighted_matched / weighted_total  # 0.0 – 1.0

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
    max_points: int = 5,
) -> int:
    """Visa sponsorship bonus (spec §3.2: +5 points)."""
    if job_verified:
        return max_points
    if job_confidence is not None and job_confidence >= 70:
        return max_points - 1
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

    # Base components (spec §3.2): title 40 + skills 50 + experience 10
    title_score = score_title_relevance(user_titles, job_title, max_points=40)
    skills_score = score_skills_overlap(user_skills, job_skills, max_points=50)
    exp_score = score_experience_level(user_years, job_min_yrs, job_max_yrs, max_points=10)
    # Bonuses: location +10, visa +5 (total capped at 100)
    visa_score = score_visa_sponsorship(job_visa, job_confidence, max_points=5)
    loc_score = score_location_preference(user_countries, user_modes, job_country, job_mode, max_points=10)

    return min(100, title_score + skills_score + exp_score + visa_score + loc_score)

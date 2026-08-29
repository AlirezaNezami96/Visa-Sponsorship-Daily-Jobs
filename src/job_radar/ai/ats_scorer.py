"""ATS (Applicant Tracking System) scorer.

Computes a before/after ATS score for a resume against a specific job.
Used to show users how much their tailored resume improved their ATS match.

Scoring breakdown (totals to 100):
  - Keyword overlap (job description keywords in resume): 40 pts
  - Skills overlap (job skills in resume skills):         30 pts
  - Job title match (resume titles vs. job title):        20 pts
  - Resume format quality (section completeness):         10 pts

The scorer is:
  - Fully deterministic (no AI calls) — fast and free
  - Used for "before" scoring (original resume)
  - AI-returned score is used for "after" scoring (tailored resume)
"""
from __future__ import annotations

import re
from typing import Any

# Words to ignore in keyword comparison
_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "are", "have", "will",
    "from", "your", "our", "their", "you", "we", "in", "on", "at", "to",
    "of", "a", "an", "be", "is", "was", "as", "by", "or", "not", "but",
    "also", "all", "any", "can", "do", "has", "had", "its", "may", "new",
    "no", "one", "so", "up", "use", "who", "out", "if", "about", "into",
})

_WORD_RE = re.compile(r"\b[a-z][a-z0-9\-\+#\.]{1,40}\b")


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text, filtered for stop words."""
    if not text:
        return set()
    words = _WORD_RE.findall(text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) >= 3}


def _norm_set(items: list[str]) -> set[str]:
    """Normalize and deduplicate a skill list."""
    return {re.sub(r"[^a-z0-9]", "", s.lower()) for s in items if s}


def score_keyword_overlap(resume_text: str, job_description: str, max_points: int = 40) -> int:
    """Score how many job-description keywords appear in the resume.

    Returns points (0 to max_points).
    """
    if not job_description or not resume_text:
        return max_points // 2  # neutral when one side is empty

    jd_keywords = _extract_keywords(job_description)
    if not jd_keywords:
        return max_points // 2

    resume_keywords = _extract_keywords(resume_text)
    matched = jd_keywords & resume_keywords
    coverage = len(matched) / len(jd_keywords)
    return min(int(coverage * max_points), max_points)


def score_skills_overlap(
    resume_skills: list[str],
    job_skills: list[str],
    max_points: int = 30,
) -> int:
    """Score overlap between explicit skill lists.

    Returns points (0 to max_points).
    """
    if not job_skills:
        return max_points // 2  # neutral when job has no skills

    job_set = _norm_set(job_skills)
    resume_set = _norm_set(resume_skills)

    if not resume_set:
        return 0

    matched = job_set & resume_set
    coverage = len(matched) / len(job_set)
    return min(int(coverage * max_points), max_points)


def score_title_match(
    resume_titles: list[str],
    job_title: str,
    max_points: int = 20,
) -> int:
    """Score how well resume job titles match the target job title.

    Returns points (0 to max_points).
    """
    if not job_title:
        return max_points // 2

    jt_lower = job_title.lower()
    jt_words = set(jt_lower.split())

    if not resume_titles:
        return max_points // 4  # slight penalty when no titles listed

    best = 0
    for title in resume_titles:
        tl = title.lower()
        t_words = set(tl.split())
        if tl == jt_lower:
            return max_points
        if tl in jt_lower or jt_lower in tl:
            best = max(best, max_points - 2)
        elif t_words & jt_words:
            overlap = len(t_words & jt_words) / max(len(t_words), len(jt_words))
            best = max(best, int(overlap * (max_points - 4)))

    return min(best, max_points)


def score_format_quality(parsed_resume: dict[str, Any] | None, max_points: int = 10) -> int:
    """Score resume completeness (presence of key sections).

    Deducts points for missing sections. A complete resume has:
    summary, skills, experience (≥ 1 entry), education (≥ 1 entry).
    """
    if not parsed_resume:
        return 0

    pts = max_points
    deductions = 0

    if not parsed_resume.get("summary"):
        deductions += 2
    if not (parsed_resume.get("skills") or []):
        deductions += 3
    if not (parsed_resume.get("experience") or []):
        deductions += 3
    if not (parsed_resume.get("education") or []):
        deductions += 2

    return max(0, pts - deductions)


def compute_ats_score(
    resume_text: str,
    resume_skills: list[str],
    resume_titles: list[str],
    parsed_resume: dict[str, Any] | None,
    job_description: str,
    job_skills: list[str],
    job_title: str,
) -> int:
    """Compute a composite ATS compatibility score (0–100).

    Args:
        resume_text: Raw resume text.
        resume_skills: List of skills from the resume.
        resume_titles: Job titles from the resume.
        parsed_resume: Parsed resume JSON (for format quality).
        job_description: Full job description text.
        job_skills: Skills extracted from the job.
        job_title: Job title.

    Returns:
        Integer score 0–100.
    """
    kw_score = score_keyword_overlap(resume_text, job_description, max_points=40)
    skills_score = score_skills_overlap(resume_skills, job_skills, max_points=30)
    title_score = score_title_match(resume_titles, job_title, max_points=20)
    format_score = score_format_quality(parsed_resume, max_points=10)

    return min(100, kw_score + skills_score + title_score + format_score)

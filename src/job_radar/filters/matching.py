"""Job title matching rules and regex patterns for AI internships and engineer roles."""
from __future__ import annotations

import re
from typing import Any, Optional

# --- Legacy Mobile Dev Keywords (for backwards compatibility) ---
KEYWORDS_INCLUDE = [
    "android",
    "flutter",
    "kmm",
    "kotlin multiplatform",
]

KEYWORDS_EXCLUDE = [
    "director", "manager", "vp ", "head ", "intern", "co-op",
]

KEYWORDS_INCLUDE_COMPILED = [re.compile(r"\b" + re.escape(k) + r"\b", re.I) for k in KEYWORDS_INCLUDE]
KEYWORDS_EXCLUDE_COMPILED = [re.compile(r"\b" + re.escape(k) + r"\b", re.I) for k in KEYWORDS_EXCLUDE]

# --- Junior / Entry-Level AI & ML Regexes ---
JUNIOR_AI_DOMAIN_REGEX = re.compile(
    r"\b(ai|ml|nlp|llm|genai|machine learning|deep learning|artificial intelligence|"
    r"generative ai|computer vision|data science|data scientist|prompt engineer|"
    r"ai engineer|ml engineer|ai developer|ml developer|ai researcher|ai quality|"
    r"ai forward|ai data)\b",
    re.IGNORECASE,
)

JUNIOR_AI_LEVEL_REGEX = re.compile(
    r"\b(junior|jr|jr\.|trainee|intern|internship|associate|graduate|entry[- ]level|"
    r"starter|apprentice|fellow|fellowship|early[- ]career|0-1|0-2|new grad|new graduate|fresh|entry)\b",
    re.IGNORECASE,
)

JUNIOR_AI_EXCLUDE_REGEX = re.compile(
    r"\b(senior|sr|sr\.|lead|staff|principal|head|director|manager|vp|chief|expert|"
    r"architect|mid[- ]level|experienced|l5|l6|l7)\b",
    re.IGNORECASE,
)

AI_DOMAIN_TERMS = (
    "ai", "ml", "nlp", "llm", "genai", "generative ai", "machine learning",
    "deep learning", "computer vision", "vision", "speech", "robotics",
    "reinforcement learning", "data science", "data scientist", "prompt engineer",
    "mlops", "ai agent", "autonomous", "language model", "neural"
)

INTERN_LEVEL_TERMS = (
    "intern", "internship", "trainee", "fellow", "fellowship", "apprentice",
    "student", "co-op", "coop"
)

ENGINEER_TITLE_PATTERNS = [
    r"\b(ai|ml|machine learning|deep learning|nlp|computer vision|cv|llm|generative ai|mlops|ai agent)\s+(engineer|developer|researcher|scientist)\b",
    r"\b(junior|jr|jr\.|entry[- ]level|associate|graduate|early[- ]career)\s+(ai|ml|machine learning|deep learning|nlp|data science|software)\s*(engineer|developer)?\b",
    r"\b(research engineer|applied scientist|machine learning engineer|ai engineer)\b"
]

INTERNSHIP_TERMS = INTERN_LEVEL_TERMS
ENGINEER_LEVEL_INCLUDE = ["junior", "associate", "graduate", "entry level", "early career", "0-2", "new grad"]
SENIORITY_EXCLUDE = [
    "senior", "sr", "sr.", "staff", "principal", "lead", "director",
    "head of", "vp", "vice president", "chief", "architect", "manager", "l5", "l6", "l7"
]
SENIORITY_EXCLUDE_COMPILED = [re.compile(r"\b" + re.escape(s) + r"\b", re.I) for s in SENIORITY_EXCLUDE]
AI_INTERNSHIP_INCLUDE = [
    "ai intern", "machine learning intern", "ml intern", "applied ai intern",
    "applied scientist intern", "ai research intern", "ml research intern",
    "nlp intern", "computer vision intern", "cv intern", "generative ai intern",
    "llm intern", "deep learning intern", "data science intern", "ai fellowship", "ml fellowship"
]
AI_EARLY_CAREER_INCLUDE = [
    "ai engineer", "machine learning engineer", "ml engineer", "applied ai engineer",
    "research engineer", "nlp engineer", "computer vision engineer", "cv engineer",
    "generative ai engineer", "llm engineer", "deep learning engineer", "mlops engineer",
    "ai agent engineer", "agent engineer", "junior ai engineer", "junior ml engineer",
    "entry level ai engineer", "associate ai engineer", "graduate ai engineer"
]


def match_track(title: str, config: Any = None) -> Optional[str]:
    """Classify a title into 'internship', 'engineer', 'borderline', or None."""
    if config is None:
        try:
            from job_radar.config.loader import get_config
            config = get_config()
        except Exception:
            config = None

    t = title.strip().lower()

    if config and hasattr(config, "tracks"):
        seniority_exclude = config.tracks.seniority_exclude
        internship_include = config.tracks.internship_include
        engineer_include = config.tracks.engineer_include
        borderline_review = config.tracks.borderline_review
    else:
        seniority_exclude = SENIORITY_EXCLUDE
        internship_include = AI_INTERNSHIP_INCLUDE
        engineer_include = AI_EARLY_CAREER_INCLUDE
        borderline_review = [
            "prompt engineer", "data scientist", "data science", "ai specialist", "ai developer"
        ]

    # 1. Seniority exclusion check (strictly reject senior/staff/lead)
    for exc in seniority_exclude:
        if re.search(r"\b" + re.escape(exc) + r"\b", t):
            return None

    # 2. Internship track check (direct keyword or AI domain + Intern term)
    for kw in internship_include:
        if kw in t or re.search(r"\b" + re.escape(kw) + r"\b", t):
            return "internship"

    has_intern_term = any(re.search(r"\b" + re.escape(term) + r"\b", t) for term in INTERN_LEVEL_TERMS)
    has_ai_domain = any(re.search(r"\b" + re.escape(dom) + r"\b", t) for dom in AI_DOMAIN_TERMS)
    if has_intern_term and has_ai_domain:
        return "internship"

    # 3. Borderline review check (prioritized for roles like Data Scientist / Prompt Engineer)
    for kw in borderline_review:
        if re.search(r"\b" + re.escape(kw) + r"\b", t):
            return "borderline"

    # 4. Early-Career Engineer track check
    for kw in engineer_include:
        if kw in t or re.search(r"\b" + re.escape(kw) + r"\b", t):
            return "engineer"

    for pattern in ENGINEER_TITLE_PATTERNS:
        if re.search(pattern, t):
            return "engineer"

    return None


def is_senior_role(title: str) -> bool:
    t = title.strip().lower()
    return any(re.search(r"\b" + re.escape(exc) + r"\b", t) for exc in SENIORITY_EXCLUDE)


def has_visa_signal(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ("visa", "sponsorship", "relocation", "work permit"))


def matches(title: str) -> bool:
    """Check if a job title matches legacy mobile keyword filters."""
    t = title.lower()
    if not any(k in t for k in KEYWORDS_INCLUDE):
        return False
    if any(k in t for k in KEYWORDS_EXCLUDE):
        return False
    return True


is_matching_role = matches


def matches_junior_ai(title: str) -> bool:
    """Check if a job title matches Junior/Entry/Trainee AI/ML roles."""
    t = title.strip()
    if JUNIOR_AI_EXCLUDE_REGEX.search(t):
        return False
    if not JUNIOR_AI_DOMAIN_REGEX.search(t):
        return False
    if not JUNIOR_AI_LEVEL_REGEX.search(t):
        return False
    return True

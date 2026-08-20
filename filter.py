"""Keyword filtering and deduplication for job listings.
Keeps a seen-jobs store to avoid re-alerting.
Supports multi-track filtering (internships vs early-career engineers) and cross-source deduplication.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Maximum age (in seconds) for entries in the seen store. Default: 30 days.
SEEN_MAX_AGE = 30 * 24 * 60 * 60  # 30 days
SEEN_FILE = "seen_jobs.json"

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


# ------------------------------------------------------------------ #
#  URL and Fingerprint Normalization
# ------------------------------------------------------------------ #

def _canonical_job_url(url: str) -> str:
    """Normalize a job URL so tracking parameters do not cause duplicate alerts."""
    if not url:
        return ""
    parsed = urlsplit(url.strip())
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith(("utm_", "ref", "source", "tracking", "gh_src", "lever-source"))
        )
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def _canonical_seen_key(key: str) -> str:
    """Migrate a legacy Company|URL key to the current stable form."""
    if key.startswith("fp|"):
        return key
    company, separator, url = key.partition("|")
    if not separator or not url.startswith(("http://", "https://")):
        return key
    return f"{company.casefold()}|{_canonical_job_url(url)}"


def normalize_company_name(company: str) -> str:
    """Normalize company name for cross-source matching."""
    if not company:
        return ""
    c = company.strip().lower()
    c = re.sub(r"\b(inc|incorporated|corp|corporation|llc|ltd|limited|gmbh|co|technologies|technology|labs|pbc)\b", "", c)
    c = re.sub(r"[^\w\s]", "", c)
    return " ".join(c.split())


def normalize_job_title(title: str) -> str:
    """Normalize job title for cross-source deduplication."""
    if not title:
        return ""
    t = title.strip().lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\binternship\b", "intern", t)
    t = re.sub(r"\bmachine learning\b", "ml", t)
    t = re.sub(r"\bartificial intelligence\b", "ai", t)
    t = re.sub(r"\bdeep learning\b", "dl", t)
    return " ".join(t.split())


def normalize_job_location(location: str) -> str:
    """Normalize location string for fingerprinting."""
    if not location:
        return "remote"
    loc = location.strip().lower()
    if any(w in loc for w in ("remote", "anywhere", "worldwide", "work from home", "virtual")):
        return "remote"
    loc = re.sub(r"[^\w\s]", " ", loc)
    return " ".join(loc.split())


def job_fingerprint(company: str, title: str, location: str = "") -> str:
    """Create a normalized fingerprint for cross-source deduplication."""
    norm_c = normalize_company_name(company)
    norm_t = normalize_job_title(title)
    norm_l = normalize_job_location(location)
    return f"fp|{norm_c}|{norm_t}|{norm_l}"


# ------------------------------------------------------------------ #
#  Seen Store Management
# ------------------------------------------------------------------ #

def _load_seen(path: str = None) -> dict:
    """Load the seen-jobs store, pruning old entries."""
    path = path or SEEN_FILE
    now = time.time()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                seen = json.load(f)
        except (json.JSONDecodeError, IOError):
            seen = {}
    else:
        seen = {}

    if not isinstance(seen, dict):
        return {}

    # Prune old entries
    expired = [
        key for key, value in seen.items()
        if not isinstance(value, dict) or now - value.get("t", 0) > SEEN_MAX_AGE
    ]
    for k in expired:
        del seen[k]

    # Normalize existing keys
    normalized = {}
    for key, value in seen.items():
        normalized_key = _canonical_seen_key(key)
        if normalized_key not in normalized or value.get("t", 0) > normalized[normalized_key].get("t", 0):
            normalized[normalized_key] = value
    return normalized


def _save_seen(seen: dict, path: str = None):
    """Persist the seen-jobs store in compact JSON."""
    path = path or SEEN_FILE
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f, separators=(",", ":"))


# ------------------------------------------------------------------ #
#  Track Matching
# ------------------------------------------------------------------ #

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


def match_track(title: str, config: Any = None) -> Optional[str]:
    """Classify a title into 'internship', 'engineer', 'borderline', or None.
    
    Uses config.yaml tracks if available, with robust multi-keyword fallbacks.
    """
    if config is None:
        try:
            from config_loader import get_config
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
        seniority_exclude = [
            "senior", "sr", "sr.", "staff", "principal", "lead", "director",
            "head of", "vp", "vice president", "chief", "architect", "manager", "l5", "l6", "l7"
        ]
        internship_include = [
            "ai intern", "machine learning intern", "ml intern", "applied ai intern",
            "applied scientist intern", "ai research intern", "ml research intern",
            "nlp intern", "computer vision intern", "cv intern", "generative ai intern",
            "llm intern", "deep learning intern", "data science intern", "ai fellowship", "ml fellowship"
        ]
        engineer_include = [
            "ai engineer", "machine learning engineer", "ml engineer", "applied ai engineer",
            "research engineer", "nlp engineer", "computer vision engineer", "cv engineer",
            "generative ai engineer", "llm engineer", "deep learning engineer", "mlops engineer",
            "ai agent engineer", "agent engineer", "junior ai engineer", "junior ml engineer",
            "entry level ai engineer", "associate ai engineer", "graduate ai engineer"
        ]
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


# ------------------------------------------------------------------ #
#  Radar Deduplication & Filtering
# ------------------------------------------------------------------ #

def dedupe_radar_jobs(jobs: list, seen: dict, config: Any = None) -> list:
    """Filter candidate jobs by track matching and deduplicate against seen store.
    
    Uses both URL canonicalization and (company, title, location) fingerprinting
    to collapse cross-source duplicate postings.
    Updates seen dictionary in-place.
    """
    new_jobs = []
    now = int(time.time())

    for j in jobs:
        title = str(j.get("title", "")).strip()
        url = str(j.get("url", "")).strip()
        company = str(j.get("company", "")).strip() or "Unknown"
        location = str(j.get("location", "")).strip()

        if not title or not url:
            continue

        url_key = f"{company.casefold()}|{_canonical_job_url(url)}"
        fp_key = job_fingerprint(company, title, location)

        # Skip if already alerted under either key
        if url_key in seen or fp_key in seen:
            continue

        track = match_track(title, config=config)
        if not track:
            continue

        # Attach detected track candidate metadata
        job_copy = dict(j)
        job_copy["prefilter_track"] = track
        job_copy["url_key"] = url_key
        job_copy["fp_key"] = fp_key

        # Temporarily register in seen store (persisted after pipeline finishes)
        seen[url_key] = {"t": now, "track": track}
        seen[fp_key] = {"t": now, "track": track}
        new_jobs.append(job_copy)

    return new_jobs


# ------------------------------------------------------------------ #
#  Legacy Compatibility Functions
# ------------------------------------------------------------------ #

def matches(title: str) -> bool:
    """Check if a job title matches legacy mobile keyword filters."""
    t = title.lower()
    if not any(k in t for k in KEYWORDS_INCLUDE):
        return False
    if any(k in t for k in KEYWORDS_EXCLUDE):
        return False
    return True


def dedupe(company: str, jobs: list, seen: dict) -> list:
    """Legacy dedupe for Mobile Visa jobs."""
    new_jobs = []
    for j in jobs:
        title = str(j.get("title", "")).strip()
        url = str(j.get("url", "")).strip()
        if not title or not url:
            continue

        key = f"{company.casefold()}|{_canonical_job_url(url)}"
        legacy_key = f"{company}|{url}"

        if key in seen or legacy_key in seen:
            continue

        if not matches(title):
            continue

        seen[key] = {"t": int(time.time())}
        new_jobs.append(j)

    return new_jobs


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


def dedupe_junior_ai_multi(jobs: list, seen: dict) -> list:
    """Filter jobs by Junior AI keyword match and deduplicate against seen store."""
    new_jobs = []
    for j in jobs:
        title = str(j.get("title", "")).strip()
        url = str(j.get("url", "")).strip()
        company = str(j.get("company", "")).strip() or "Indeed"
        if not title or not url:
            continue

        key = f"{company.casefold()}|{_canonical_job_url(url)}"
        legacy_key = f"{company}|{url}"

        if key in seen or legacy_key in seen:
            continue

        if not matches_junior_ai(title):
            continue

        seen[key] = {"t": int(time.time())}
        new_jobs.append(j)

    return new_jobs


def dedupe_junior_ai(company: str, jobs: list, seen: dict) -> list:
    prepared = []
    for j in jobs:
        item = dict(j)
        if not item.get("company"):
            item["company"] = company
        prepared.append(item)
    return dedupe_junior_ai_multi(prepared, seen)

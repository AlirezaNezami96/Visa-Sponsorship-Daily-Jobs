"""Keyword filtering and deduplication for job listings.
Keeps a seen-jobs store to avoid re-alerting.
"""
import json
import os
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# --- Configurable keywords ---
# Only alert for Android, Flutter, and Kotlin Multiplatform (KMM) job titles.
KEYWORDS_INCLUDE = [
    "android",
    "flutter",
    "kmm",
    "kotlin multiplatform",
]

# Titles containing these words are EXCLUDED even if they match a keyword above.
# Prevents non-IC or non-engineering roles like "Mobile Crisis Counselor" or management roles.
KEYWORDS_EXCLUDE = [
    "director", "manager", "vp ", "head ", "intern", "co-op",
]

# Maximum age (in seconds) for entries in the seen store. Default: 30 days.
SEEN_MAX_AGE = 30 * 24 * 60 * 60  # 30 days

SEEN_FILE = "seen_jobs.json"


def _canonical_seen_key(key: str) -> str:
    """Migrate a legacy ``Company|URL`` key to the current stable form."""
    company, separator, url = key.partition("|")
    if not separator or not url.startswith(("http://", "https://")):
        return key
    return f"{company.casefold()}|{_canonical_job_url(url)}"


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

    # Existing state files used the original URL verbatim.  Migrate in memory
    # so a tracking parameter change does not re-alert a previously seen job.
    normalized = {}
    for key, value in seen.items():
        normalized_key = _canonical_seen_key(key)
        if normalized_key not in normalized or value.get("t", 0) > normalized[normalized_key].get("t", 0):
            normalized[normalized_key] = value
    return normalized


def _save_seen(seen: dict, path: str = None):
    """Persist the seen-jobs store."""
    path = path or SEEN_FILE
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f, separators=(",", ":"))  # Compact JSON


def matches(title: str) -> bool:
    """Check if a job title matches our keyword filters."""
    t = title.lower()

    # Must contain at least one include keyword (Android, Flutter, KMM)
    if not any(k in t for k in KEYWORDS_INCLUDE):
        return False

    # Must NOT contain any exclude keyword
    if any(k in t for k in KEYWORDS_EXCLUDE):
        return False

    return True


def _canonical_job_url(url: str) -> str:
    """Normalize a job URL so tracking parameters do not cause duplicate alerts."""
    parsed = urlsplit(url.strip())
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith(("utm_", "ref", "source", "tracking"))
        )
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def dedupe(company: str, jobs: list, seen: dict) -> list:
    """Filter jobs by keyword match and deduplicate against seen store.
    Updates the seen store in-place. Caller must call _save_seen() after.
    """
    new_jobs = []
    for j in jobs:
        title = str(j.get("title", "")).strip()
        url = str(j.get("url", "")).strip()
        if not title or not url:
            continue

        key = f"{company.casefold()}|{_canonical_job_url(url)}"
        legacy_key = f"{company}|{url}"

        # Keep recognising entries written by older releases while new entries
        # gain URL normalization.
        if key in seen or legacy_key in seen:
            continue

        if not matches(title):
            continue

        seen[key] = {"t": int(time.time())}
        new_jobs.append(j)

    return new_jobs


# --- Junior / Entry-Level AI & ML Keywords ---
JUNIOR_AI_DOMAIN_KEYWORDS = [
    "ai ", " ai", "ai/ml", "ml ", " ml", "machine learning",
    "deep learning", "nlp", "llm", "genai", "generative ai",
    "artificial intelligence", "computer vision", "data science",
    "data scientist", "prompt engineer", "ai engineer", "ml engineer",
    "ai developer", "ml developer", "ai researcher"
]

JUNIOR_AI_LEVEL_KEYWORDS = [
    "junior", "jr", "jr.", "trainee", "intern", "internship",
    "associate", "graduate", "entry level", "entry-level",
    "starter", "apprentice", "fellow", "fellowship", "early career",
    "early-career", "0-1", "0-2", "new grad", "fresh"
]

JUNIOR_AI_EXCLUDE_KEYWORDS = [
    "senior", "sr.", "sr ", " lead", "lead ", "staff", "principal",
    "head", "director", "manager", "vp", "chief", "expert", "architect",
    "mid-level", "mid level", "experienced", "l5", "l6", "l7", "ii", "iii", "iv"
]


def matches_junior_ai(title: str) -> bool:
    """Check if a job title matches Junior/Entry/Trainee AI/ML roles."""
    t = title.lower()

    # Must NOT contain any mid/senior exclude keyword
    if any(k in t for k in JUNIOR_AI_EXCLUDE_KEYWORDS):
        return False

    # Must contain at least one AI/ML domain keyword
    if not any(k in t for k in JUNIOR_AI_DOMAIN_KEYWORDS):
        return False

    # Must contain at least one Junior/Entry level keyword
    if not any(k in t for k in JUNIOR_AI_LEVEL_KEYWORDS):
        return False

    return True


def dedupe_junior_ai(company: str, jobs: list, seen: dict) -> list:
    """Filter jobs by Junior AI keyword match and deduplicate against seen store."""
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

        if not matches_junior_ai(title):
            continue

        seen[key] = {"t": int(time.time())}
        new_jobs.append(j)

    return new_jobs


"""Keyword filtering and deduplication for job listings.
Keeps a seen-jobs store to avoid re-alerting.
"""
import json
import os
import time

# --- Configurable keywords ---
# Edit these to match what you're looking for.
# The scraper only alerts you for jobs whose title contains at least one keyword.
KEYWORDS_INCLUDE = [
    "android", "mobile", "flutter", "react native",
    "software engineer", "developer",
]

# Titles containing these words are EXCLUDED even if they match a keyword above.
# Prevents false positives like "Mobile Crisis Counselor".
KEYWORDS_EXCLUDE = [
    "staff", "principal", "lead ", "director", "manager",
    "vp ", "head ", "intern", "co-op",
]

# Maximum age (in seconds) for entries in the seen store. Default: 30 days.
SEEN_MAX_AGE = 30 * 24 * 60 * 60  # 30 days

SEEN_FILE = "seen_jobs.json"


def _load_seen() -> dict:
    """Load the seen-jobs store, pruning old entries."""
    now = time.time()
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                seen = json.load(f)
        except (json.JSONDecodeError, IOError):
            seen = {}
    else:
        seen = {}

    # Prune old entries
    expired = [k for k, v in seen.items() if now - v.get("t", 0) > SEEN_MAX_AGE]
    for k in expired:
        del seen[k]

    return seen


def _save_seen(seen: dict):
    """Persist the seen-jobs store."""
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, separators=(",", ":"))  # Compact JSON


def matches(title: str) -> bool:
    """Check if a job title matches our keyword filters."""
    t = title.lower()

    # Must contain at least one include keyword
    if not any(k in t for k in KEYWORDS_INCLUDE):
        return False

    # Must NOT contain any exclude keyword
    if any(k in t for k in KEYWORDS_EXCLUDE):
        return False

    return True


def dedupe(company: str, jobs: list, seen: dict) -> list:
    """Filter jobs by keyword match and deduplicate against seen store.
    Updates the seen store in-place. Caller must call _save_seen() after.
    """
    new_jobs = []
    for j in jobs:
        key = f"{company}|{j['url']}"

        if key in seen:
            continue

        if not matches(j["title"]):
            continue

        seen[key] = {"t": int(time.time())}
        new_jobs.append(j)

    return new_jobs

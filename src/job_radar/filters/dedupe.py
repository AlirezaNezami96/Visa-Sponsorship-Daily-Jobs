"""Deduplication and state store management for job listings."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from job_radar.filters.matching import (
    match_track,
    matches,
    matches_junior_ai,
)

SEEN_MAX_AGE = 30 * 24 * 60 * 60  # 30 days
SEEN_FILE = "seen_jobs.json"


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


extract_canonical_job_url = _canonical_job_url


def extract_job_key(company: str, url: str) -> str:
    return f"{company.casefold()}|{_canonical_job_url(url)}"


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


def dedupe_radar_jobs(jobs: list, seen: dict, config: Any = None) -> list:
    """Filter candidate jobs by track matching and deduplicate against seen store."""
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

        job_copy = dict(j)
        job_copy["prefilter_track"] = track
        job_copy["url_key"] = url_key
        job_copy["fp_key"] = fp_key

        seen[url_key] = {"t": now, "track": track}
        seen[fp_key] = {"t": now, "track": track}
        new_jobs.append(job_copy)

    return new_jobs


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

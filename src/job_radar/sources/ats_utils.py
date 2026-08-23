"""Helper utilities for ATS source adapters."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def extract_slug_from_url(url: str, ats_name: str) -> Optional[str]:
    """Extract company slug from career board URL for known ATS platforms."""
    if not url:
        return None
    url = url.strip()
    parsed = urlparse(url if "://" in url else f"https://{url}")
    netloc = parsed.netloc.lower()
    path = parsed.path.strip("/").split("/")

    if ats_name == "greenhouse":
        if "greenhouse.io" in netloc and path:
            return path[0] if path[0] not in ("embed", "v1") else (path[1] if len(path) > 1 else None)
    elif ats_name == "lever":
        if "lever.co" in netloc and path:
            return path[0]
    elif ats_name == "ashby":
        if "ashbyhq.com" in netloc and path:
            return path[0]
    elif ats_name == "workable":
        if "workable.com" in netloc and path:
            return path[0]
    elif ats_name == "smartrecruiters":
        if "smartrecruiters.com" in netloc and path:
            return path[0]
    elif ats_name == "personio":
        if "personio" in netloc:
            subdomain = netloc.split(".")[0]
            if subdomain not in ("www", "jobs", "careers"):
                return subdomain
            if path:
                return path[0]

    # Fallback: if single word passed as URL, treat as slug
    if "/" not in url and "." not in url:
        return url
    return None


def get_curated_companies_for_ats(ats_name: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Load curated companies for a given ATS from data files."""
    candidate_files = [
        "ai_companies.json",
        "companies.json",
        "remote_companies.json",
        "data/ai_companies.json",
        "data/companies.json",
        "data/remote_companies.json",
    ]
    seen_names = set()
    results = []

    for fname in candidate_files:
        if not os.path.exists(fname):
            continue
        try:
            with open(fname, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("scrapable", []) + data.get("custom_ats", [])
            for c in entries:
                if not isinstance(c, dict):
                    continue
                c_ats = c.get("ats", "").lower()
                c_name = c.get("name", "").strip()
                if not c_name or c_name in seen_names:
                    continue
                if c_ats == ats_name.lower():
                    seen_names.add(c_name)
                    results.append(c)
                    if limit and len(results) >= limit:
                        return results
        except Exception as e:
            logger.debug("Failed loading %s: %s", fname, e)

    return results

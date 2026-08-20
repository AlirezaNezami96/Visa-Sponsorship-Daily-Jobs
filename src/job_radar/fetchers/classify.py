"""ATS classification for company careers URLs."""
from __future__ import annotations

import re
from typing import Optional, Tuple

ATS_PATTERNS = {
    "greenhouse":      r"boards\.greenhouse\.io/([\w\-]+)/?",
    "lever":           r"jobs\.lever\.co/([\w\-]+)/?",
    "ashby":           r"ashbyhq\.com/([\w\-]+)/?",
    "smartrecruiters": r"careers\.smartrecruiters\.com/([\w\-]+)/?",
    "personio":        r"([\w\-]+)\.jobs\.personio\.de",
    "workday":         r"mywd\.jobs|wd\d?\.myworkdaysite|workday\.com",
}


def classify(careers_url: Optional[str]) -> Tuple[str, Optional[str]]:
    """Returns (ats_type, slug) for a given careers URL."""
    if not careers_url:
        return "unknown", None
    for ats, pattern in ATS_PATTERNS.items():
        m = re.search(pattern, careers_url, re.IGNORECASE)
        if m:
            slug = m.group(1) if ats != "workday" else None
            return ats, slug
    return "custom", None

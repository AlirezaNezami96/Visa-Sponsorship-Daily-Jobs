"""ATS Discovery tool: probes company names against known ATS providers."""
from __future__ import annotations

import json
import logging
import time
from typing import Optional, Tuple
import requests

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobScraper/2.0)"}

KNOWN_SLUGS = {
    "stripe": ("greenhouse", "stripe"),
    "shopify": ("greenhouse", "shopify"),
    "spotify": ("greenhouse", "spotify"),
    "datadog": ("greenhouse", "datadog"),
    "revolut": ("lever", "revolut"),
    "intercom": ("lever", "intercom"),
    "monzo": ("greenhouse", "monzo"),
    "doordash": ("greenhouse", "doordash"),
    "coinbase": ("greenhouse", "coinbase"),
    "airbnb": ("greenhouse", "airbnb"),
    "notion": ("lever", "notion"),
    "vercel": ("lever", "vercel"),
    "linear": ("ashby", "linear"),
    "supabase": ("ashby", "supabase"),
    "cal": ("ashby", "cal"),
    "figma": ("greenhouse", "figma"),
    "plaid": ("greenhouse", "plaid"),
    "affirm": ("greenhouse", "affirm"),
    "chime": ("greenhouse", "chimefinancial"),
    "canva": ("greenhouse", "canva"),
    "atlassian": ("greenhouse", "atlassian"),
    "aiven": ("greenhouse", "aiven"),
    "squareup": ("greenhouse", "block"),
    "lendi": ("smartrecruiters", "LendiGroup1"),
    "adyen": ("greenhouse", "adyen"),
    "klarna": ("lever", "klarna"),
    "zalando": ("greenhouse", "zalando"),
    "hellofresh": ("greenhouse", "hellofresh"),
    "deliveroo": ("greenhouse", "deliveroo"),
    "wise": ("greenhouse", "wise"),
    "twilio": ("greenhouse", "twilio"),
    "hashicorp": ("greenhouse", "hashicorp"),
    "deputy": ("greenhouse", "deputy"),
    "redbubble": ("greenhouse", "redbubble"),
    "envato": ("lever", "envato"),
    "finder": ("greenhouse", "finder"),
    "linktree": ("ashby", "linktree"),
    "safetyculture": ("lever", "safetyculture"),
    "rokt": ("greenhouse", "rokt"),
    "optiver": ("greenhouse", "optiver"),
    "gocardless": ("greenhouse", "gocardless"),
    "skyscanner": ("greenhouse", "skyscanner"),
    "backbase": ("greenhouse", "backbase"),
    "celonis": ("greenhouse", "celonis"),
    "sap se": ("greenhouse", "sap"),
    "zendesk": ("greenhouse", "zendesk"),
    "tyro": ("greenhouse", "tyro"),
    "hipages": ("greenhouse", "hipages"),
    "propeller": ("greenhouse", "propelleraero"),
    "harrison.ai": ("lever", "harrisonai"),
    "healthengine": ("greenhouse", "healthengine"),
}


def try_discover_ats(name: str, current_url: str = "") -> Tuple[Optional[str], Optional[str]]:
    slug_variants = [
        name.lower().replace(" ", "").replace(".", "").replace("-", ""),
        name.lower().replace(" ", "-"),
        name.lower().replace(" ", ""),
    ]
    for suffix in ["ag", "se", "gmbh", "ltd", "inc", "llc", "pty", "pty ltd"]:
        slug_base = name.lower().replace(" ", "").replace(".", "")
        if slug_base.endswith(suffix):
            slug_variants.append(slug_base[:-len(suffix)])

    seen = set()
    unique_slugs = []
    for s in slug_variants:
        if s and s not in seen:
            seen.add(s)
            unique_slugs.append(s)

    tests = []
    for slug in unique_slugs:
        tests.append((f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", "greenhouse", slug))
        tests.append((f"https://api.lever.co/v0/postings/{slug}?mode=json", "lever", slug))
        tests.append((f"https://api.ashbyhq.com/posting-api/job-board/{slug}", "ashby", slug))

    for url, ats, slug in tests:
        try:
            r = requests.get(url, timeout=8, headers=HEADERS)
            if r.status_code == 200:
                data = r.json()
                if ats == "greenhouse" and data.get("jobs"):
                    return ats, slug
                elif ats == "lever" and isinstance(data, list):
                    return ats, slug
                elif ats == "ashby" and data.get("jobPostings"):
                    return ats, slug
        except Exception:
            pass

    return None, None

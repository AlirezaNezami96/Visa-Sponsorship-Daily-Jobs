#!/usr/bin/env python3
"""
Build ai_companies.json from curated lists of dedicated AI companies & AI job boards.
Separate from visa companies and remote companies.

Usage:
    python build_ai_companies.py
"""
import json
import os
import sys

# ------------------------------------------------------------------ #
#  CURATED AI COMPANIES & DEDICATED AI JOB BOARDS
#  (name, ats, slug_or_url)
# ------------------------------------------------------------------ #
CURATED_AI = [
    # Verified Active AI Companies (Greenhouse API)
    ("Anthropic", "greenhouse", "anthropic"),
    ("Scale AI", "greenhouse", "scaleai"),
    ("Databricks", "greenhouse", "databricks"),
    ("Cresta", "greenhouse", "cresta"),
    ("Together AI", "greenhouse", "togetherai"),
    ("Snorkel AI", "greenhouse", "snorkelai"),
    ("Stability AI", "greenhouse", "stabilityai"),
    ("Labelbox", "greenhouse", "labelbox"),
    ("DeepMind", "greenhouse", "deepmind"),
    ("Abacus AI", "greenhouse", "abacus"),
    ("Otter.ai", "greenhouse", "otterai"),
    ("Descript", "greenhouse", "descript"),
    ("AssemblyAI", "greenhouse", "assemblyai"),
    ("Imbue", "greenhouse", "imbue"),

    # Verified Active AI Companies (Lever API)
    ("Shield AI", "lever", "shieldai"),
    ("Anyscale", "lever", "anyscale"),

    # Verified Active AI Companies (Workable API)
    ("Hugging Face", "workable", "huggingface"),

    # Dedicated AI Job Portals & Niche Aggregators
    ("AI-Jobs.net", "custom", "https://ai-jobs.net"),
    ("DataScienceJobs", "custom", "https://datasciencejobs.com"),
    ("RemoteAI.io", "custom", "https://remoteai.io"),
    ("CryptoJobs AI", "custom", "https://crypto.jobs"),
    ("Web3 Career AI", "custom", "https://web3.career"),
    ("HackerNews AI Jobs", "custom", "https://news.ycombinator.com/jobs"),
]


def main():
    scrapable = []
    custom_ats = []

    print("Building ai_companies.json...")
    for name, ats, slug_or_url in CURATED_AI:
        if ats == "greenhouse":
            url = f"https://boards.greenhouse.io/{slug_or_url}"
            slug = slug_or_url
        elif ats == "lever":
            url = f"https://jobs.lever.co/{slug_or_url}"
            slug = slug_or_url
        elif ats == "ashby":
            url = f"https://{slug_or_url}.ashbyhq.com"
            slug = slug_or_url
        elif ats == "workable":
            url = f"https://apply.workable.com/{slug_or_url}"
            slug = slug_or_url
        elif ats == "smartrecruiters":
            url = f"https://careers.smartrecruiters.com/{slug_or_url}"
            slug = slug_or_url
        else:
            url = slug_or_url
            slug = None

        item = {
            "name": name,
            "careers_url": url,
            "ats": ats,
            "slug": slug,
            "source": "curated_ai",
        }

        if ats in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "personio"):
            scrapable.append(item)
        else:
            custom_ats.append(item)

    out = {
        "scrapable": scrapable,
        "custom_ats": custom_ats,
    }

    out_file = "ai_companies.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"Saved {out_file} ✓")
    print(f"  Scrapable API endpoints: {len(scrapable)}")
    print(f"  Custom websites: {len(custom_ats)}")

if __name__ == "__main__":
    main()

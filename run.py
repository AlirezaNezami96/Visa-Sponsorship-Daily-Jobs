#!/usr/bin/env python3
"""AI Internship & Early-Career Engineer Remote Job Radar.

Discovers, filters, classifies, and alerts for remote AI/ML opportunities
across direct company ATS feeds and public job board APIs.

Usage:
    python run.py                     # Full daily radar run
    python run.py --dry-run           # Preview matches without sending email or updating seen store
    python run.py --no-llm            # Run with fast heuristic classification (bypassing LLM API)
    python run.py --no-public-apis    # Fetch only direct company career boards
    python run.py --limit 10          # Limit company scan for quick debugging
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Tuple

from classify_relevance import classify_and_filter_jobs
from config_loader import get_config, load_radar_config
from email_sender import send_radar_digest
from fetchers_public_apis import fetch_all_public_apis
from filter import _load_seen, _save_seen, dedupe_radar_jobs
from job_pipeline import fetch_companies

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SEEN_FILE = "seen_jobs.json"


def load_all_target_companies(company_files: List[str], limit: Optional[int] = None) -> List[dict]:
    """Load and combine deduplicated company targets from JSON files."""
    combined: Dict[str, dict] = {}

    for fname in company_files:
        if not os.path.exists(fname):
            logger.debug("Company file %s not found; skipping", fname)
            continue
        try:
            with open(fname, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Both 'scrapable' (API) and 'custom_ats' / 'custom' entries
            entries = data.get("scrapable", []) + data.get("custom_ats", [])
            for c in entries:
                name = c.get("name", "").strip()
                if not name:
                    continue
                # If duplicate company, prefer direct ATS over custom
                if name not in combined or (c.get("ats") != "custom" and combined[name].get("ats") == "custom"):
                    combined[name] = c
        except Exception as exc:
            logger.warning("Failed to load company file %s: %s", fname, exc)

    all_companies = list(combined.values())
    if limit and limit > 0:
        all_companies = all_companies[:limit]
    return all_companies


def run(
    dry_run: bool = False,
    no_llm: bool = False,
    no_public_apis: bool = False,
    no_companies: bool = False,
    limit: Optional[int] = None,
    send_empty: Optional[bool] = None,
) -> Tuple[List[dict], List[dict]]:
    """Execute the full AI Radar pipeline."""
    cfg = get_config()
    if no_llm:
        cfg.classifier.enabled = False

    logger.info("=" * 60)
    logger.info("🚀 Launching AI Internship & Engineer Remote Job Radar")
    logger.info("LLM Classifier: %s (model: %s, min_score: %d)", "Enabled" if cfg.classifier.enabled else "Disabled (Rule-based)", cfg.classifier.model, cfg.classifier.min_relevance_score)
    logger.info("=" * 60)

    # 1. Load seen store
    seen = _load_seen(SEEN_FILE)
    logger.info("Loaded seen store: %d entries", len(seen))

    raw_jobs: List[dict] = []
    companies_count = 0
    errors_count = 0

    # 2. Fetch Direct Company ATS Feeds
    if not no_companies:
        companies = load_all_target_companies(cfg.sources.company_files, limit=limit)
        companies_count = len(companies)
        logger.info("Scanning %d curated companies...", companies_count)

        for result in fetch_companies(companies):
            comp_name = result.company.get("name", "Unknown")
            if result.error:
                errors_count += 1
                logger.debug("[%s] %s -> Error: %s", result.method.upper(), comp_name, result.error)
                continue
            for j in result.jobs:
                item = dict(j)
                if not item.get("company"):
                    item["company"] = comp_name
                if not item.get("source"):
                    item["source"] = result.method.upper()
                raw_jobs.append(item)

        logger.info("Fetched %d raw listings from company ATS feeds", len(raw_jobs))

    # 3. Fetch Public Job Board APIs
    boards_count = 0
    if not no_public_apis and cfg.sources.enable_public_apis:
        public_jobs = fetch_all_public_apis(cfg.sources.public_apis)
        boards_count = len([k for k, v in cfg.sources.public_apis.items() if v])
        raw_jobs.extend(public_jobs)

    logger.info("Total raw candidate pool: %d listings", len(raw_jobs))

    # 4. Multi-Track Keyword Pre-Filter + Fingerprint Deduplication
    candidate_jobs = dedupe_radar_jobs(raw_jobs, seen, config=cfg)
    logger.info("Surviving keyword pre-filter candidates: %d jobs", len(candidate_jobs))

    # 5. LLM Relevance Classification Pass
    qualified_jobs, clf_stats = classify_and_filter_jobs(candidate_jobs, config=cfg)

    # 6. Group into Dual Tracks
    internships = [j for j in qualified_jobs if j.get("classified_track") == "internship"]
    engineers = [j for j in qualified_jobs if j.get("classified_track") == "engineer"]

    # 7. Persist seen store (unless dry-run)
    if not dry_run:
        _save_seen(seen, SEEN_FILE)
        logger.info("Persisted updated seen store: %d entries", len(seen))
    else:
        logger.info("[DRY RUN] Seen store left unmodified")

    # 8. Console Summary
    total_found = len(internships) + len(engineers)
    logger.info("\n" + "=" * 60)
    logger.info("🎯 RADAR RUN COMPLETE: %d new matches (%d internships, %d engineers)", total_found, len(internships), len(engineers))
    logger.info("=" * 60)

    if internships:
        logger.info("\n🎓 NEW AI/ML INTERNSHIPS (%d):", len(internships))
        for j in internships:
            logger.info("  • [%s] %s — %s (%d%% match)", j.get("company"), j.get("title"), j.get("location"), j.get("relevance_score", 0))
            if j.get("why_matched"):
                logger.info("    ↳ %s", j.get("why_matched"))

    if engineers:
        logger.info("\n🚀 NEW EARLY-CAREER AI ENGINEERS (%d):", len(engineers))
        for j in engineers:
            logger.info("  • [%s] %s — %s (%d%% match)", j.get("company"), j.get("title"), j.get("location"), j.get("relevance_score", 0))
            if j.get("why_matched"):
                logger.info("    ↳ %s", j.get("why_matched"))

    # 9. Send Email Digest
    health_info = {
        "companies_scanned": companies_count,
        "boards_scanned": boards_count,
        "errors": errors_count,
        "total_evaluated": len(candidate_jobs),
    }

    send_empty_flag = send_empty if send_empty is not None else cfg.email.send_empty_digests
    if not dry_run:
        send_radar_digest(
            internships=internships,
            engineers=engineers,
            health_info=health_info,
            send_empty=send_empty_flag,
            show_visa_tag=cfg.email.show_visa_tag,
        )
    else:
        logger.info("[DRY RUN] Would dispatch email digest: %d internships, %d engineers", len(internships), len(engineers))

    return internships, engineers


def main():
    parser = argparse.ArgumentParser(description="AI Internship & Engineer Remote Job Radar")
    parser.add_argument("--dry-run", action="store_true", help="Preview matches without persisting seen store or sending email")
    parser.add_argument("--no-llm", action="store_true", help="Bypass LLM API calls and use heuristic classifier")
    parser.add_argument("--no-public-apis", action="store_true", help="Disable public job board APIs (RemoteOK, Remotive, etc.)")
    parser.add_argument("--no-companies", action="store_true", help="Disable direct company ATS scanning")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of companies scanned")
    parser.add_argument("--send-empty", action="store_true", help="Send email digest even when zero new jobs are found")
    args = parser.parse_args()

    run(
        dry_run=args.dry_run,
        no_llm=args.no_llm,
        no_public_apis=args.no_public_apis,
        no_companies=args.no_companies,
        limit=args.limit,
        send_empty=args.send_empty if args.send_empty else None,
    )


if __name__ == "__main__":
    main()

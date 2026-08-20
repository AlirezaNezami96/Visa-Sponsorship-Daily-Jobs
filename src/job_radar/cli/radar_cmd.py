"""CLI entrypoint for main AI Internship & Engineer Remote Job Radar."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from job_radar.classifiers.relevance import classify_and_filter_jobs
from job_radar.config.loader import get_config
from job_radar.dedup.store import bulk_mark_sent, is_already_sent, is_available as supabase_available
from job_radar.fetchers.pipeline import fetch_companies
from job_radar.fetchers.public_apis import fetch_all_public_apis
from job_radar.filters.dedupe import _load_seen, _save_seen, dedupe_radar_jobs
from job_radar.filters.freshness import filter_fresh_jobs
from job_radar.notifications.email import send_radar_digest
from job_radar.resume.fetch import fetch_resume_text
from job_radar.resume.matcher import match_resume_batch

logger = logging.getLogger("job_radar")
SEEN_FILE = "seen_jobs.json"


def load_all_target_companies(company_files: List[str], limit: Optional[int] = None) -> List[dict]:
    combined: Dict[str, dict] = {}
    for fname in company_files:
        candidates = [fname, os.path.join("data", os.path.basename(fname))]
        target_path = None
        for c in candidates:
            if os.path.exists(c):
                target_path = c
                break
        if not target_path:
            continue
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("scrapable", []) + data.get("custom_ats", [])
            for c in entries:
                name = c.get("name", "").strip()
                if not name:
                    continue
                if name not in combined or (c.get("ats") != "custom" and combined[name].get("ats") == "custom"):
                    combined[name] = c
        except Exception as exc:
            logger.warning("Failed to load company file %s: %s", target_path, exc)

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
    cfg = get_config()
    if no_llm:
        cfg.classifier.enabled = False

    logger.info("=" * 60)
    logger.info("🚀 Launching AI Internship & Engineer Remote Job Radar")
    logger.info("LLM Classifier: %s (model: %s, min_score: %d)", "Enabled" if cfg.classifier.enabled else "Disabled (Rule-based)", cfg.classifier.model, cfg.classifier.min_relevance_score)
    logger.info("Freshness filter: max_age=%d days", cfg.freshness.max_age_days)
    logger.info("Resume matcher: %s (model: %s)", "Enabled" if cfg.resume_matcher.enabled else "Disabled", cfg.resume_matcher.model)
    logger.info("Supabase dedup: %s", "Connected" if supabase_available() else "Fallback → JSON seen-store")
    logger.info("=" * 60)

    seen = _load_seen(SEEN_FILE)
    logger.info("Loaded seen store: %d entries", len(seen))

    raw_jobs: List[dict] = []
    companies_count = 0
    errors_count = 0

    if not no_companies:
        companies = load_all_target_companies(cfg.sources.company_files, limit=limit)
        companies_count = len(companies)
        logger.info("Scanning %d curated companies...", companies_count)

        for result in fetch_companies(companies):
            comp_name = result.company.get("name", "Unknown")
            if result.error:
                errors_count += 1
                continue
            for j in result.jobs:
                item = dict(j)
                if not item.get("company"):
                    item["company"] = comp_name
                if not item.get("source"):
                    item["source"] = result.method.upper()
                raw_jobs.append(item)

        logger.info("Fetched %d raw listings from company ATS feeds", len(raw_jobs))

    boards_count = 0
    if not no_public_apis and cfg.sources.enable_public_apis:
        public_jobs = fetch_all_public_apis(cfg.sources.public_apis)
        boards_count = len([k for k, v in cfg.sources.public_apis.items() if v])
        raw_jobs.extend(public_jobs)

    logger.info("Total raw candidate pool: %d listings", len(raw_jobs))

    # Freshness filter — drop stale jobs before dedupe
    raw_jobs = filter_fresh_jobs(raw_jobs, max_age_days=cfg.freshness.max_age_days)
    logger.info("After freshness filter: %d listings", len(raw_jobs))

    candidate_jobs = dedupe_radar_jobs(raw_jobs, seen, config=cfg)
    logger.info("Surviving keyword pre-filter candidates: %d jobs", len(candidate_jobs))

    # Supabase cross-track dedup (skip jobs already sent in any track)
    if supabase_available():
        before = len(candidate_jobs)
        candidate_jobs = [
            j for j in candidate_jobs
            if not is_already_sent(j.get("_fingerprint", j.get("url", "")))
        ]
        logger.info("After Supabase cross-track dedup: %d jobs (dropped %d)", len(candidate_jobs), before - len(candidate_jobs))

    qualified_jobs, _ = classify_and_filter_jobs(candidate_jobs, config=cfg)

    # Resume matching — in-memory, fail-open
    if cfg.resume_matcher.enabled and os.environ.get("GEMINI_API_KEY"):
        resume_text = None
        try:
            resume_text = fetch_resume_text(
                doc_id=cfg.resume.doc_id,
                access_method=cfg.resume.access_method,
            )
        except Exception as exc:
            logger.warning("Resume fetch failed: %s — skipping ATS scoring for this run", exc)
        if resume_text:
            logger.info("Running resume matching for %d qualified jobs...", len(qualified_jobs))
            match_resume_batch(qualified_jobs, resume_text, config=cfg)
    else:
        if not os.environ.get("GEMINI_API_KEY"):
            logger.debug("GEMINI_API_KEY not set — skipping resume matching")

    internships = [j for j in qualified_jobs if j.get("classified_track") == "internship"]
    engineers = [j for j in qualified_jobs if j.get("classified_track") == "engineer"]

    if not dry_run:
        _save_seen(seen, SEEN_FILE)
        logger.info("Persisted updated seen store: %d entries", len(seen))
        # Mark sent jobs in Supabase
        if supabase_available() and qualified_jobs:
            bulk_mark_sent(internships, track="visa_intern")
            bulk_mark_sent(engineers, track="visa_engineer")
    else:
        logger.info("[DRY RUN] Seen store and Supabase left unmodified")

    total_found = len(internships) + len(engineers)
    logger.info("\n" + "=" * 60)
    logger.info("🎯 RADAR RUN COMPLETE: %d new matches (%d internships, %d engineers)", total_found, len(internships), len(engineers))
    logger.info("=" * 60)

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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="AI Internship & Engineer Remote Job Radar")
    parser.add_argument("--dry-run", action="store_true", help="Preview matches without persisting seen store or sending email")
    parser.add_argument("--no-llm", action="store_true", help="Bypass LLM API calls and use heuristic classifier")
    parser.add_argument("--no-public-apis", action="store_true", help="Disable public job board APIs")
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

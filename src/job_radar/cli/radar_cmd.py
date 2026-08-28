"""CLI entrypoint for main AI Internship & Engineer Remote Job Radar."""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from job_radar.classifiers.relevance import classify_and_filter_jobs
from job_radar.config.loader import get_config
from job_radar.dedup.store import bulk_mark_sent, is_already_sent, is_available as supabase_available
from job_radar.enrichment.linkedin import enrich_jobs_with_linkedin
from job_radar.fetchers.pipeline import fetch_companies
from job_radar.fetchers.public_apis import fetch_all_public_apis
from job_radar.fetchers.search_grounding import fetch_search_grounded_jobs
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
    no_search_grounding: bool = False,
    force_search_grounding: bool = False,
    limit: Optional[int] = None,
    send_empty: Optional[bool] = None,
) -> Tuple[List[dict], List[dict]]:
    cfg = get_config()
    if no_llm:
        cfg.classifier.enabled = False
    if no_search_grounding:
        cfg.search_grounding.enabled = False
    if force_search_grounding:
        cfg.search_grounding.force_run = True

    logger.info("=" * 60)
    logger.info("🚀 Launching AI Internship & Engineer Remote Job Radar")
    logger.info("LLM Classifier: %s (model: %s, min_score: %d)", "Enabled" if cfg.classifier.enabled else "Disabled (Rule-based)", cfg.classifier.model, cfg.classifier.min_relevance_score)
    logger.info("Freshness filter: max_age=%d days", cfg.freshness.max_age_days)
    logger.info("Resume matcher: %s (model: %s)", "Enabled" if cfg.resume_matcher.enabled else "Disabled", cfg.resume_matcher.model)
    logger.info("Search grounding: %s (model: %s, scheduled hours: %s UTC)", "Enabled" if cfg.search_grounding.enabled else "Disabled", cfg.search_grounding.model, cfg.search_grounding.run_hours_utc)
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
                if hasattr(j, "to_legacy_dict"):
                    item = j.to_legacy_dict()
                else:
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

    # 4th source: Gemini Search-Grounded Discovery
    current_utc_hour = datetime.datetime.now(datetime.timezone.utc).hour
    should_run_grounding = cfg.search_grounding.enabled and (
        current_utc_hour in cfg.search_grounding.run_hours_utc or getattr(cfg.search_grounding, "force_run", False)
    )
    if should_run_grounding:
        logger.info("Triggering search grounding for 'visa_sponsorship' (UTC hour %d)...", current_utc_hour)
        grounded_jobs = fetch_search_grounded_jobs("visa_sponsorship", config=cfg)
        if grounded_jobs:
            logger.info("Search grounding discovered %d visa sponsorship candidate jobs", len(grounded_jobs))
            raw_jobs.extend(grounded_jobs)
    else:
        logger.debug("Search grounding skipped for this slot (current UTC hour: %d, scheduled: %s)", current_utc_hour, cfg.search_grounding.run_hours_utc)

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

    # Fetch resume once for single-pass combined LLM evaluation
    resume_text = None
    if cfg.resume_matcher.enabled and os.environ.get("GEMINI_API_KEY"):
        try:
            resume_text = fetch_resume_text(
                doc_id=cfg.resume.doc_id,
                access_method=cfg.resume.access_method,
            )
            if resume_text:
                logger.info("Loaded candidate resume for single-pass matching (%d chars)", len(resume_text))
        except Exception as exc:
            logger.warning("Resume fetch failed: %s — skipping resume matching for this run", exc)

    qualified_jobs, clf_stats = classify_and_filter_jobs(candidate_jobs, config=cfg, resume_text=resume_text)

    # Multi-dimensional ranking:
    # 1. Visa status: sponsors -> likely -> opt_friendly -> unknown -> no
    # 2. Relevance score: descending
    # 3. Resume match score: descending
    # 4. Date posted / Recency
    visa_order = {"sponsors": 0, "likely": 1, "opt_friendly": 2, "unknown": 3, "no": 4}
    qualified_jobs.sort(
        key=lambda x: (
            visa_order.get(x.get("visa_status", "unknown"), 3),
            -(x.get("relevance_score") or 0),
            -(x.get("resume_match_score") or 0),
            str(x.get("date_posted") or ""),
        )
    )

    # Company LinkedIn page discovery & enrichment (after discovery is finalized)
    if qualified_jobs:
        logger.info("Enriching %d qualified jobs with company LinkedIn pages...", len(qualified_jobs))
        enrich_jobs_with_linkedin(qualified_jobs)

    internships = [j for j in qualified_jobs if j.get("classified_track") == "internship"]
    engineers = [j for j in qualified_jobs if j.get("classified_track") == "engineer"]

    # Atomic state persist: write once at end of successful run (never in dry-run)
    if not dry_run:
        _save_seen(seen, SEEN_FILE)
        logger.info("Atomically persisted updated seen store: %d entries", len(seen))
        # Mark sent jobs in Supabase
        if supabase_available() and qualified_jobs:
            bulk_mark_sent(internships, track="visa_intern")
            bulk_mark_sent(engineers, track="visa_engineer")
    else:
        logger.info("[DRY RUN] Seen store and Supabase left unmodified (atomic write skipped)")

    # VisaLane backend sync: companies/jobs tables + alert/social/enrichment
    # staging. Opt-in (VISALANE_SYNC=1) so existing cron workflows keep their
    # current behavior; fail-open — a sync error never breaks the radar run.
    if not dry_run and os.environ.get("VISALANE_SYNC") == "1" and qualified_jobs:
        try:
            from job_radar.visalane.stages import sync_qualified_jobs

            sync_stats = sync_qualified_jobs(
                qualified_jobs,
                source_name="radar",
                do_enrichment=os.environ.get("VISALANE_ENRICHMENT") == "1",
            )
            logger.info("VisaLane sync stats: %s", sync_stats)
        except Exception as exc:
            logger.warning("VisaLane sync failed (non-fatal): %s", exc)

    total_found = len(internships) + len(engineers)
    logger.info("\n" + "=" * 60)
    logger.info("🎯 RADAR RUN COMPLETE: %d new matches (%d internships, %d engineers)", total_found, len(internships), len(engineers))
    logger.info("Visa breakdown: %s", clf_stats.get("visa_status_counts", {}))
    logger.info("=" * 60)

    from job_radar.fetchers.ats import global_circuit_breaker
    health_info = {
        "companies_scanned": companies_count,
        "boards_scanned": boards_count,
        "errors": errors_count,
        "total_evaluated": len(candidate_jobs),
        "total_qualified": len(qualified_jobs),
        "circuit_breaker_trips": global_circuit_breaker.get_trip_counts(),
        "visa_status_counts": clf_stats.get("visa_status_counts", {}),
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
    parser.add_argument("--no-search-grounding", action="store_true", help="Disable Gemini search-grounded discovery")
    parser.add_argument("--force-search-grounding", action="store_true", help="Force search-grounded discovery regardless of scheduled UTC hours")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of companies scanned")
    parser.add_argument("--send-empty", action="store_true", help="Send email digest even when zero new jobs are found")
    args = parser.parse_args()

    run(
        dry_run=args.dry_run,
        no_llm=args.no_llm,
        no_public_apis=args.no_public_apis,
        no_companies=args.no_companies,
        no_search_grounding=args.no_search_grounding,
        force_search_grounding=args.force_search_grounding,
        limit=args.limit,
        send_empty=args.send_empty if args.send_empty else None,
    )


if __name__ == "__main__":
    main()

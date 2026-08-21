"""CLI entrypoint for JustJoin.it Scraper (AI/ML and Mobile tracks)."""
from __future__ import annotations

import argparse
import datetime
import logging
import os
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from job_radar.config.loader import get_config
from job_radar.dedup.store import bulk_mark_sent, is_already_sent, is_available as supabase_available
from job_radar.enrichment.linkedin import enrich_jobs_with_linkedin
from job_radar.fetchers.justjoin import fetch_justjoin_jobs
from job_radar.filters.dedupe import _load_seen, _save_seen
from job_radar.notifications.email import send_justjoin_email
from job_radar.resume.fetch import fetch_resume_text
from job_radar.resume.matcher import match_resume_batch

logger = logging.getLogger("job_radar.justjoin")
JUSTJOIN_SEEN_FILE = "seen_justjoin_jobs.json"


def _canonicalize_justjoin_url(url: str) -> str:
    """Strip query parameters from JustJoin URLs for consistent deduplication."""
    if not url:
        return ""
    parsed = urlsplit(url.strip())
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower() or "https", parsed.netloc.lower(), path, "", ""))


def dedupe_justjoin(jobs: List[Dict[str, Any]], seen: dict) -> List[Dict[str, Any]]:
    """Deduplicate JustJoin jobs against local seen store."""
    new_jobs: List[Dict[str, Any]] = []
    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    for j in jobs:
        url = j.get("url", "").strip()
        company = j.get("company", "").strip().lower()
        canon_url = _canonicalize_justjoin_url(url)
        if not canon_url:
            continue

        key = f"{company}|{canon_url}"
        if key not in seen and canon_url not in seen:
            seen[key] = {
                "t": now_ts,
                "title": j.get("title", ""),
                "category": j.get("category", ""),
            }
            new_jobs.append(j)

    return new_jobs


def run(
    dry_run: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Execute JustJoin scraping pipeline."""
    cfg = get_config()

    logger.info("Initializing JustJoin.it Daily Job Scraper (AI & Mobile)")
    logger.info("Supabase dedup: %s", "Connected" if supabase_available() else "Fallback → JSON seen-store")

    seen = _load_seen(JUSTJOIN_SEEN_FILE)
    logger.info("Loaded JustJoin seen store: %d entries", len(seen))

    # Fetch candidate resume once per run (fail-open)
    resume_text = None
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            if cfg.resume_matcher.enabled:
                resume_text = fetch_resume_text(
                    doc_id=cfg.resume.doc_id,
                    access_method=cfg.resume.access_method,
                )
        except Exception as exc:
            logger.warning("Resume fetch failed: %s — skipping ATS scoring", exc)

    # 1. Fetch raw candidate jobs from JustJoin.it
    raw_jobs = fetch_justjoin_jobs()
    logger.info("Fetched %d raw jobs across JustJoin.it categories", len(raw_jobs))

    # 2. Local seen-store deduplication
    new_jobs = dedupe_justjoin(raw_jobs, seen)
    logger.info("After seen-store deduplication: %d new jobs", len(new_jobs))

    # 3. Supabase cross-track deduplication
    if supabase_available() and new_jobs:
        before = len(new_jobs)
        new_jobs = [j for j in new_jobs if not is_already_sent(j.get("url", ""))]
        logger.info("After Supabase cross-track dedup: %d jobs (dropped %d)", len(new_jobs), before - len(new_jobs))

    # 4. Resume ATS matching
    if resume_text and new_jobs:
        logger.info("Running resume ATS scoring for %d JustJoin jobs...", len(new_jobs))
        match_resume_batch(new_jobs, resume_text, config=cfg)

    # 5. Company LinkedIn page discovery & enrichment
    if new_jobs:
        logger.info("Enriching %d JustJoin jobs with company LinkedIn pages...", len(new_jobs))
        enrich_jobs_with_linkedin(new_jobs)

    # Split by track
    ai_jobs = [j for j in new_jobs if j.get("category") == "AI / ML"]
    mobile_jobs = [j for j in new_jobs if j.get("category") == "Mobile"]

    logger.info(
        "TOTALS: %d raw jobs fetched, %d new matches (%d AI/ML, %d Mobile)",
        len(raw_jobs), len(new_jobs), len(ai_jobs), len(mobile_jobs),
    )

    if not dry_run:
        _save_seen(seen, JUSTJOIN_SEEN_FILE)
        logger.info("Updated JustJoin seen store: %d total entries in %s", len(seen), JUSTJOIN_SEEN_FILE)
        if supabase_available() and new_jobs:
            bulk_mark_sent(new_jobs, track="justjoin")

        if new_jobs:
            send_justjoin_email(ai_jobs, mobile_jobs)
        else:
            logger.info("No new matching jobs found on JustJoin.it today — skipping email.")
    else:
        logger.info("[DRY RUN] State files and Supabase left unchanged.")
        if new_jobs:
            logger.info("[DRY RUN] Would send email digest with %d AI and %d Mobile jobs.", len(ai_jobs), len(mobile_jobs))

    return ai_jobs, mobile_jobs


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="JustJoin.it Daily Job Scraper (AI & Mobile)")
    parser.add_argument("--dry-run", action="store_true", help="Don't send email or persist state changes")
    args = parser.parse_args()

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Main orchestrator: fetches jobs from all companies, filters, deduplicates, emails.

Usage:
    python run.py                    # Normal run
    python run.py --dry-run          # Print results without sending email
    python run.py --build            # Rebuild companies.json first
    python run.py --classify-only    # Only show ATS classification stats
"""
import argparse
import json
import os
import sys
import time
import logging

from fetchers import FETCHERS
from fetcher_custom import fetch_custom_sync
from filter import dedupe, _load_seen, _save_seen, matches
from email_sender import send_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

COMPANIES_FILE = "companies.json"
REQUEST_DELAY = 0.5  # seconds between API calls (be polite)


def load_companies() -> list:
    """Load the scrapable companies list."""
    if not os.path.exists(COMPANIES_FILE):
        logger.error(f"{COMPANIES_FILE} not found. Run 'python build_companies.py' first.")
        sys.exit(1)

    with open(COMPANIES_FILE, "r") as f:
        data = json.load(f)

    # Combine scrapable + custom_ats into one list
    companies = data.get("scrapable", []) + data.get("custom_ats", [])
    return companies


def fetch_jobs_for_company(company: dict) -> list:
    """Fetch all jobs for a single company using the appropriate fetcher."""
    name = company["name"]
    ats = company["ats"]
    slug = company.get("slug")
    url = company["careers_url"]

    if ats in FETCHERS:
        logger.info(f"  [{ats.upper()}] {name} (slug: {slug})")
        try:
            jobs = FETCHERS[ats](slug)
            logger.info(f"    -> {len(jobs)} jobs found")
            return jobs
        except Exception as e:
            logger.warning(f"    -> Error: {e}")
            return [{"error": str(e)}]

    elif ats in ("custom", "workday", "unknown"):
        logger.info(f"  [CUSTOM] {name} ({url})")
        try:
            jobs = fetch_custom_sync(url)
            logger.info(f"    -> {len(jobs)} jobs found")
            return jobs
        except Exception as e:
            logger.warning(f"    -> Error: {e}")
            return [{"error": str(e)}]

    else:
        logger.warning(f"  [SKIP] {name} — unknown ATS: {ats}")
        return []


def run(dry_run: bool = False):
    """Main pipeline."""
    companies = load_companies()
    logger.info(f"Loaded {len(companies)} companies")

    # ATS distribution
    ats_counts = {}
    for c in companies:
        ats_counts[c["ats"]] = ats_counts.get(c["ats"], 0) + 1
    logger.info(f"ATS distribution: {ats_counts}")

    # Load seen store
    seen = _load_seen()
    logger.info(f"Seen store: {len(seen)} entries")

    report = []  # list of (company_name, [matching_jobs])
    total_fetched = 0
    total_matching = 0
    errors = 0

    for i, company in enumerate(companies):
        name = company["name"]
        logger.info(f"[{i+1}/{len(companies)}] Fetching {name}...")

        try:
            jobs = fetch_jobs_for_company(company)
            total_fetched += len([j for j in jobs if "error" not in j])

            if jobs and "error" not in jobs[0]:
                new = dedupe(name, jobs, seen)
                if new:
                    total_matching += len(new)
                    report.append((name, new))
                    for j in new:
                        logger.info(f"    MATCH: {j['title']} — {j.get('location', '')}")

            elif jobs and "error" in jobs[0]:
                errors += 1
                logger.warning(f"  Error fetching {name}: {jobs[0]['error']}")

        except Exception as e:
            errors += 1
            logger.error(f"  Unexpected error for {name}: {e}")

        # Rate limiting
        time.sleep(REQUEST_DELAY)

    # Save updated seen store
    _save_seen(seen)
    logger.info(f"Updated seen store: {len(seen)} entries")

    # Summary
    logger.info(f"\n{'='*50}")
    logger.info(f"TOTALS: {total_fetched} jobs fetched, {total_matching} new matches, {errors} errors")
    logger.info(f"Companies with matches: {len(report)}")

    if report:
        logger.info(f"\nNew jobs found:")
        for company, jobs in report:
            for j in jobs:
                logger.info(f"  - [{company}] {j['title']} ({j.get('location', '')})")

    # Send email (unless dry run or no matches)
    if not dry_run and report:
        logger.info("\nSending email...")
        send_email(report)
    elif dry_run and report:
        logger.info(f"\n[DRY RUN] Would send email with {len(report)} companies")
    elif not report:
        logger.info("\nNo new matching jobs today. No email sent.")

    return report


def classify_only():
    """Just show ATS classification stats, don't fetch anything."""
    companies = load_companies()
    ats_counts = {}
    for c in companies:
        ats = c["ats"]
        ats_counts[ats] = ats_counts.get(ats, 0) + 1

    print(f"\n{'='*50}")
    print(f"Total companies: {len(companies)}")
    print(f"\nATS Distribution:")
    for ats, count in sorted(ats_counts.items(), key=lambda x: -x[1]):
        pct = count / len(companies) * 100
        bar = "\u2588" * int(pct / 5)
        print(f"  {ats:20s} {count:4d} ({pct:5.1f}%) {bar}")

    print(f"\nCompanies by ATS:")
    for ats in sorted(ats_counts.keys()):
        cos = [c for c in companies if c["ats"] == ats]
        print(f"\n  [{ats.upper()}]")
        for c in cos[:10]:
            print(f"    - {c['name']:30s} {c['careers_url'][:60]}")
        if len(cos) > 10:
            print(f"    ... and {len(cos) - 10} more")


def main():
    parser = argparse.ArgumentParser(description="Visa Job Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Don't send email")
    parser.add_argument("--build", action="store_true", help="Rebuild companies.json first")
    parser.add_argument("--classify-only", action="store_true", help="Show ATS classification stats")
    args = parser.parse_args()

    if args.build:
        import build_companies
        build_companies.main()
        print()

    if args.classify_only:
        classify_only()
        return

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

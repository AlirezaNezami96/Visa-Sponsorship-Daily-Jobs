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
import logging

from filter import dedupe, _load_seen, _save_seen
from job_pipeline import fetch_companies
from email_sender import send_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

COMPANIES_FILE = "companies.json"


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

    for i, result in enumerate(fetch_companies(companies)):
        company = result.company
        name = company["name"]
        if result.error:
            errors += 1
            logger.warning("[%d/%d] [%s] %s -> Error: %s", i + 1, len(companies), result.method.upper(), name, result.error)
            continue

        jobs = result.jobs
        total_fetched += len(jobs)
        logger.info("[%d/%d] [%s] %s -> %d jobs", i + 1, len(companies), result.method.upper(), name, len(jobs))
        new = dedupe(name, jobs, seen)
        if new:
            total_matching += len(new)
            report.append((name, new))
            for job in new:
                logger.info("    MATCH: %s — %s", job["title"], job.get("location", ""))

    # A dry run must be repeatable: it previews results without consuming the
    # alerts that the next scheduled run should send.
    if not dry_run:
        _save_seen(seen)
        logger.info(f"Updated seen store: {len(seen)} entries")
    else:
        logger.info("[DRY RUN] Seen store left unchanged")

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

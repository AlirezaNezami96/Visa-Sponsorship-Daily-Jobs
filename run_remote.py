#!/usr/bin/env python3
"""
Remote-job scanner: fetches jobs from fully-remote companies, filters by
job title keywords, deduplicates, and emails a daily digest.

This is a separate pipeline from run.py (visa sponsorship jobs).
It reads from remote_companies.json and uses seen_remote_jobs.json as
its own state store so the two pipelines never interfere.

Usage:
    python run_remote.py                    # Normal run
    python run_remote.py --dry-run          # Print results without sending email
    python run_remote.py --build            # Rebuild remote_companies.json first
    python run_remote.py --classify-only    # Show ATS distribution stats
"""
import argparse
import json
import os
import sys
import time
import logging

from fetchers import FETCHERS
from fetcher_custom import fetch_custom_sync
from filter import _load_seen, _save_seen, matches

# Override the seen-file path for the remote pipeline so it is isolated
# from the visa-sponsorship pipeline's seen_jobs.json
REMOTE_SEEN_FILE = "seen_remote_jobs.json"

# ------------------------------------------------------------------ #
#  Monkey-patch filter.SEEN_FILE so _load_seen / _save_seen use the
#  remote file without modifying filter.py at all.
# ------------------------------------------------------------------ #
import filter as _filter_module
_filter_module.SEEN_FILE = REMOTE_SEEN_FILE

from email_sender import send_email as _base_send_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

REMOTE_COMPANIES_FILE = "remote_companies.json"
REQUEST_DELAY = 0.5  # seconds between API calls


# ------------------------------------------------------------------ #
#  Email wrapper — changes subject/header to "Remote Job Digest"
# ------------------------------------------------------------------ #
def send_remote_email(report: list):
    """Send the remote-job digest email with a distinct subject/header."""
    import os
    import requests as http_requests
    from email_sender import (
        _send_via_resend, _send_via_sendgrid, _send_via_gmail_smtp,
        _build_html,
    )

    if not report:
        print("No new remote jobs found — skipping email.")
        return

    total_jobs = sum(len(jobs) for _, jobs in report)
    html = _build_remote_html(report, total_jobs)
    subject = f"💻 Remote Job Digest — {len(report)} companies, {total_jobs} jobs"

    provider = os.environ.get("EMAIL_PROVIDER", "resend").lower()
    if provider == "resend":
        _send_via_resend(subject, html)
    elif provider == "sendgrid":
        _send_via_sendgrid(subject, html)
    elif provider == "gmail":
        _send_via_gmail_smtp(subject, html)
    else:
        raise ValueError(f"Unknown email provider: {provider}")

    print(f"Remote email sent via {provider}: {total_jobs} jobs from {len(report)} companies")


def _build_remote_html(report: list, total_jobs: int) -> str:
    """Build HTML email specifically for remote jobs digest."""
    import datetime
    html_parts = [
        '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; max-width: 680px; margin: 0 auto; color: #1a1a1a;">',
        '<div style="background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); padding: 24px 28px; border-radius: 12px 12px 0 0;">',
        f'<h1 style="margin: 0; color: white; font-size: 22px;">💻 Remote Job Digest</h1>',
        f'<p style="margin: 6px 0 0; color: rgba(255,255,255,0.85); font-size: 14px;">{len(report)} companies · {total_jobs} new remote jobs · {datetime.datetime.now().strftime("%b %d, %Y")}</p>',
        '</div>',
        '<div style="padding: 20px 28px 28px; background: #fff; border: 1px solid #e8e8e8; border-top: none; border-radius: 0 0 12px 12px;">',
    ]

    for company, jobs in report:
        html_parts.append(f'<h2 style="margin: 20px 0 8px; font-size: 17px; color: #333;">{company} <span style="font-size:12px;color:#11998e;font-weight:normal;">🌍 Remote</span></h2>')
        html_parts.append('<ul style="margin: 0; padding-left: 20px;">')
        for j in jobs:
            if "error" in j:
                html_parts.append(f'<li style="margin: 4px 0; color: #999;">⚠️ {j["error"]}</li>')
            else:
                loc = j.get("location", "Remote")
                dept = j.get("department", "")
                meta = " · ".join(filter(None, [loc, dept]))
                html_parts.append(
                    f'<li style="margin: 6px 0; line-height: 1.5;">'
                    f'<a href="{j["url"]}" style="color: #11998e; text-decoration: none; font-weight: 500;">{j["title"]}</a>'
                    f'{"<span style=\"color: #888; font-size: 13px;\"> " + meta + "</span>" if meta else ""}'
                    f'</li>'
                )
        html_parts.append('</ul>')

    html_parts.extend([
        '</div>',
        '<p style="text-align: center; color: #aaa; font-size: 12px; margin-top: 16px;">'
        'Powered by remote-job-scraper · Update your keywords in filter.py</p>',
        '</div>',
    ])
    return "\n".join(html_parts)


# ------------------------------------------------------------------ #
#  Main pipeline
# ------------------------------------------------------------------ #
def load_remote_companies() -> list:
    """Load the remote companies list."""
    if not os.path.exists(REMOTE_COMPANIES_FILE):
        logger.error(
            f"{REMOTE_COMPANIES_FILE} not found. "
            "Run 'python build_remote_companies.py' first."
        )
        sys.exit(1)

    with open(REMOTE_COMPANIES_FILE, "r") as f:
        data = json.load(f)

    return data.get("scrapable", []) + data.get("custom_ats", [])


def fetch_jobs_for_company(company: dict) -> list:
    """Fetch all jobs for a single remote company."""
    name = company["name"]
    ats = company["ats"]
    slug = company.get("slug")
    url = company.get("careers_url", "")

    if ats in FETCHERS:
        logger.info(f"  [{ats.upper()}] {name} (slug: {slug})")
        try:
            jobs = FETCHERS[ats](slug)
            logger.info(f"    -> {len(jobs)} jobs found")
            return jobs
        except Exception as e:
            logger.warning(f"    -> Error: {e}")
            return [{"error": str(e)}]

    elif ats in ("custom", "workday", "unknown", "workable"):
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
    """Main remote-jobs pipeline."""
    companies = load_remote_companies()
    logger.info(f"Loaded {len(companies)} remote companies")

    ats_counts = {}
    for c in companies:
        ats_counts[c["ats"]] = ats_counts.get(c["ats"], 0) + 1
    logger.info(f"ATS distribution: {ats_counts}")

    seen = _load_seen()
    logger.info(f"Seen store (remote): {len(seen)} entries")

    report = []
    total_fetched = 0
    total_matching = 0
    errors = 0

    from filter import dedupe

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
                        logger.info(f"    MATCH: {j['title']} — {j.get('location', 'Remote')}")

            elif jobs and "error" in jobs[0]:
                errors += 1
                logger.warning(f"  Error fetching {name}: {jobs[0]['error']}")

        except Exception as e:
            errors += 1
            logger.error(f"  Unexpected error for {name}: {e}")

        time.sleep(REQUEST_DELAY)

    _save_seen(seen)
    logger.info(f"Updated remote seen store: {len(seen)} entries")

    logger.info(f"\n{'='*50}")
    logger.info(f"TOTALS: {total_fetched} jobs fetched, {total_matching} new remote matches, {errors} errors")
    logger.info(f"Companies with matches: {len(report)}")

    if report:
        logger.info("\nNew remote jobs found:")
        for company, jobs in report:
            for j in jobs:
                logger.info(f"  - [{company}] {j['title']} ({j.get('location', 'Remote')})")

    if not dry_run and report:
        logger.info("\nSending remote job email...")
        send_remote_email(report)
    elif dry_run and report:
        logger.info(f"\n[DRY RUN] Would send email with {len(report)} companies")
    elif not report:
        logger.info("\nNo new matching remote jobs today. No email sent.")

    return report


def classify_only():
    """Show ATS distribution stats for remote companies."""
    companies = load_remote_companies()
    ats_counts = {}
    for c in companies:
        ats = c["ats"]
        ats_counts[ats] = ats_counts.get(ats, 0) + 1

    print(f"\n{'='*50}")
    print(f"Total remote companies: {len(companies)}")
    print(f"\nATS Distribution:")
    for ats, count in sorted(ats_counts.items(), key=lambda x: -x[1]):
        pct = count / len(companies) * 100
        bar = "█" * int(pct / 5)
        print(f"  {ats:20s} {count:4d} ({pct:5.1f}%) {bar}")


def main():
    parser = argparse.ArgumentParser(description="Remote Job Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Don't send email")
    parser.add_argument("--build", action="store_true", help="Rebuild remote_companies.json first")
    parser.add_argument("--classify-only", action="store_true", help="Show ATS stats")
    args = parser.parse_args()

    if args.build:
        import build_remote_companies
        build_remote_companies.main()
        print()

    if args.classify_only:
        classify_only()
        return

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

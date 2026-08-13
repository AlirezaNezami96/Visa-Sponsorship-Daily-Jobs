#!/usr/bin/env python3
"""
Junior AI & ML Job Scanner: fetches jobs from remote & visa sponsorship companies,
filters specifically for Junior / Trainee / Associate / Entry-Level AI & ML roles,
deduplicates against seen_junior_ai_jobs.json, and sends a daily email digest.

Usage:
    python run_junior_ai.py                    # Normal run
    python run_junior_ai.py --dry-run          # Print results without sending email
    python run_junior_ai.py --classify-only    # Show ATS distribution stats
"""
import argparse
import json
import os
import sys
import logging

from filter import _load_seen, _save_seen, dedupe_junior_ai
from job_pipeline import fetch_companies

JUNIOR_AI_SEEN_FILE = "seen_junior_ai_jobs.json"
AI_COMPANIES_FILE = "ai_companies.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Email wrapper — "Junior AI & ML Job Digest"
# ------------------------------------------------------------------ #
def send_junior_ai_email(report: list):
    """Send the Junior AI job digest email."""
    from email_sender import (
        _send_via_resend, _send_via_sendgrid, _send_via_gmail_smtp,
    )

    if not report:
        print("No new Junior AI & ML jobs found — skipping email.")
        return

    total_jobs = sum(len(jobs) for _, jobs in report)
    html = _build_junior_ai_html(report, total_jobs)
    subject = f"🤖 Junior AI & ML Job Digest — {len(report)} companies, {total_jobs} jobs"

    provider = os.environ.get("EMAIL_PROVIDER", "resend").lower()
    if provider == "resend":
        _send_via_resend(subject, html)
    elif provider == "sendgrid":
        _send_via_sendgrid(subject, html)
    elif provider == "gmail":
        _send_via_gmail_smtp(subject, html)
    else:
        raise ValueError(f"Unknown email provider: {provider}")

    print(f"Junior AI email sent via {provider}: {total_jobs} jobs from {len(report)} companies")


def _build_junior_ai_html(report: list, total_jobs: int) -> str:
    """Build HTML email specifically for Junior AI & ML jobs digest."""
    import datetime
    html_parts = [
        '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; max-width: 680px; margin: 0 auto; color: #1a1a1a;">',
        '<div style="background: linear-gradient(135deg, #FF512F 0%, #DD2476 100%); padding: 24px 28px; border-radius: 12px 12px 0 0;">',
        '<h1 style="margin: 0; color: white; font-size: 22px;">🤖 Junior AI & ML Job Digest</h1>',
        f'<p style="margin: 6px 0 0; color: rgba(255,255,255,0.85); font-size: 14px;">{len(report)} companies · {total_jobs} new junior/entry AI jobs · {datetime.datetime.now().strftime("%b %d, %Y")}</p>',
        '</div>',
        '<div style="padding: 20px 28px 28px; background: #fff; border: 1px solid #e8e8e8; border-top: none; border-radius: 0 0 12px 12px;">',
    ]

    for company, jobs in report:
        html_parts.append(f'<h2 style="margin: 20px 0 8px; font-size: 17px; color: #333;">{company} <span style="font-size:12px;color:#DD2476;font-weight:normal;">🎯 Junior / Trainee AI</span></h2>')
        html_parts.append('<ul style="margin: 0; padding-left: 20px;">')
        for j in jobs:
            if "error" in j:
                html_parts.append(f'<li style="margin: 4px 0; color: #999;">⚠️ {j["error"]}</li>')
            else:
                loc = j.get("location", "Remote / On-site")
                dept = j.get("department", "")
                meta = " · ".join(filter(None, [loc, dept]))
                html_parts.append(
                    f'<li style="margin: 6px 0; line-height: 1.5;">'
                    f'<a href="{j["url"]}" style="color: #DD2476; text-decoration: none; font-weight: 500;">{j["title"]}</a>'
                    f'{"<span style=\"color: #888; font-size: 13px;\"> " + meta + "</span>" if meta else ""}'
                    f'</li>'
                )
        html_parts.append('</ul>')

    html_parts.extend([
        '</div>',
        '<p style="text-align: center; color: #aaa; font-size: 12px; margin-top: 16px;">'
        'Powered by junior-ai-job-scraper · Target: Junior, Trainee & Entry-Level AI/ML roles</p>',
        '</div>',
    ])
    return "\n".join(html_parts)


# ------------------------------------------------------------------ #
#  Main pipeline
# ------------------------------------------------------------------ #
def load_all_target_companies() -> list:
    """Load companies specifically from dedicated ai_companies.json."""
    if not os.path.exists(AI_COMPANIES_FILE):
        logger.info(f"{AI_COMPANIES_FILE} not found. Building it now...")
        import build_ai_companies
        build_ai_companies.main()

    with open(AI_COMPANIES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("scrapable", []) + data.get("custom_ats", [])



def run(dry_run: bool = False):
    """Main Junior AI job pipeline."""
    companies = load_all_target_companies()
    logger.info(f"Loaded {len(companies)} combined target companies for Junior AI scan")

    ats_counts = {}
    for c in companies:
        ats_counts[c["ats"]] = ats_counts.get(c["ats"], 0) + 1
    logger.info(f"ATS distribution: {ats_counts}")

    seen = _load_seen(JUNIOR_AI_SEEN_FILE)
    logger.info(f"Seen store (Junior AI): {len(seen)} entries")

    report = []
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
        new = dedupe_junior_ai(name, jobs, seen)
        if new:
            total_matching += len(new)
            report.append((name, new))
            for job in new:
                logger.info("    JUNIOR AI MATCH: %s — %s", job["title"], job.get("location", ""))

    if not dry_run:
        _save_seen(seen, JUNIOR_AI_SEEN_FILE)
        logger.info(f"Updated Junior AI seen store: {len(seen)} entries")
    else:
        logger.info("[DRY RUN] Junior AI seen store left unchanged")

    logger.info(f"\n{'='*50}")
    logger.info(f"TOTALS: {total_fetched} jobs fetched, {total_matching} new Junior AI matches, {errors} errors")
    logger.info(f"Companies with matches: {len(report)}")

    if report:
        logger.info("\nNew Junior AI jobs found:")
        for company, jobs in report:
            for j in jobs:
                logger.info(f"  - [{company}] {j['title']} ({j.get('location', '')})")

    if not dry_run and report:
        logger.info("\nSending Junior AI job email...")
        send_junior_ai_email(report)
    elif dry_run and report:
        logger.info(f"\n[DRY RUN] Would send email with {len(report)} companies")
    elif not report:
        logger.info("\nNo new matching Junior AI jobs today. No email sent.")

    return report


def classify_only():
    """Show ATS distribution stats for combined companies."""
    companies = load_all_target_companies()
    ats_counts = {}
    for c in companies:
        ats = c["ats"]
        ats_counts[ats] = ats_counts.get(ats, 0) + 1

    print(f"\n{'='*50}")
    print(f"Total target companies (combined): {len(companies)}")
    print(f"\nATS Distribution:")
    for ats, count in sorted(ats_counts.items(), key=lambda x: -x[1]):
        pct = count / len(companies) * 100
        bar = "█" * int(pct / 5)
        print(f"  {ats:20s} {count:4d} ({pct:5.1f}%) {bar}")


def main():
    parser = argparse.ArgumentParser(description="Junior AI & ML Job Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Don't send email")
    parser.add_argument("--build", action="store_true", help="Rebuild ai_companies.json first")
    parser.add_argument("--classify-only", action="store_true", help="Show ATS stats")
    args = parser.parse_args()

    if args.build:
        import build_ai_companies
        build_ai_companies.main()
        print()

    if args.classify_only:
        classify_only()
        return

    run(dry_run=args.dry_run)



if __name__ == "__main__":
    main()

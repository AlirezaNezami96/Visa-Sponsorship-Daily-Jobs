"""CLI entrypoint for remote-job scanner."""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
from typing import List

from job_radar.fetchers.pipeline import fetch_companies
from job_radar.filters.dedupe import _load_seen, _save_seen, dedupe
from job_radar.filters.freshness import filter_fresh_jobs
from job_radar.dedup.store import bulk_mark_sent, is_already_sent, is_available as supabase_available
from job_radar.notifications.email import (
    _send_via_gmail_smtp,
    _send_via_resend,
    _send_via_sendgrid,
)
from job_radar.resume.fetch import fetch_resume_text
from job_radar.resume.matcher import match_resume_batch

logger = logging.getLogger("job_radar.remote")
REMOTE_SEEN_FILE = "seen_remote_jobs.json"
REMOTE_COMPANIES_FILE = "remote_companies.json"


def _build_remote_html(report: list, total_jobs: int) -> str:
    # Import the ATS block renderer from the shared renderers module
    try:
        from job_radar.notifications.renderers import _render_ats_block
    except ImportError:
        def _render_ats_block(rm):  # type: ignore[misc]
            return ""

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
        for j in jobs:
            loc = j.get("location", "Remote")
            dept = j.get("department", "")
            meta = " · ".join(filter(None, [loc, dept]))
            ats_block = _render_ats_block(j.get("resume_match"))
            html_parts.append(
                f'<div style="margin: 8px 0; padding: 10px 12px; background: #F9FAFB; border-radius: 6px; border: 1px solid #E5E7EB;">'
                f'<a href="{j["url"]}" style="color: #11998e; text-decoration: none; font-weight: 600; font-size: 14px;">{j["title"]}</a>'
                f'{"<span style=\"color: #888; font-size: 12px; margin-left: 8px;\"> · " + meta + "</span>" if meta else ""}'
                f'{ats_block}'
                f'<div style="margin-top:8px;text-align:right;">'
                f'<a href="{j["url"]}" target="_blank" style="font-size:12px;color:#fff;background:#11998e;padding:4px 10px;border-radius:4px;text-decoration:none;font-weight:600;">Apply →</a>'
                f'</div>'
                f'</div>'
            )

    html_parts.extend([
        '</div>',
        '<p style="text-align: center; color: #aaa; font-size: 12px; margin-top: 16px;">'
        'Powered by job-radar · Remote Scanner</p>',
        '</div>',
    ])
    return "\n".join(html_parts)


def send_remote_email(report: list):
    if not report:
        logger.info("No new remote jobs found — skipping email.")
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

    logger.info("Remote email sent via %s: %d jobs from %d companies", provider, total_jobs, len(report))


def load_remote_companies() -> list:
    candidates = [
        REMOTE_COMPANIES_FILE,
        os.path.join("data", REMOTE_COMPANIES_FILE),
    ]
    target_path = None
    for c in candidates:
        if os.path.exists(c):
            target_path = c
            break

    if not target_path:
        logger.error("%s not found. Build it first.", REMOTE_COMPANIES_FILE)
        sys.exit(1)

    with open(target_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("scrapable", []) + data.get("custom_ats", [])


def run(dry_run: bool = False):
    companies = load_remote_companies()
    logger.info("Loaded %d remote companies", len(companies))

    seen = _load_seen(REMOTE_SEEN_FILE)
    logger.info("Seen store (remote): %d entries", len(seen))
    logger.info("Supabase dedup: %s", "Connected" if supabase_available() else "Fallback → JSON seen-store")

    # Fetch resume once per run (fail-open)
    resume_text = None
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            from job_radar.config.loader import get_config
            cfg = get_config()
            if cfg.resume_matcher.enabled:
                resume_text = fetch_resume_text(
                    doc_id=cfg.resume.doc_id,
                    access_method=cfg.resume.access_method,
                )
        except Exception as exc:
            logger.warning("Resume fetch failed: %s — skipping ATS scoring", exc)

    report = []
    all_new_jobs = []
    total_fetched = 0
    total_matching = 0
    errors = 0

    # Load freshness config
    try:
        from job_radar.config.loader import get_config
        cfg = get_config()
        max_age_days = cfg.freshness.max_age_days
    except Exception:
        max_age_days = 5

    for i, result in enumerate(fetch_companies(companies)):
        company = result.company
        name = company["name"]
        if result.error:
            errors += 1
            continue

        jobs = result.jobs
        total_fetched += len(jobs)

        # Apply freshness filter per company batch
        jobs = filter_fresh_jobs(jobs, max_age_days=max_age_days)

        new = dedupe(name, jobs, seen)

        # Supabase cross-track dedup
        if supabase_available() and new:
            new = [j for j in new if not is_already_sent(j.get("url", ""))]

        if new:
            total_matching += len(new)
            all_new_jobs.extend(new)
            report.append((name, new))

    # Resume matching for all new remote jobs in one batch
    if resume_text and all_new_jobs:
        logger.info("Running resume matching for %d remote jobs...", len(all_new_jobs))
        try:
            from job_radar.config.loader import get_config
            match_cfg = get_config()
        except Exception:
            match_cfg = None
        match_resume_batch(all_new_jobs, resume_text, config=match_cfg)

    if not dry_run:
        _save_seen(seen, REMOTE_SEEN_FILE)
        logger.info("Updated remote seen store: %d entries", len(seen))
        # Mark sent in Supabase
        if supabase_available() and all_new_jobs:
            bulk_mark_sent(all_new_jobs, track="remote")
    else:
        logger.info("[DRY RUN] Remote seen store and Supabase left unchanged")

    logger.info("TOTALS: %d jobs fetched, %d new remote matches, %d errors", total_fetched, total_matching, errors)

    if not dry_run and report:
        send_remote_email(report)
    elif dry_run and report:
        logger.info("[DRY RUN] Would send email with %d companies", len(report))

    return report


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Remote Job Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Don't send email")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

"""CLI entrypoint for Newly Fund-Raised Companies Scanner."""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import time

from job_radar.fetchers.funding import fetch_all_funding_deals
from job_radar.notifications.email import (
    _send_via_gmail_smtp,
    _send_via_resend,
    _send_via_sendgrid,
)

logger = logging.getLogger("job_radar.funding")
SEEN_FUNDING_FILE = "seen_funding.json"
SEEN_MAX_AGE = 30 * 24 * 60 * 60  # 30 days


def _load_seen_funding() -> dict:
    now = time.time()
    if os.path.exists(SEEN_FUNDING_FILE):
        try:
            with open(SEEN_FUNDING_FILE, "r") as f:
                seen = json.load(f)
        except (json.JSONDecodeError, IOError):
            seen = {}
    else:
        seen = {}

    expired = [k for k, v in seen.items() if now - v.get("t", 0) > SEEN_MAX_AGE]
    for k in expired:
        del seen[k]

    return seen


def _save_seen_funding(seen: dict):
    with open(SEEN_FUNDING_FILE, "w") as f:
        json.dump(seen, f, separators=(",", ":"))


def dedupe_funding(deals: list, seen: dict) -> list:
    new_deals = []
    for d in deals:
        key = d["url"] or d["title"]
        if key in seen:
            continue
        seen[key] = {"t": int(time.time())}
        new_deals.append(d)
    return new_deals


def build_funding_html(deals: list) -> str:
    now_str = datetime.datetime.now().strftime("%b %d, %Y")
    html_parts = [
        '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; max-width: 680px; margin: 0 auto; color: #1a1a1a;">',
        '<div style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 50%, #7c3aed 100%); padding: 24px 28px; border-radius: 12px 12px 0 0;">',
        '  <h1 style="margin: 0; color: white; font-size: 22px;">💰 Newly Funded Companies Digest</h1>',
        f'  <p style="margin: 6px 0 0; color: rgba(255,255,255,0.9); font-size: 14px;">{len(deals)} new funding rounds · Global (Non-US, Non-India) · {now_str}</p>',
        '</div>',
        '<div style="padding: 20px 28px 28px; background: #ffffff; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 12px 12px;">',
    ]

    for d in deals:
        kw_badge = ""
        if d.get("matched_keywords"):
            kw_tags = ", ".join(d["matched_keywords"])
            kw_badge = f'<span style="background: #e0e7ff; color: #3730a3; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-left: 8px;">🎯 {kw_tags}</span>'

        amount_round = f"{d['amount']} ({d['round']})" if d['amount'] != "N/A" else d['round']

        html_parts.append('<div style="margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #f3f4f6;">')
        html_parts.append(f'  <h2 style="margin: 0 0 6px 0; font-size: 17px; color: #111827;">{d["company"]} {kw_badge}</h2>')
        html_parts.append(
            f'  <p style="margin: 0 0 8px 0; font-size: 13px; color: #6b7280;">'
            f'  📍 <strong>{d["region"]}</strong> ({d["source"]}) &nbsp;·&nbsp; 💵 <span style="color: #059669; font-weight: 600;">{amount_round}</span>'
            f'  </p>'
        )
        html_parts.append(
            f'  <p style="margin: 0 0 8px 0; font-size: 14px; color: #374151; line-height: 1.5;">'
            f'  <a href="{d["url"]}" style="color: #2563eb; text-decoration: none; font-weight: 500;">{d["title"]}</a>'
            f'  </p>'
        )
        if d.get("summary") and d["summary"] != d["title"]:
            html_parts.append(f'  <p style="margin: 0; font-size: 13px; color: #4b5563; line-height: 1.4;">{d["summary"]}</p>')
        html_parts.append('</div>')

    html_parts.extend([
        '</div>',
        '<p style="text-align: center; color: #9ca3af; font-size: 12px; margin-top: 16px;">'
        'Powered by job-radar · Funding Scanner</p>',
        '</div>',
    ])
    return "\n".join(html_parts)


def send_funding_email(deals: list):
    if not deals:
        logger.info("No new funding deals found — skipping email.")
        return

    html = build_funding_html(deals)
    subject = f"💰 Newly Funded Startups Digest — {len(deals)} announcements"

    provider = os.environ.get("EMAIL_PROVIDER", "resend").lower()
    if provider == "resend":
        _send_via_resend(subject, html)
    elif provider == "sendgrid":
        _send_via_sendgrid(subject, html)
    elif provider == "gmail":
        _send_via_gmail_smtp(subject, html)
    else:
        raise ValueError(f"Unknown email provider: {provider}")

    logger.info("Funding digest email sent via %s: %d companies", provider, len(deals))


def run(dry_run: bool = False):
    logger.info("Starting Funding Scraper Pipeline (Non-US, Non-India)...")
    deals = fetch_all_funding_deals()

    seen = _load_seen_funding()
    logger.info("Seen funding store: %d entries", len(seen))

    new_deals = dedupe_funding(deals, seen)
    logger.info("New funding deals after deduplication: %d", len(new_deals))

    if not dry_run:
        _save_seen_funding(seen)
        logger.info("Updated seen funding store: %d entries", len(seen))
    else:
        logger.info("[DRY RUN] Funding seen store left unchanged")

    if not dry_run and new_deals:
        send_funding_email(new_deals)
    elif dry_run and new_deals:
        logger.info("[DRY RUN] Would send email with %d funding announcements", len(new_deals))

    return new_deals


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Newly Fund-Raised Companies Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Don't send email")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

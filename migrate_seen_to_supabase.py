"""One-time migration script: seen_*.json → Supabase sent_jobs table.

Run locally BEFORE switching to Supabase-backed dedup in production:

    python migrate_seen_to_supabase.py [--dry-run] [--table sent_jobs]

Idempotent: uses upsert with on_conflict='fingerprint' so re-running is safe.
Requires SUPABASE_URL and SUPABASE_KEY env vars to be set.

Supabase table schema (if not already created):

    CREATE TABLE IF NOT EXISTS sent_jobs (
        id           BIGSERIAL PRIMARY KEY,
        fingerprint  TEXT NOT NULL UNIQUE,
        track        TEXT NOT NULL DEFAULT 'unknown',
        title        TEXT,
        company      TEXT,
        url          TEXT,
        ats_score    INT,
        sent_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE UNIQUE INDEX IF NOT EXISTS sent_jobs_fingerprint_idx ON sent_jobs (fingerprint);
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("migrate")

TRACK_FILES = {
    "visa": "seen_jobs.json",
    "remote": "seen_remote_jobs.json",
    "ai_intern": "seen_junior_ai_jobs.json",
}


def load_seen_file(path: str) -> list[dict]:
    """Load a seen JSON file and return a list of row dicts."""
    if not os.path.exists(path):
        logger.warning("File not found: %s — skipping", path)
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    if isinstance(data, dict):
        # Format: {"fingerprint": {"title": ..., "company": ..., "url": ...}}
        for fp, meta in data.items():
            if isinstance(meta, dict):
                rows.append({
                    "fingerprint": fp,
                    "title": meta.get("title", "")[:255],
                    "company": meta.get("company", "")[:255],
                    "url": meta.get("url", "")[:2048],
                })
            else:
                rows.append({"fingerprint": fp})
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                rows.append({
                    "fingerprint": item.get("fingerprint", str(item)),
                    "title": item.get("title", "")[:255],
                    "company": item.get("company", "")[:255],
                    "url": item.get("url", "")[:2048],
                })
            else:
                rows.append({"fingerprint": str(item)})

    return rows


def migrate(dry_run: bool = False, table_name: str = "sent_jobs") -> None:
    """Run the migration from JSON seen-stores to Supabase."""
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_key = os.environ.get("SUPABASE_KEY", "").strip()

    if not dry_run:
        if not supabase_url or not supabase_key:
            logger.error(
                "SUPABASE_URL and SUPABASE_KEY env vars must be set. "
                "Use --dry-run to preview without connecting."
            )
            sys.exit(1)
        try:
            from supabase import create_client
            client = create_client(supabase_url, supabase_key)
            logger.info("✅ Connected to Supabase (%s)", supabase_url)
        except ImportError:
            logger.error("supabase-py not installed. Run: pip install supabase")
            sys.exit(1)
    else:
        client = None

    total_migrated = 0

    for track, filepath in TRACK_FILES.items():
        rows = load_seen_file(filepath)
        logger.info("Track '%s': %d fingerprints found in %s", track, len(rows), filepath)

        if not rows:
            continue

        # Annotate with track name
        for row in rows:
            row["track"] = track

        total_migrated += len(rows)

        if dry_run:
            logger.info("[DRY RUN] Would upsert %d rows for track '%s'", len(rows), track)
            for r in rows[:3]:
                logger.info("  Sample row: %s", r)
            if len(rows) > 3:
                logger.info("  ... and %d more", len(rows) - 3)
            continue

        # Batch upsert (Supabase has a 1000-row limit per request)
        batch_size = 500
        for batch_start in range(0, len(rows), batch_size):
            batch = rows[batch_start:batch_start + batch_size]
            try:
                client.table(table_name).upsert(batch, on_conflict="fingerprint").execute()
                logger.info("  Upserted batch [%d–%d]", batch_start, batch_start + len(batch))
            except Exception as exc:
                logger.error("  Upsert failed for batch [%d–%d]: %s", batch_start, batch_start + len(batch), exc)

    logger.info("Migration complete. Total fingerprints processed: %d", total_migrated)
    if dry_run:
        logger.info("[DRY RUN] No data was written to Supabase.")


def main():
    parser = argparse.ArgumentParser(description="Migrate seen_*.json → Supabase sent_jobs table")
    parser.add_argument("--dry-run", action="store_true", help="Preview only — do not write to Supabase")
    parser.add_argument("--table", default="sent_jobs", help="Supabase table name (default: sent_jobs)")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run, table_name=args.table)


if __name__ == "__main__":
    main()

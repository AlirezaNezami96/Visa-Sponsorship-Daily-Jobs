#!/usr/bin/env python3
"""Render brand cards for live jobs — visual verification helper (GAP 1).

Usage:
    python scripts/render_cards.py --limit 10 --out build/cards
    python scripts/render_cards.py --limit 5 --no-landmarks

Pulls the newest active jobs from Supabase when configured (SUPABASE_URL +
service key); otherwise falls back to a built-in sample set so the renderer
can always be exercised. Prints the license metadata for every landmark
photo used — unlicensed images must never appear here.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from job_radar.social.card_renderer import CardJob, render_card_png  # noqa: E402
from job_radar.social.landmark import fetch_landmark_photo  # noqa: E402

SAMPLE_JOBS = [
    {"title": "Senior Android Developer", "city": "Barcelona", "country": "Spain", "verified": True, "conf": 90},
    {"title": "Staff Flutter Engineer", "city": "Amsterdam", "country": "Netherlands", "verified": True, "conf": 85},
    {"title": "Backend Engineer (Go)", "city": "Berlin", "country": "Germany", "verified": False, "conf": 72},
    {"title": "Machine Learning Engineer", "city": "Paris", "country": "France", "verified": True, "conf": 95},
    {"title": "DevOps Platform Engineer", "city": "Warsaw", "country": "Poland", "verified": False, "conf": 55},
    {"title": "iOS Engineer — Swift", "city": "Stockholm", "country": "Sweden", "verified": True, "conf": 88},
    {"title": "Data Engineer", "city": "Vienna", "country": "Austria", "verified": False, "conf": 40},
    {"title": "Site Reliability Engineer", "city": "Dublin", "country": "Ireland", "verified": True, "conf": 80},
    {"title": "Full-Stack TypeScript Developer", "city": "Lisbon", "country": "Portugal", "verified": True, "conf": 77},
    {"title": "Kotlin Multiplatform Engineer", "city": "Istanbul", "country": "Türkiye", "verified": False, "conf": 65},
]


def load_live_jobs(limit: int):
    """Newest active jobs from Supabase, or None when not configured."""
    try:
        from job_radar.storage.supabase_client import SupabaseStorageClient

        storage = SupabaseStorageClient()
        if not storage.is_configured or storage._client is None:
            return None
        res = (
            storage._client.table("jobs")
            .select("id,title,city,country,work_mode,visa_sponsorship_verified,visa_sponsorship_confidence")
            .eq("status", "active")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = res.data or []
        return [
            {
                "job_db_id": str(r.get("id")),
                "title": r.get("title") or "Untitled role",
                "city": r.get("city"),
                "country": r.get("country") or "",
                "work_mode": r.get("work_mode"),
                "verified": bool(r.get("visa_sponsorship_verified")),
                "conf": int(r.get("visa_sponsorship_confidence") or 0),
            }
            for r in rows
        ] or None
    except Exception as exc:
        print(f"[render_cards] Supabase unavailable ({exc}); using sample jobs.")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "build" / "cards")
    parser.add_argument("--no-landmarks", action="store_true", help="skip Wikimedia photo sourcing")
    parser.add_argument("--samples", action="store_true", help="force the built-in sample set")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    storage = None
    jobs = None
    if not args.samples:
        jobs = load_live_jobs(args.limit)
    if jobs is None:
        jobs = SAMPLE_JOBS[: args.limit]
        print(f"[render_cards] rendering {len(jobs)} sample cards -> {args.out}")
    else:
        from job_radar.storage.supabase_client import SupabaseStorageClient

        storage = SupabaseStorageClient()
        print(f"[render_cards] rendering {len(jobs)} live-job cards -> {args.out}")

    for i, j in enumerate(jobs):
        card = CardJob(
            title=j["title"],
            country=j.get("country") or "",
            city=j.get("city"),
            work_mode=j.get("work_mode"),
            visa_sponsorship_verified=bool(j.get("verified")),
            visa_sponsorship_confidence=int(j.get("conf") or 0),
        )
        photo = None
        meta = None
        if not args.no_landmarks and card.city:
            client = storage._client if storage and storage.is_configured else _null_client()
            photo, meta = fetch_landmark_photo(client, card.city, card.country, storage=storage)
        png = render_card_png(card, photo)
        name = j.get("job_db_id") or f"card-{i + 1:02d}"
        path = args.out / f"{name}.png"
        path.write_bytes(png)
        lic = f"license={meta['license']}" if meta else "fallback-background"
        print(f"  [{i + 1:02d}] {card.title[:44]:44s} {card.city or 'remote':12s} {lic}")

    print(f"[render_cards] done: {len(jobs)} cards in {args.out}")
    return 0


def _null_client():
    class _NullClient:
        def table(self, name):
            raise RuntimeError("no db")

    return _NullClient()


if __name__ == "__main__":
    raise SystemExit(main())

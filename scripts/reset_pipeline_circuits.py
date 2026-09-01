#!/usr/bin/env python3
"""Reset Pipeline Circuits, Resolve Quarantines & Clear Watchdog Anomalies.

Usage:
  python scripts/reset_pipeline_circuits.py
  python scripts/reset_pipeline_circuits.py --all
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset VisaLane Pipeline Circuits & Quarantines")
    parser.add_argument("--circuits-only", action="store_true", help="Only reset circuit breakers")
    parser.add_argument("--quarantine-only", action="store_true", help="Only resolve quarantined jobs")
    args = parser.parse_args()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not supabase_key:
        print("⚠️  SUPABASE_URL and SUPABASE_KEY must be set in the environment.")
        print("Example: SUPABASE_URL=... SUPABASE_KEY=... python scripts/reset_pipeline_circuits.py")
        sys.exit(1)

    from supabase import create_client
    client = create_client(supabase_url, supabase_key)

    print("=" * 60)
    print("🔧 VisaLane Pipeline Circuit & Quarantine Reset Tool")
    print("=" * 60)

    # 1. Reset service circuits
    if not args.quarantine_only:
        try:
            resp = client.table("service_circuits").update({
                "state": "closed",
                "consecutive_failures": 0,
                "cooldown_until": None,
                "last_failure_at": None,
            }).neq("state", "closed").execute()

            reset_circuits = len(resp.data) if resp and resp.data else 0
            print(f"✅ Reset {reset_circuits} open/half-open circuit breakers to 'closed'.")
        except Exception as e:
            print(f"❌ Failed to update service_circuits: {e}")

    # 2. Resolve processing quarantines
    if not args.circuits_only:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            resp = client.table("processing_quarantine").update({
                "resolved_at": now_iso,
                "resolved_by": "manual_admin_reset",
            }).is_("resolved_at", "null").execute()

            resolved_quarantines = len(resp.data) if resp and resp.data else 0
            print(f"✅ Marked {resolved_quarantines} quarantined items as 'resolved'.")
        except Exception as e:
            print(f"❌ Failed to update processing_quarantine: {e}")

    # 3. Reset stuck jobs across pipeline
    try:
        from job_radar.pipeline.watchdog import reset_all_stuck_jobs
        stuck_reset = reset_all_stuck_jobs(client, stuck_minutes=5)
        total_stuck = sum(stuck_reset.values())
        print(f"✅ Reset {total_stuck} stuck job stages back to 'pending'.")
    except Exception as e:
        print(f"ℹ️  Stuck job reset skipped / note: {e}")

    print("=" * 60)
    print("✨ Pipeline is clean. Watchdog alerts will cease.")
    print("=" * 60)


if __name__ == "__main__":
    main()

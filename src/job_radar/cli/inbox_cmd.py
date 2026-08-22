"""
src/job_radar/cli/inbox_cmd.py

CLI command to interact with the Job OS CRM Inbox.
Usage:
  python -m job_radar.cli.inbox_cmd list [--status STATUS] [--limit N]
  python -m job_radar.cli.inbox_cmd set <URL_OR_ID> --status <STATUS> [--notes NOTES]
  python -m job_radar.cli.inbox_cmd due
"""
from __future__ import annotations

import argparse
import sys
from job_radar.crm.db import get_due_followups, list_crm_jobs, update_job_status
from job_radar.crm.models import JobStatus


def main() -> None:
    parser = argparse.ArgumentParser(prog="job-os inbox", description="Manage your Job OS application CRM inbox.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    list_p = subparsers.add_parser("list", help="List jobs in the CRM.")
    list_p.add_argument("--status", default=None, help="Filter by status (e.g. new, applying, applied, interview)")
    list_p.add_argument("--limit", type=int, default=20, help="Maximum number of jobs to list.")

    # set
    set_p = subparsers.add_parser("set", help="Update the status of a job.")
    set_p.add_argument("target", help="Job ID or URL")
    set_p.add_argument("--status", required=True, help="New status (e.g. applied, interview, offer, rejected, skipped)")
    set_p.add_argument("--notes", default=None, help="Optional notes on this status transition.")

    # due
    subparsers.add_parser("due", help="Show applications due for a 3-day follow-up bump.")

    args = parser.parse_args()

    if args.command == "list":
        jobs = list_crm_jobs(status=args.status, limit=args.limit)
        if not jobs:
            print(f"No jobs found in CRM (filter: status={args.status}).")
            return

        print(f"\n{'ID':<5} {'Score':<7} {'Status':<11} {'Company':<20} {'Title':<35} {'Visa'}")
        print("-" * 95)
        for j in jobs:
            score = f"{j.composite:.1f}" if j.composite else "—"
            v_conf = j.visa_confidence or "—"
            print(f"{j.id or 0:<5} {score:<7} {j.status.value:<11} {j.company[:18]:<20} {j.title[:33]:<35} {v_conf}")
        print()

    elif args.command == "set":
        target = int(args.target) if args.target.isdigit() else args.target
        updated = update_job_status(target, status=args.status, notes=args.notes)
        if updated:
            print(f"✅ Updated Job #{updated.id} ({updated.company} - {updated.title}) -> {updated.status.value}")
            if updated.next_action:
                print(f"👉 Next Action: {updated.next_action}")
        else:
            print(f"❌ Job not found for target: {args.target}")
            sys.exit(1)

    elif args.command == "due":
        due_jobs = get_due_followups()
        if not due_jobs:
            print("✨ No applications currently due for follow-up.")
            return

        print(f"\n⏰ {len(due_jobs)} Applications Due for Follow-up:")
        print("-" * 80)
        for j in due_jobs:
            print(f"• #{j.id} {j.company} — {j.title}")
            print(f"  URL: {j.url}")
            print(f"  Suggested Action: {j.next_action or 'Send 3-line bump'}\n")


if __name__ == "__main__":
    main()

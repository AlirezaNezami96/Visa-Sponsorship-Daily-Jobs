"""CLI: send a worker run alert email (GAP 5 failure alerting).

Used by GitHub Actions workflows to email the owner when a run fails:

    job-radar-run-alert --workflow db-backup --status failed \
        --error "pg_dump exited 1" --stat dumped=0

Reads EMAIL_TO / RESEND_API_KEY (or SENDGRID/GMAIL) like the existing
run-alert path; exits 0 when no provider is configured so alerting never
breaks a workflow cleanup step.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any


def _stat_pairs(pairs: list[str]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if key:
            stats[key.strip()] = value.strip()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job-radar-run-alert", description="Send a worker run alert email.")
    parser.add_argument("--workflow", required=True, help="Workflow/job name shown in the alert")
    parser.add_argument("--status", default="failed", help="Run status (failed, completed, timed_out, ...)")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local-run"))
    parser.add_argument("--error", default=None, help="Short error summary")
    parser.add_argument("--stat", action="append", default=[], help="key=value stat, repeatable")
    parser.add_argument("--run-url", default=None)
    args = parser.parse_args(argv)

    run_url = args.run_url
    if not run_url and os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_REPOSITORY") and os.environ.get("GITHUB_RUN_ID"):
        run_url = (
            f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
            f"/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        )

    stats = _stat_pairs(args.stat)
    stats.setdefault("workflow", args.workflow)

    from job_radar.notifications.email import send_worker_run_alert

    sent = send_worker_run_alert(
        run_id=str(args.run_id),
        status=args.status,
        stats=stats,
        error_message=args.error,
        run_url=run_url,
    )
    if sent:
        print(f"run alert sent ({args.workflow}, status={args.status})")
    else:
        print(f"run alert skipped — no email provider configured ({args.workflow})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

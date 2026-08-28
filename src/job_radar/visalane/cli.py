"""CLI entrypoint for VisaLane post-scrape processing.

Usage:
  job-radar-visalane dispatch [--alerts] [--social] [--enrichment] [--limit N]

Default: alerts + social. Enrichment is opt-in (it calls external services).
"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="job-radar-visalane", description="VisaLane backend stage runner")
    sub = parser.add_subparsers(dest="command", required=True)

    disp = sub.add_parser("dispatch", help="Process unprocessed jobs from the database")
    disp.add_argument("--alerts", action="store_true", help="Enable alert matching/dispatch")
    disp.add_argument("--social", action="store_true", help="Enable social queue staging")
    disp.add_argument("--enrichment", action="store_true", help="Enable contact enrichment")
    disp.add_argument("--limit", type=int, default=200, help="Max jobs per run (default 200)")

    args = parser.parse_args(argv)

    if args.command == "dispatch":
        # Default to alerts+social when no explicit stage flags are passed.
        none_selected = not (args.alerts or args.social or args.enrichment)
        from job_radar.visalane.stages import dispatch_pending

        stats = dispatch_pending(
            do_alerts=args.alerts or none_selected,
            do_social=args.social or none_selected,
            do_enrichment=args.enrichment,
            limit=args.limit,
        )
        print(stats)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

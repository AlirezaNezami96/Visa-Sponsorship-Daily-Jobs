"""CLI Command for Executing the LinkedIn Repurposing Pipeline."""
from __future__ import annotations

import argparse
import logging
import os
import sys

from job_radar.repurpose.orchestrator import RepurposeOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("republish_post")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="job-radar-republish",
        description="Executes the LinkedIn source post repurposing and publishing pipeline.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the entire pipeline (selection, media processing, Gemini adaptation) without publishing to LinkedIn or modifying database.",
    )
    parser.add_argument(
        "--worker-id",
        help="Custom worker execution identifier for concurrency traceability.",
    )
    parser.add_argument(
        "--post-id",
        help="Force process a specific source post database ID.",
    )

    args = parser.parse_args()

    orchestrator = RepurposeOrchestrator()
    result = orchestrator.run(
        worker_id=args.worker_id,
        dry_run=args.dry_run,
        force_post_id=args.post_id,
    )

    if result.status == "exhausted":
        logger.info("Pipeline completed: %s", result.skipped_reason)
        sys.exit(0)

    if result.success:
        logger.info("Pipeline succeeded! Published LinkedIn URN: %s (URL: %s)", result.linkedin_post_urn, result.linkedin_post_url)
        sys.exit(0)
    else:
        logger.error("Pipeline failed: %s", result.error_message)
        sys.exit(1)


if __name__ == "__main__":
    main()

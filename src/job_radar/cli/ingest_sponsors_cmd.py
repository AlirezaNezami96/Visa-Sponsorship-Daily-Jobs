"""
src/job_radar/cli/ingest_sponsors_cmd.py

CLI command to ingest and refresh official government sponsor registers (UK GOV.UK, etc.).
"""
from __future__ import annotations

import argparse
import logging
import sys

from job_radar.visa.ingest_uk import ingest_uk_sponsors

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest official government visa sponsor registers.")
    parser.add_argument("--uk-url", default=None, help="Custom URL or path for UK sponsor CSV")
    args = parser.parse_args()

    logger.info("Starting weekly visa sponsor ingestion...")
    count = ingest_uk_sponsors(csv_url_or_path=args.uk_url)
    logger.info("Ingestion completed. Total records processed: %d", count)


if __name__ == "__main__":
    main()

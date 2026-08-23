"""CLI Command for Importing Source Posts Dataset into Supabase."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from job_radar.repurpose.importer import SourcePostImporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("import_posts")


def main() -> None:
    from job_radar.storage.supabase_client import _load_dotenv_if_needed
    _load_dotenv_if_needed()

    parser = argparse.ArgumentParser(
        prog="job-radar-import-posts",
        description="Imports and deduplicates source LinkedIn posts from JSON into Supabase.",
    )
    parser.add_argument(
        "--file",
        "-f",
        default=os.environ.get("SOURCE_POSTS_JSON_PATH", "data/source_posts.json"),
        help="Path to source posts JSON file (default: data/source_posts.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without modifying Supabase database.",
    )

    args = parser.parse_args()
    target_file = Path(args.file)

    if not target_file.exists():
        example_fallback = Path("data/source_posts.example.json")
        if example_fallback.exists() and args.file == "data/source_posts.json":
            logger.info("Default file 'data/source_posts.json' not found. Using 'data/source_posts.example.json'.")
            target_file = example_fallback
        else:
            logger.error("Source file not found: %s", target_file)
            sys.exit(1)

    importer = SourcePostImporter()
    logger.info("Starting source posts import from: %s (dry_run=%s)", target_file, args.dry_run)
    summary = importer.import_dataset(target_file, dry_run=args.dry_run)

    print(summary)
    if summary.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()

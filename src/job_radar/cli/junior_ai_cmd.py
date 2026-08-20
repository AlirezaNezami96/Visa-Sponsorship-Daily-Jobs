"""CLI entrypoint for Junior AI & ML Job Scanner."""
from __future__ import annotations

import argparse
import collections
import logging
from typing import List, Tuple

from job_radar.fetchers.jobboards import (
    DEFAULT_CONFIG_PATH,
    fetch_all_jobboard_jobs,
    load_config,
)
from job_radar.filters.dedupe import (
    _load_seen,
    _save_seen,
    dedupe_junior_ai_multi,
)
from job_radar.notifications.email import send_junior_ai_email

logger = logging.getLogger("job_radar.junior_ai")
JUNIOR_AI_SEEN_FILE = "seen_junior_ai_jobs.json"


def run(
    dry_run: bool = False,
    countries: list = None,
    queries: list = None,
    max_results: int = None,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> List[Tuple[str, List[dict]]]:
    cfg = load_config(config_path)
    target_countries = countries or cfg.get("active_countries", ["USA", "UK", "Canada", "Germany", "Netherlands", "Ireland"])
    target_queries = queries or cfg.get("search_queries", ["Junior AI Engineer"])

    logger.info("Initializing Junior AI Job-Board Scanner")
    logger.info("Target Countries: %s", ", ".join(target_countries))
    logger.info("Search Queries: %s", ", ".join(target_queries))

    seen = _load_seen(JUNIOR_AI_SEEN_FILE)
    logger.info("Loaded Junior AI seen store: %d entries", len(seen))

    fetched_jobs = fetch_all_jobboard_jobs(
        countries=target_countries,
        queries=target_queries,
        config_path=config_path,
        max_results_override=max_results,
    )
    logger.info("Fetched %d raw candidate jobs across job boards", len(fetched_jobs))

    new_matching_jobs = dedupe_junior_ai_multi(fetched_jobs, seen)
    logger.info("Filtered %d new matching Junior AI jobs", len(new_matching_jobs))

    grouped = collections.defaultdict(list)
    for job in new_matching_jobs:
        company_name = job.get("company", "Indeed")
        grouped[company_name].append(job)

    report = sorted(grouped.items(), key=lambda x: x[0].lower())

    if not dry_run:
        _save_seen(seen, JUNIOR_AI_SEEN_FILE)
        logger.info("Updated Junior AI seen store: %d total entries saved to %s", len(seen), JUNIOR_AI_SEEN_FILE)
    else:
        logger.info("[DRY RUN] Junior AI seen store left unchanged")

    logger.info("TOTALS: %d jobs fetched, %d new Junior AI matches across %d companies", len(fetched_jobs), len(new_matching_jobs), len(report))

    if not dry_run and report:
        send_junior_ai_email(report)
    elif dry_run and report:
        logger.info("[DRY RUN] Would send email digest with %d companies (%d jobs)", len(report), len(new_matching_jobs))

    return report


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Junior AI & ML Job-Board Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Don't send email or persist state changes")
    parser.add_argument("--countries", type=str, default=None, help="Comma-separated country list (e.g. USA,UK,Canada)")
    parser.add_argument("--queries", type=str, default=None, help="Comma-separated queries list")
    parser.add_argument("--max-results", type=int, default=None, help="Max results per search query per country")
    parser.add_argument("--config", type=str, default=DEFAULT_CONFIG_PATH, help="Path to jobboard_config.json")
    args = parser.parse_args()

    countries = [c.strip() for c in args.countries.split(",")] if args.countries else None
    queries = [q.strip() for q in args.queries.split(",")] if args.queries else None

    run(
        dry_run=args.dry_run,
        countries=countries,
        queries=queries,
        max_results=args.max_results,
        config_path=args.config,
    )


if __name__ == "__main__":
    main()

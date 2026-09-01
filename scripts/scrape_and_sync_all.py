#!/usr/bin/env python3
"""
Scrape all registered sources, evaluate visa sponsorship against the 276k sponsor database,
and sync qualified jobs directly into the Supabase database.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add project root and src to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scraper_sync")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from job_radar.models.config import JobSearchConfig
from job_radar.pipeline.orchestrator import run_pipeline
from job_radar.pipeline.sink import SupabaseJobSink
from job_radar.visa.db import ensure_db_extracted


async def main():
    logger.info("=" * 60)
    logger.info("🚀 Starting Live Multi-Source Scraper & Supabase Sync")
    logger.info("=" * 60)

    # Ensure the 276k sponsors database is extracted and ready
    ensure_db_extracted()

    config = JobSearchConfig(
        keywords=[],  # All roles
        countries=[],  # Worldwide
        visa_sponsorship_only=True,
        include_unknown_visa=False,
        min_visa_confidence="unknown",  # Captures stated_in_jd, on_sponsor_list, historical_filings, likely
        enable_overseas_sources=True,
        enable_ai_classification=False,  # Keep cost $0 for automated scheduled scraping
        max_results=500,
        concurrency=8,
        timeout_per_source_secs=35,
        max_companies_per_ats=50,
    )

    sink = SupabaseJobSink(
        source_name="scraper_pipeline",
        do_alerts=True,
        do_social=True,
    )

    result = await run_pipeline(config, sink)
    await sink.close()

    logger.info("=" * 60)
    logger.info("🏁 Live Scraping Complete!")
    logger.info("Total fetched: %s", result.stats.get("totalFetched"))
    logger.info("Total visa qualified: %s", result.stats.get("visaPassedJobs"))
    logger.info("Total matched to registries: %s", result.stats.get("visaEnrichedJobs"))
    logger.info("Total emitted: %s", result.stats.get("totalEmitted"))
    logger.info("Supabase sync stats: %s", getattr(sink, "sync_stats", {}))
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
scripts/dry_run_scrapers.py

Executes a local dry-run scrape through the full real-world pipeline without
saving any records to Supabase or any external database.

Uses InMemoryJobSink to keep all output in memory for evaluation and statistics.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Setup paths
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root))

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.pipeline.orchestrator import run_pipeline
from job_radar.pipeline.sink import InMemoryJobSink
from job_radar.sources.registry import SOURCE_REGISTRY

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("dry_run_scrapers")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


async def execute_dry_run(
    sources: List[str] | None = None,
    max_per_source: int = 50,
    max_results: int = 2000,
    visa_sponsorship_only: bool = False,
) -> None:
    """Run full pipeline locally into InMemoryJobSink (ZERO DB writes)."""
    t0 = time.time()
    
    print("\n" + "=" * 80)
    print("🚀 VISALANE LOCAL DRY-RUN PIPELINE (NO SUPABASE DB WRITES)")
    print("=" * 80)
    print(f"Time: {datetime.datetime.now().isoformat()}")
    print(f"Available Sources in Registry: {len(SOURCE_REGISTRY)}")
    
    # Configure JobSearchConfig
    config = JobSearchConfig(
        sources=sources or [],  # empty list means all registered sources in registry
        max_per_source=max_per_source,
        max_results=max_results,
        max_runtime_secs=300,
        enable_ai_classification=False,  # Use deterministic ISCO & Additive Visa engine
        include_description=True,
        include_raw_metadata=False,
        visa_sponsorship_only=visa_sponsorship_only,
        include_unknown_visa=True,  # Allow all tiers through to inspect full scraper output
        posted_within_days=60,
    )
    
    sink = InMemoryJobSink()
    
    print(f"Target Sources: {config.sources or 'ALL 26 REGISTERED SOURCES'}")
    print(f"Max Per Source: {config.max_per_source}")
    print(f"Sink: InMemoryJobSink (Guaranteed 0 DB writes)")
    print("-" * 80)
    print("Fetching and executing pipeline...")

    # Run the orchestrator pipeline
    result = await run_pipeline(config, sink)
    elapsed = time.time() - t0

    # Gather stats
    jobs: List[Job] = sink.jobs
    stats = result.stats

    print("\n" + "=" * 80)
    print("📊 PIPELINE EXECUTION SUMMARY")
    print("=" * 80)
    print(f"Total Execution Time      : {elapsed:.2f} seconds")
    print(f"Total Raw Jobs Fetched    : {stats.get('totalFetched', 0)}")
    print(f"Passed Initial Filter     : {stats.get('totalFiltered', 0)}")
    print(f"Unique Surviving Jobs     : {stats.get('uniqueSurvivingJobs', 0)}")
    print(f"Simhash Duplicates Dropped: {stats.get('simhashDuplicates', 0)}")
    print(f"Visa Evaluated & Emitted  : {len(jobs)}")
    print(f"Successful Source Adapters: {len(result.successful_sources)}")
    print(f"Failed Source Adapters    : {len(result.failed_sources)}")

    if result.successful_sources:
        print("\n✅ Top Performing Source Adapters:")
        # Tally jobs by source
        source_counts: Dict[str, int] = {}
        for j in jobs:
            src = j.source or "unknown"
            source_counts[src] = source_counts.get(src, 0) + 1
        for src, cnt in sorted(source_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  • {src:<22}: {cnt:>4} jobs emitted")

    # Visa Confidence Tier Breakdown
    tier_counts: Dict[str, int] = {}
    signal_counts: Dict[str, int] = {}
    country_counts: Dict[str, int] = {}
    verified_sponsors: List[Job] = []

    for j in jobs:
        # Confidence tier
        tier = getattr(j, "visa_tier", None) or "UNKNOWN"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        
        # Visa signal
        sig = getattr(j, "visa_signal", None) or getattr(j, "visa_confidence", None) or "unknown"
        signal_counts[str(sig)] = signal_counts.get(str(sig), 0) + 1

        # Country
        c = j.country or (j.locations[0] if j.locations else "Unknown")
        country_counts[c] = country_counts.get(c, 0) + 1

        # Verified / High list
        if str(tier).upper() in ("VERIFIED", "HIGH") or str(sig).lower() in ("verified", "on_sponsor_list", "stated_in_jd", "known_sponsor"):
            verified_sponsors.append(j)

    print("\n" + "=" * 80)
    print("🛡️  VISA SPONSORSHIP BREAKDOWN (Additive Intelligence Engine)")
    print("=" * 80)
    for t, cnt in sorted(tier_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  • {t:<25}: {cnt:>4} jobs")

    print("\n🌍 Top Geographic Locations:")
    for c, cnt in sorted(country_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  • {c:<25}: {cnt:>4} jobs")

    print("\n" + "=" * 80)
    print(f"🌟 SAMPLE HIGH-CONFIDENCE / VERIFIED SPONSOR JOBS ({min(5, len(verified_sponsors))} of {len(verified_sponsors)})")
    print("=" * 80)
    
    samples = verified_sponsors[:5] if verified_sponsors else jobs[:5]
    for idx, j in enumerate(samples, 1):
        print(f"\n[{idx}] {j.title}")
        print(f"    Company    : {j.company}")
        print(f"    Location   : {j.location or j.country or 'Global'}")
        print(f"    Source     : {j.source}")
        print(f"    Visa Tier  : {getattr(j, 'visa_tier', 'N/A')}")
        print(f"    Visa Score : {getattr(j, 'visa_score', 'N/A')}")
        print(f"    Apply URL  : {j.apply_url or j.url}")
        if getattr(j, "visa_explanation", None):
            print(f"    Explanation: {j.visa_explanation}")
        elif getattr(j, "visa_notes", None):
            print(f"    Notes      : {j.visa_notes}")

    print("\n" + "=" * 80)
    print(f"🏁 DRY RUN COMPLETED — {len(jobs)} jobs evaluated in-memory with 0 database writes.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    sources_arg = None
    if len(sys.argv) > 1:
        sources_arg = sys.argv[1].split(",")
    asyncio.run(execute_dry_run(sources=sources_arg, max_per_source=30, max_results=1000))

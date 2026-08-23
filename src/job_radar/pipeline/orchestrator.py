"""Shared pipeline orchestrator with bounded concurrency and error isolation."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.pipeline.classify import classify_jobs_stage
from job_radar.pipeline.dedupe import deduplicate_jobs
from job_radar.pipeline.filter import filter_jobs
from job_radar.pipeline.scoring import score_and_rank_jobs
from job_radar.pipeline.sink import JobSink
from job_radar.pipeline.visa import evaluate_and_filter_visa
from job_radar.sources.base import SourceAdapter
from job_radar.sources.registry import get_enabled_sources

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Detailed result and operational stats from a pipeline run."""
    jobs: List[Job] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    successful_sources: List[str] = field(default_factory=list)
    failed_sources: List[Dict[str, str]] = field(default_factory=list)


async def fetch_all_sources(config: JobSearchConfig) -> Tuple[List[Job], List[str], List[Dict[str, str]]]:
    """
    Fetch from all enabled sources concurrently with bounded concurrency and error isolation.
    Guarantees that one source failure will never terminate the overall run.
    """
    adapters = get_enabled_sources(config)
    semaphore = asyncio.Semaphore(config.concurrency or 5)

    successful_sources: List[str] = []
    failed_sources: List[Dict[str, str]] = []
    all_raw_jobs: List[Job] = []

    async def _fetch_single(adapter: SourceAdapter) -> Tuple[str, List[Job], Optional[str]]:
        async with semaphore:
            try:
                timeout = config.timeout_per_source_secs or 30
                jobs = await asyncio.wait_for(adapter.fetch(config), timeout=timeout)
                return (adapter.name, jobs, None)
            except asyncio.TimeoutError:
                err_msg = f"Timeout after {config.timeout_per_source_secs}s"
                logger.warning("Source '%s' timed out", adapter.name)
                return (adapter.name, [], err_msg)
            except Exception as e:
                err_msg = str(e)
                logger.warning("Source '%s' encountered error: %s", adapter.name, e)
                return (adapter.name, [], err_msg)

    tasks = [_fetch_single(a) for a in adapters]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    for src_name, jobs, error in results:
        if error:
            failed_sources.append({"name": src_name, "error": error})
        else:
            successful_sources.append(src_name)
            all_raw_jobs.extend(jobs)

    return all_raw_jobs, successful_sources, failed_sources


async def run_pipeline(
    config: JobSearchConfig,
    sink: JobSink,
) -> PipelineResult:
    """
    THE shared job processing pipeline orchestrator.
    Used identically by personal workflows and the Apify Actor.

    Execution Order:
    1. Fetch from all sources concurrently (with error isolation)
    2. Freshness and keyword/location/seniority filter
    3. Within-run deduplication (fingerprint-based)
    4. Visa registry matching (deterministic, free, on all surviving jobs)
    5. AI relevance classification (optional, budget-limited, post-dedup)
    6. Composite scoring and ranking
    7. Slice to max_results limit
    8. Emit final jobs and stats to sink
    """
    t_start = time.perf_counter()
    logger.info("=" * 60)
    logger.info("🚀 Starting Shared Job Radar Pipeline")
    logger.info("Sources requested: %s", config.sources or "All registered")
    logger.info("AI classification: %s", "Enabled" if config.enable_ai_classification else "Disabled")
    logger.info("=" * 60)

    # 1. Concurrently fetch all sources with error isolation
    raw_jobs, successful_sources, failed_sources = await fetch_all_sources(config)
    total_fetched = len(raw_jobs)
    logger.info("Fetch complete: %d raw jobs fetched (%d successful sources, %d failed)", total_fetched, len(successful_sources), len(failed_sources))

    # 2. Filter (freshness, keywords, location, seniority, remote)
    filtered_jobs = filter_jobs(raw_jobs, config)
    total_filtered = len(filtered_jobs)
    logger.info("Filter complete: %d jobs passed initial criteria", total_filtered)

    # 3. Within-run deduplication
    if config.deduplicate_within_run:
        deduped_jobs, duplicate_count = deduplicate_jobs(filtered_jobs)
    else:
        deduped_jobs, duplicate_count = filtered_jobs, 0
    total_deduped = len(deduped_jobs)

    # 4. Visa Intelligence and registry matching (Free, deterministic)
    visa_passed_jobs, visa_enriched_count = evaluate_and_filter_visa(deduped_jobs, config)
    total_visa_passed = len(visa_passed_jobs)
    logger.info("Visa stage complete: %d passed, %d matched to official sponsor registries", total_visa_passed, visa_enriched_count)

    # 5. Preliminary Ranking & AI Candidate Slicing (FIX 1: Protect AI cost budget)
    preliminary_ranked = score_and_rank_jobs(visa_passed_jobs, config)
    if config.enable_ai_classification and config.max_results:
        ai_candidate_limit = config.max_results + 50
        candidates_for_ai = preliminary_ranked[:ai_candidate_limit]
        logger.info(
            "AI Pre-Filtering: Sliced candidate pool from %d to top %d jobs for LLM classification",
            len(preliminary_ranked),
            len(candidates_for_ai),
        )
    else:
        candidates_for_ai = preliminary_ranked

    # 6. AI Classification (Optional, budget-limited, run ONLY on top candidate pool)
    ai_passed_jobs, ai_classified_count = await classify_jobs_stage(candidates_for_ai, config)
    total_ai_passed = len(ai_passed_jobs)

    # 7. Final Composite scoring, re-ranking, and truncation to maxResults
    ranked_jobs = score_and_rank_jobs(ai_passed_jobs, config)
    final_jobs = ranked_jobs[: config.max_results] if config.max_results else ranked_jobs
    total_emitted = len(final_jobs)

    duration_secs = round(time.perf_counter() - t_start, 2)

    stats: Dict[str, Any] = {
        "totalFetched": total_fetched,
        "totalFiltered": total_filtered,
        "totalDeduplicated": duplicate_count,
        "uniqueSurvivingJobs": total_deduped,
        "visaPassedJobs": total_visa_passed,
        "visaEnrichedJobs": visa_enriched_count,
        "aiClassifiedJobs": ai_classified_count,
        "totalEmitted": total_emitted,
        "successfulSources": successful_sources,
        "failedSources": failed_sources,
        "durationSeconds": duration_secs,
    }

    # 8. Emit to sink (sink.close is owned by the caller/wrapper)
    await sink.emit(final_jobs)
    await sink.emit_stats(stats)

    logger.info("🎯 Pipeline finished in %.2fs: %d jobs emitted to sink", duration_secs, total_emitted)
    return PipelineResult(
        jobs=final_jobs,
        stats=stats,
        successful_sources=successful_sources,
        failed_sources=failed_sources,
    )

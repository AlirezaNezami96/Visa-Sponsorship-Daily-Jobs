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
from job_radar.pipeline.simhash import simhash_deduplicate
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
                timeout = getattr(adapter, "fetch_timeout_secs", None) or config.timeout_per_source_secs or 30
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


def _is_overseas(job: Job) -> bool:
    return bool(getattr(job, "metadata", None) and job.metadata.get("overseas"))


def _ensure_overseas_slots(
    ranked_jobs: List[Job],
    config: JobSearchConfig,
) -> Tuple[List[Job], int, int]:
    """Slice ranked jobs to maxResults, guaranteeing overseas representation.

    Overseas records rank below registry-enriched baseline jobs on composite
    score, so a plain top-N slice can emit zero overseas records — silently
    disabling the expansion (and its `overseas-job` PPE event). When the pack
    is enabled, reserve up to `overseas_min_results` slots for the best
    overseas jobs and fill the rest with the best remaining jobs.

    Returns (final_jobs, overseas_emitted, overseas_guaranteed).
    `overseas_guaranteed` counts overseas jobs pulled in beyond what a plain
    top-N slice would have emitted naturally.
    """
    max_results = int(config.max_results or 0)
    if max_results <= 0:
        emitted = sum(1 for j in ranked_jobs if _is_overseas(j))
        return ranked_jobs, emitted, 0

    min_overseas = int(getattr(config, "overseas_min_results", 0) or 0)
    if not getattr(config, "enable_overseas_sources", False) or min_overseas <= 0:
        final_jobs = ranked_jobs[:max_results]
        emitted = sum(1 for j in final_jobs if _is_overseas(j))
        return final_jobs, emitted, 0

    natural_overseas = sum(1 for j in ranked_jobs[:max_results] if _is_overseas(j))

    target = min(min_overseas, max_results)
    overseas_pool = [j for j in ranked_jobs if _is_overseas(j)]
    overseas_pick = overseas_pool[:target]
    picked_ids = {id(j) for j in overseas_pick}
    fill_pool = [j for j in ranked_jobs if id(j) not in picked_ids]
    final_jobs = fill_pool[: max_results - len(overseas_pick)] + overseas_pick
    final_jobs = score_and_rank_jobs(final_jobs, config)

    emitted = len(overseas_pick)
    guaranteed = max(0, emitted - natural_overseas)
    if guaranteed:
        logger.info(
            "overseas: slot guarantee pulled in %d overseas jobs (emitted %d of target %d)",
            guaranteed, emitted, target,
        )
    return final_jobs, emitted, guaranteed


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

    # 3b. SimHash near-duplicate dedup (overseas copy-pasted JDs). Runs only
    # when overseas sources are enabled and the SimHash stage is on.
    # Reports 0 when the stage is off.
    simhash_dup_count = 0
    if getattr(config, "enable_overseas_sources", False) and getattr(config, "overseas_simhash_dedup", False):
        deduped_jobs, simhash_dup_count = simhash_deduplicate(deduped_jobs, config)
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

    # 6. Check budget and spending limits before burning LLM tokens (FIX 4: Prevent LLM Money Leak)
    skip_ai = False
    is_limit_reached_fn = getattr(sink, "is_limit_reached", None)
    if getattr(sink, "limit_reached", False) or (callable(is_limit_reached_fn) and is_limit_reached_fn()):
        logger.warning("User spending limit reached before AI stage. Skipping AI classification.")
        skip_ai = True

    if config.enable_ai_classification and not skip_ai:
        ai_passed_jobs, ai_classified_count = await classify_jobs_stage(candidates_for_ai, config)
    else:
        ai_passed_jobs, ai_classified_count = candidates_for_ai, 0
    total_ai_passed = len(ai_passed_jobs)

    # 7. Final Composite scoring, re-ranking, and truncation to maxResults
    ranked_jobs = score_and_rank_jobs(ai_passed_jobs, config)
    final_jobs, overseas_emitted, overseas_guaranteed = _ensure_overseas_slots(ranked_jobs, config)
    total_emitted = len(final_jobs)

    duration_secs = round(time.perf_counter() - t_start, 2)

    stats: Dict[str, Any] = {
        "totalFetched": total_fetched,
        "totalFiltered": total_filtered,
        "totalDeduplicated": duplicate_count,
        "uniqueSurvivingJobs": total_deduped,
        "simhashDuplicates": simhash_dup_count,
        "visaPassedJobs": total_visa_passed,
        "visaEnrichedJobs": visa_enriched_count,
        "aiClassifiedJobs": ai_classified_count,
        "totalEmitted": total_emitted,
        "successfulSources": successful_sources,
        "failedSources": failed_sources,
        "durationSeconds": duration_secs,
    }
    # Overseas-specific stats are only present when the pack is enabled, so
    # flag-off runs keep a byte-identical stats key set.
    if getattr(config, "enable_overseas_sources", False):
        stats["overseasEmitted"] = overseas_emitted
        stats["overseasGuaranteed"] = overseas_guaranteed

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

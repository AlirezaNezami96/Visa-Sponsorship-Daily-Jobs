"""Apify Dataset Sink with Atomic Charge-Before-Push, PPE monetization, and spending limit enforcement."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from apify import Actor

from job_radar.models.job import Job
from job_radar.pipeline.sink import JobSink

logger = logging.getLogger(__name__)


class ApifyDatasetSink(JobSink):
    """
    Pushes jobs to default Apify Dataset in batches with atomic Charge-Before-Push enforcement.

    Guarantees:
    1. Every item is charged via Actor.charge() BEFORE it is appended for push.
    2. If spending limit is reached, uncharged jobs are discarded immediately.
    3. Push failures after retry are persisted to Key-Value store under RECOVERY_UNPUSHED_ITEMS.
    4. Invariant: emitted_count == dataset_pushed_count (unless push delivery failure occurs).
    """

    def __init__(
        self,
        include_description: bool = True,
        include_raw_metadata: bool = False,
        deduplicator: Optional[Any] = None,
        deduplication_across_runs: bool = True,
        deduplication_ttl_days: int = 30,
    ) -> None:
        self.include_description = include_description
        self.include_raw_metadata = include_raw_metadata
        self.deduplicator = deduplicator
        self.deduplication_across_runs = deduplication_across_runs
        self.deduplication_ttl_days = deduplication_ttl_days
        self.cross_run_skipped_count = 0
        self.emitted_count = 0
        self.dataset_pushed_count = 0
        self.ai_classified_count = 0
        self.visa_enriched_count = 0
        self.overseas_count = 0
        self.limit_reached = False
        self.charged_not_delivered = False
        self.pending_push: List[Dict[str, Any]] = []
        self._unconfigured_events: set[str] = set()

    def is_limit_reached(self) -> bool:
        """Check if limit has been reached either locally or via Actor charging manager."""
        if self.limit_reached:
            return True
        cm = getattr(Actor, "charging_manager", None)
        if cm and getattr(cm, "is_limit_reached", False):
            self.limit_reached = True
            return True
        return False

    async def _charge_event(self, event_name: str) -> bool:
        """
        Charge a single PPE event safely.
        If user spending limit is reached, sets self.limit_reached = True and returns False.
        If event is unconfigured in Apify Console, logs a warning once and allows run to continue.
        """
        if self.limit_reached:
            return False
        try:
            charge_result = await Actor.charge(event_name=event_name)
            if getattr(charge_result, "event_charge_limit_reached", False) is True:
                logger.warning("User spending limit reached for PPE event '%s'. Stopping emission.", event_name)
                self.limit_reached = True
                return False
            return True
        except Exception as e:
            if event_name not in self._unconfigured_events:
                self._unconfigured_events.add(event_name)
                logger.warning(
                    "PPE event '%s' not configured or failed in Apify Console: %s. "
                    "Configure it in Apify Console → Pricing tab. Continuing run without charging for this event.",
                    event_name,
                    e,
                )
            return True

    async def _charge_job_events(self, item: Dict[str, Any]) -> bool:
        """
        Charge PPE events corresponding to features in the job BEFORE dataset push.
        Returns True if base job-result was charged and no spending limit was tripped.
        """
        if self.limit_reached:
            return False

        # 1. Base job result event (P0 required charge)
        base_ok = await self._charge_event("job-result")
        if not base_ok or self.limit_reached:
            return False

        # 2. Add-on AI classification event
        if item.get("relevanceScore") is not None and not item.get("ai_skipped"):
            if await self._charge_event("ai-classified-job"):
                self.ai_classified_count += 1
            elif self.limit_reached:
                return False

        # 3. Add-on official visa registry / known sponsor enrichment event
        if item.get("visaSignal") in ("on_sponsor_list", "known_sponsor"):
            if await self._charge_event("visa-enriched-job"):
                self.visa_enriched_count += 1
            elif self.limit_reached:
                return False

        # 4. Add-on overseas expansion event
        if item.get("sourceCategory"):
            if await self._charge_event("overseas-job"):
                self.overseas_count += 1
            elif self.limit_reached:
                return False

        return True

    async def _push_pending_batch(self) -> None:
        """Pushes a single batch of up to 100 charged items to the Apify dataset."""
        if not self.pending_push:
            return

        batch = self.pending_push[:100]
        self.pending_push = self.pending_push[100:]

        try:
            await Actor.push_data(batch)
            self.dataset_pushed_count += len(batch)
        except Exception as push_err:
            logger.warning("Actor.push_data failed (%s). Retrying once...", push_err)
            try:
                await asyncio.sleep(0.5)
                await Actor.push_data(batch)
                self.dataset_pushed_count += len(batch)
            except Exception as retry_err:
                logger.critical(
                    "Actor.push_data failed on retry: %s. Persisting %d charged items to Key-Value Store.",
                    retry_err,
                    len(batch),
                )
                self.charged_not_delivered = True
                try:
                    await Actor.set_value("RECOVERY_UNPUSHED_ITEMS", batch)
                except Exception as kv_err:
                    logger.critical("Failed to persist RECOVERY_UNPUSHED_ITEMS to KV store: %s", kv_err)

    async def flush_pending(self) -> None:
        """Flush all pending charged items into the dataset."""
        while self.pending_push:
            await self._push_pending_batch()

    async def emit(self, jobs: List[Job]) -> None:
        """
        Atomic Charge-Before-Push emission:
        1. Filter previously seen jobs across runs (if deduplicationAcrossRuns is active).
        2. Iterate each candidate job individually.
        3. Evaluate spending limit status.
        4. Convert job to camelCase dictionary.
        5. Charge corresponding PPE event(s).
        6. If charged successfully without hitting spending limit, enqueue for dataset push.
        7. If spending limit is reached, discard uncharged remainder and push only charged prefix.
        """
        if self.deduplicator and self.deduplication_across_runs:
            jobs, skipped = self.deduplicator.filter_jobs(
                jobs=jobs,
                enabled=True,
                ttl_days=self.deduplication_ttl_days,
            )
            self.cross_run_skipped_count += skipped
            if skipped:
                logger.info("Cross-run deduplication skipped %d previously seen jobs.", skipped)

        for job in jobs:
            if self.is_limit_reached():
                break

            item = job.to_apify_dict(
                include_description=self.include_description,
                include_raw_metadata=self.include_raw_metadata,
            )

            charged_ok = await self._charge_job_events(item)
            if not charged_ok or self.limit_reached:
                logger.warning("Spending limit reached during job charge. Halting emission.")
                break

            self.emitted_count += 1
            self.pending_push.append(item)

            if len(self.pending_push) >= 100:
                await self._push_pending_batch()

        if self.pending_push:
            await self.flush_pending()

    async def emit_stats(self, stats: Dict[str, Any]) -> None:
        """Write summary statistics to log and Key-Value store."""
        if self.limit_reached:
            stats["limitReached"] = True
        if self.charged_not_delivered:
            stats["chargedNotDelivered"] = True
        if self.cross_run_skipped_count:
            stats["crossRunDuplicatesSkipped"] = self.cross_run_skipped_count
        stats["emittedCount"] = self.emitted_count
        stats["datasetPushedCount"] = self.dataset_pushed_count

        Actor.log.info(f"Pipeline run statistics: {stats}")
        try:
            await Actor.set_value("RUN_STATS", stats)
        except Exception as e:
            logger.warning("Could not write RUN_STATS: %s", e)

    async def close(self) -> None:
        """Flush any pending items, persist deduplication state, and log final counters."""
        await self.flush_pending()
        if self.deduplicator and self.deduplication_across_runs:
            await self.deduplicator.save_state(ttl_days=self.deduplication_ttl_days)

        Actor.log.info(
            f"ApifyDatasetSink closed: {self.emitted_count} jobs charged, "
            f"{self.dataset_pushed_count} pushed to dataset, "
            f"{self.ai_classified_count} AI-classified, "
            f"{self.visa_enriched_count} visa-enriched, "
            f"{self.overseas_count} overseas, "
            f"{self.cross_run_skipped_count} cross-run duplicates skipped. "
            f"Limit reached: {self.limit_reached}, Charged not delivered: {self.charged_not_delivered}."
        )

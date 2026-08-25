"""Apify Dataset Sink with Batched Push, Pay-Per-Event (PPE) monetization, and spending limit enforcement."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from apify import Actor

from job_radar.models.job import Job
from job_radar.pipeline.sink import JobSink

logger = logging.getLogger(__name__)


class ApifyDatasetSink(JobSink):
    """Pushes jobs to default Apify Dataset in batches and fires Pay-Per-Event (PPE) charges."""

    def __init__(
        self,
        include_description: bool = True,
        include_raw_metadata: bool = False,
    ) -> None:
        self.include_description = include_description
        self.include_raw_metadata = include_raw_metadata
        self.emitted_count = 0
        self.ai_classified_count = 0
        self.visa_enriched_count = 0
        self.overseas_count = 0
        self.limit_reached = False

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
        Charge a single PPE event.
        Raises exception on billing failure and sets limit_reached if budget ceiling is hit.
        """
        if self.limit_reached:
            return False
        try:
            charge_result = await Actor.charge(event_name=event_name)
            if getattr(charge_result, "event_charge_limit_reached", False) is True:
                logger.warning("User spending limit reached. Stopping emission.")
                self.limit_reached = True
                return False
            return True
        except Exception as e:
            logger.error(f"Billing failed for event '{event_name}': {e}")
            raise

    async def _charge_job_events(self, item: Dict[str, Any]) -> None:
        """Charge PPE events corresponding to the features present in the emitted job."""
        if self.limit_reached:
            return

        # 1. Base job result event
        if await self._charge_event("job-result"):
            self.emitted_count += 1

        # 2. Add-on AI classification event
        if not self.limit_reached and item.get("relevanceScore") is not None:
            if await self._charge_event("ai-classified-job"):
                self.ai_classified_count += 1

        # 3. Add-on official visa registry enrichment event
        if not self.limit_reached and item.get("visaSignal") == "on_sponsor_list":
            if await self._charge_event("visa-enriched-job"):
                self.visa_enriched_count += 1

        # 4. Add-on overseas expansion event (optional, non-fatal)
        if not self.limit_reached and item.get("sourceCategory"):
            try:
                if await self._charge_event("overseas-job"):
                    self.overseas_count += 1
            except Exception as e:
                # New event may not exist yet in the Actor's Console pricing config.
                # Never let an optional add-on event kill a paying run.
                logger.warning("overseas-job charge failed (add it in Apify Console → Pricing): %s", e)

    async def emit(self, jobs: List[Job]) -> None:
        """Push normalized camelCase jobs to dataset in memory-safe batches and charge PPE events."""
        batch: List[Dict[str, Any]] = []

        for job in jobs:
            if self.limit_reached:
                break

            item = job.to_apify_dict(
                include_description=self.include_description,
                include_raw_metadata=self.include_raw_metadata,
            )
            batch.append(item)

            if len(batch) >= 100:
                await Actor.push_data(batch)
                for it in batch:
                    if self.limit_reached:
                        break
                    await self._charge_job_events(it)
                batch = []

        if batch and not self.limit_reached:
            await Actor.push_data(batch)
            for it in batch:
                if self.limit_reached:
                    break
                await self._charge_job_events(it)

    async def emit_stats(self, stats: Dict[str, Any]) -> None:
        """Write summary statistics to log and Key-Value store."""
        if self.limit_reached:
            stats["limitReached"] = True
        Actor.log.info(f"Pipeline run statistics: {stats}")
        try:
            await Actor.set_value("RUN_STATS", stats)
        except Exception as e:
            logger.warning("Could not write RUN_STATS: %s", e)

    async def close(self) -> None:
        """Log final emission counters."""
        Actor.log.info(
            f"ApifyDatasetSink closed: {self.emitted_count} jobs emitted, "
            f"{self.ai_classified_count} AI-classified, "
            f"{self.visa_enriched_count} visa-enriched, "
            f"{self.overseas_count} overseas. "
            f"Limit reached: {self.limit_reached}."
        )

"""Apify Dataset Sink with Pay-Per-Event (PPE) monetization support and spending limit enforcement."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from apify import Actor

from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job
from job_radar.pipeline.sink import JobSink

logger = logging.getLogger(__name__)


class ApifyDatasetSink(JobSink):
    """Pushes jobs to the default Apify Dataset and fires Pay-Per-Event (PPE) charge events."""

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
        self.limit_reached = False

    async def emit(self, jobs: List[Job]) -> None:
        """Push normalized camelCase jobs to dataset and charge PPE events."""
        for job in jobs:
            if self.limit_reached:
                Actor.log.warning("User spending limit reached; stopping further job emissions.")
                break

            item = job.to_apify_dict(
                include_description=self.include_description,
                include_raw_metadata=self.include_raw_metadata,
            )

            # 1. Push to dataset
            await Actor.push_data(item)

            # 2. Base PPE event for job result (charged for every emitted item)
            try:
                charge_res = await Actor.charge(event_name="job-result")
                if getattr(charge_res, "event_charge_limit_reached", False) is True:
                    self.limit_reached = True
            except Exception as e:
                logger.debug("Actor.charge('job-result') note: %s", e)
            self.emitted_count += 1

            # 3. Add-on PPE event for AI classification
            if job.relevance_score is not None and not self.limit_reached:
                try:
                    ai_charge_res = await Actor.charge(event_name="ai-classified-job")
                    if getattr(ai_charge_res, "event_charge_limit_reached", False) is True:
                        self.limit_reached = True
                except Exception as e:
                    logger.debug("Actor.charge('ai-classified-job') note: %s", e)
                self.ai_classified_count += 1

            # 4. Add-on PPE event for official visa registry enrichment (ON_SPONSOR_LIST)
            conf_val = job.visa_confidence if isinstance(job.visa_confidence, str) else job.visa_confidence.value
            if (conf_val == VisaConfidence.ON_SPONSOR_LIST.value or conf_val == "on_sponsor_list") and not self.limit_reached:
                try:
                    visa_charge_res = await Actor.charge(event_name="visa-enriched-job")
                    if getattr(visa_charge_res, "event_charge_limit_reached", False) is True:
                        self.limit_reached = True
                except Exception as e:
                    logger.debug("Actor.charge('visa-enriched-job') note: %s", e)
                self.visa_enriched_count += 1

            if self.limit_reached:
                Actor.log.warning("User spending limit reached during item charging; stopping emissions.")
                break

    async def emit_stats(self, stats: Dict[str, Any]) -> None:
        """Write summary statistics to log and Key-Value store."""
        if self.limit_reached:
            stats["limitReached"] = True
        Actor.log.info(f"Pipeline run statistics: {stats}")
        try:
            await Actor.set_value("RUN_STATS", stats)
        except Exception as e:
            logger.debug("Could not write RUN_STATS: %s", e)

    async def close(self) -> None:
        """Log final emission counters."""
        Actor.log.info(
            f"ApifyDatasetSink closed: {self.emitted_count} jobs emitted, "
            f"{self.ai_classified_count} AI-classified, "
            f"{self.visa_enriched_count} visa-enriched. "
            f"Limit reached: {self.limit_reached}."
        )

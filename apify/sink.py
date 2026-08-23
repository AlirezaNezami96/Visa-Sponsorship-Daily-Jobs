"""Apify Dataset Sink with Pay-Per-Event (PPE) monetization support."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from apify import Actor

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

    async def emit(self, jobs: List[Job]) -> None:
        """Push normalized camelCase jobs to dataset and charge PPE events."""
        for job in jobs:
            item = job.to_apify_dict(
                include_description=self.include_description,
                include_raw_metadata=self.include_raw_metadata,
            )

            # Push to dataset
            await Actor.push_data(item)

            # 1. Base PPE event for job result
            try:
                await Actor.charge(event_name="job-result")
            except Exception as e:
                logger.debug("Actor.charge('job-result') note: %s", e)
            self.emitted_count += 1

            # 2. Add-on PPE event for AI classification
            if job.relevance_score is not None:
                try:
                    await Actor.charge(event_name="ai-classified-job")
                except Exception as e:
                    logger.debug("Actor.charge('ai-classified-job') note: %s", e)
                self.ai_classified_count += 1

            # 3. Add-on PPE event for official visa registry enrichment
            conf_val = job.visa_confidence if isinstance(job.visa_confidence, str) else job.visa_confidence.value
            if conf_val in ("on_sponsor_list", "historical_filings", "stated_in_jd"):
                try:
                    await Actor.charge(event_name="visa-enriched-job")
                except Exception as e:
                    logger.debug("Actor.charge('visa-enriched-job') note: %s", e)
                self.visa_enriched_count += 1

    async def emit_stats(self, stats: Dict[str, Any]) -> None:
        """Write summary statistics to log and Key-Value store."""
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
            f"{self.visa_enriched_count} visa-enriched."
        )

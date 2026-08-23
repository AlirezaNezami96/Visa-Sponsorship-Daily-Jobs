"""Apify Actor entrypoint. Thin asynchronous adapter layer delegating to the shared pipeline."""
from __future__ import annotations

import asyncio
import logging
from apify import Actor

from apify_actor.config_mapper import input_to_config
from apify_actor.sink import ApifyDatasetSink
from job_radar.pipeline.orchestrator import run_pipeline

logger = logging.getLogger("apify_main")


async def main() -> None:
    """Main Actor execution routine with runtime timeout enforcement."""
    async with Actor:
        # 1. Read input from Apify environment
        actor_input = await Actor.get_input()
        Actor.log.info("Loaded Apify Actor input payload.")

        # 2. Map input to canonical JobSearchConfig
        config = input_to_config(actor_input)

        # 3. Instantiate Apify dataset sink with PPE support
        sink = ApifyDatasetSink(
            include_description=config.include_description,
            include_raw_metadata=config.include_raw_metadata,
        )

        # 4. Run the shared job pipeline with maxRuntimeSecs enforcement
        try:
            result = await asyncio.wait_for(
                run_pipeline(config, sink),
                timeout=float(config.max_runtime_secs),
            )
            # Output run status
            Actor.log.info(
                f"Actor run finished successfully: {result.stats.get('totalEmitted', 0)} jobs emitted. "
                f"Duration: {result.stats.get('durationSeconds', 0)}s."
            )
        except asyncio.TimeoutError:
            Actor.log.warning(
                f"Actor reached maximum runtime timeout of {config.max_runtime_secs}s. Gracefully stopping."
            )
            timeout_stats = {
                "timeoutReached": True,
                "maxRuntimeSecs": config.max_runtime_secs,
                "emittedCount": sink.emitted_count,
            }
            await sink.emit_stats(timeout_stats)
            await sink.close()


if __name__ == "__main__":
    asyncio.run(main())

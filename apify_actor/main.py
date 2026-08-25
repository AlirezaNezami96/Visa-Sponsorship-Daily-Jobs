"""Apify Actor entrypoint. Thin asynchronous adapter layer delegating to the shared pipeline."""
from __future__ import annotations

import asyncio
import logging
import os
from apify import Actor

from apify_actor.config_mapper import input_to_config
from apify_actor.sink import ApifyDatasetSink
from job_radar.notifications.email import send_worker_run_alert
from job_radar.pipeline.orchestrator import run_pipeline

logger = logging.getLogger("apify_main")

# One httpx log line per request (hundreds per run) drowns the actor log;
# keep warnings/errors only. The adapter logs its own fetch summaries.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main() -> None:
    """Main Actor execution routine with runtime timeout enforcement and guaranteed cleanup."""
    async with Actor:
        # 1. Read input from Apify environment
        actor_input = await Actor.get_input() or {}
        Actor.log.info("Loaded Apify Actor input payload.")

        # Determine Apify identifiers for console links
        try:
            apify_env = Actor.get_env() if hasattr(Actor, "get_env") else {}
        except Exception:
            apify_env = {}
        actor_id = apify_env.get("actor_id") or apify_env.get("id") or os.getenv("APIFY_ACTOR_ID", "")
        run_id = apify_env.get("run_id") or apify_env.get("actor_run_id") or os.getenv("APIFY_ACTOR_RUN_ID", "")
        run_url = f"https://console.apify.com/actors/{actor_id}/runs/{run_id}" if (actor_id and run_id) else None
        dataset_id = apify_env.get("default_dataset_id") or os.getenv("APIFY_DEFAULT_DATASET_ID", "")
        dataset_url = f"https://console.apify.com/storage/datasets/{dataset_id}" if dataset_id else None

        # 2. Map input to canonical JobSearchConfig
        config = input_to_config(actor_input)

        # 3. Instantiate Apify dataset sink with PPE support
        sink = ApifyDatasetSink(
            include_description=config.include_description,
            include_raw_metadata=config.include_raw_metadata,
        )

        # 4. Run the shared job pipeline with maxRuntimeSecs enforcement and guaranteed cleanup in finally
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

            # 5. Generate human-friendly reports (REPORT.json / REPORT.html) in the
            #    Key-Value Store. Additive and non-fatal: failures are logged only.
            from apify_actor.report_writer import write_apify_reports
            await write_apify_reports(
                config=config,
                jobs=result.jobs,
                stats=result.stats,
                successful_sources=result.successful_sources,
                failed_sources=result.failed_sources,
                status="completed",
            )

            # 6. Send email notification to owner (uses RESEND_API_KEY & EMAIL_TO if set)
            try:
                send_worker_run_alert(
                    run_id=run_id or "actor-run",
                    status="completed",
                    inputs=actor_input,
                    stats=result.stats,
                    run_url=run_url,
                    dataset_url=dataset_url,
                )
            except Exception as notify_err:
                Actor.log.warning(f"Worker run email notification skipped or failed: {notify_err}")

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
            try:
                send_worker_run_alert(
                    run_id=run_id or "actor-run",
                    status="timed_out",
                    inputs=actor_input,
                    stats=timeout_stats,
                    run_url=run_url,
                    dataset_url=dataset_url,
                )
            except Exception as notify_err:
                Actor.log.warning(f"Worker timeout email notification skipped or failed: {notify_err}")

        except Exception as e:
            Actor.log.error(f"Pipeline failed: {e}")
            try:
                send_worker_run_alert(
                    run_id=run_id or "actor-run",
                    status="failed",
                    inputs=actor_input,
                    error_message=str(e),
                    run_url=run_url,
                    dataset_url=dataset_url,
                )
            except Exception as notify_err:
                Actor.log.warning(f"Worker failure email notification skipped or failed: {notify_err}")
            raise
        finally:
            await sink.close()


if __name__ == "__main__":
    asyncio.run(main())


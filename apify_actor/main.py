"""Apify Actor entrypoint. Thin asynchronous adapter layer delegating to the shared pipeline."""
from __future__ import annotations

import asyncio
import logging
import os
from apify import Actor

from apify_actor.config_mapper import input_to_config
from apify_actor.dedup import CrossRunDeduplicator
from apify_actor.registry_cache import ensure_fresh_registries
from apify_actor.sink import ApifyDatasetSink
from job_radar.pipeline.orchestrator import run_pipeline

logger = logging.getLogger("apify_main")

# One httpx log line per request (hundreds per run) drowns the actor log;
# keep warnings/errors only. The adapter logs its own fetch summaries.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main() -> None:
    """Main Actor execution routine with runtime timeout enforcement, deduplication, and guaranteed cleanup."""
    async with Actor:
        # 1. Read input from Apify environment
        actor_input = await Actor.get_input() or {}
        Actor.log.info("Loaded Apify Actor input payload.")

        # 2. Map input to canonical JobSearchConfig
        config = input_to_config(actor_input)

        # Fast-fail guard: at least one meaningful search criteria required
        if (
            not config.keywords
            and not config.countries
            and not config.sources
            and not config.company_urls
            and not config.company_names
            and not config.enable_overseas_sources
        ):
            msg = "No search criteria provided: specify at least one keyword, country, source, or company URL."
            Actor.log.error(msg)
            raise ValueError(msg)

        # 3. Setup Apify Standard Proxy Configuration (if configured)
        proxy_cfg = actor_input.get("proxyConfiguration") or getattr(config, "proxy_configuration", None)
        if proxy_cfg:
            try:
                proxy_configuration = await Actor.create_proxy_configuration(proxy_cfg)
                if proxy_configuration:
                    proxy_url = await proxy_configuration.new_url()
                    if proxy_url:
                        os.environ["HTTP_PROXY"] = proxy_url
                        os.environ["HTTPS_PROXY"] = proxy_url
                        config.proxy_url = proxy_url
                        Actor.log.info("Configured Apify Standard Proxy for HTTP fetchers.")
            except Exception as proxy_err:
                Actor.log.warning(f"Could not initialize Apify proxy: {proxy_err}. Continuing with direct connection.")

        # 4. Sponsor Registry Freshness / Bundled Cache Fallback
        reg_meta = await ensure_fresh_registries(
            refresh_requested=getattr(config, "refresh_registries", False),
        )
        Actor.log.info(
            f"Sponsor registry loaded: {reg_meta.get('sponsors_count', 0)} sponsors "
            f"(source: {reg_meta.get('sponsors_db_source')})."
        )

        # 5. Initialize Cross-Run Deduplicator
        deduplicator = CrossRunDeduplicator()
        await deduplicator.init(reset=config.reset_dedup_state)

        # 6. Instantiate Apify dataset sink with PPE support and cross-run dedup
        sink = ApifyDatasetSink(
            include_description=config.include_description,
            include_raw_metadata=config.include_raw_metadata,
            deduplicator=deduplicator,
            deduplication_across_runs=config.deduplication_across_runs,
            deduplication_ttl_days=config.deduplication_ttl_days,
        )

        # 7. Run the shared job pipeline with maxRuntimeSecs enforcement and guaranteed cleanup
        try:
            result = await asyncio.wait_for(
                run_pipeline(config, sink),
                timeout=float(config.max_runtime_secs),
            )
            # Merge registry metadata into stats
            result.stats.update(reg_meta)

            # Output run status
            Actor.log.info(
                f"Actor run finished successfully: {sink.emitted_count} jobs charged, "
                f"{sink.dataset_pushed_count} pushed to dataset. "
                f"Duration: {result.stats.get('durationSeconds', 0)}s."
            )

            # 8. Generate human-friendly reports (REPORT.json / REPORT.html) in KV Store
            from apify_actor.report_writer import write_apify_reports

            await write_apify_reports(
                config=config,
                jobs=result.jobs,
                stats=result.stats,
                successful_sources=result.successful_sources,
                failed_sources=result.failed_sources,
                status="completed",
            )

        except asyncio.TimeoutError:
            Actor.log.warning(
                f"Actor reached maximum runtime timeout of {config.max_runtime_secs}s. Gracefully stopping and flushing dataset."
            )
            await sink.flush_pending()
            timeout_stats = {
                "timeoutReached": True,
                "maxRuntimeSecs": config.max_runtime_secs,
                "emittedCount": sink.emitted_count,
                "datasetPushedCount": sink.dataset_pushed_count,
            }
            timeout_stats.update(reg_meta)
            await sink.emit_stats(timeout_stats)

        except Exception as e:
            Actor.log.error(f"Pipeline failed: {e}")
            await sink.flush_pending()
            raise
        finally:
            await sink.close()


if __name__ == "__main__":
    asyncio.run(main())



"""OverseasAdapter: flag-gated aggregator fetching the verified overseas registry.

Design constraints (all deliberate):
- One shared httpx.AsyncClient, bounded global + per-host concurrency.
- Per-source isolation: a failing/expired source never raises upward.
- Budget deadline: scheduling stops past 0.9 * overseas_budget_secs; whatever
  jobs were gathered are always returned.
- robots.txt respected (per-domain, in-memory cache) when enabled.
- Hard 1.5 MB body cap per page, streamed.
- Per-domain 50-job cap; adapter total cap = max_results * 3 (pre-dedup).
- Visa fields are intentionally NOT set here; the visa stage owns them.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import replace as dc_replace
from time import monotonic
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib import robotparser

import httpx

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.base import SourceAdapter
from job_radar.sources.overseas.extractors import RawOverseasJob, extract_all
from job_radar.sources.overseas.geo import normalize_destination
from job_radar.sources.overseas.registry import OverseasSource, get_enabled_sources

logger = logging.getLogger(__name__)

USER_AGENT = "JobRadarOverseas/1.0 (+https://apify.com)"
PER_SOURCE_TIMEOUT_SECS = 20.0
ROBOTS_TIMEOUT_SECS = 5.0
MAX_BODY_BYTES = 1_500_000
PER_DOMAIN_JOB_CAP = 50
PER_HOST_CONCURRENCY = 2
DETAIL_ENRICH_MIN_CHARS = 300

_ALLOWED_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/xml",
    "application/xml",
    "application/rss+xml",
    "application/atom+xml",
)

# (raw job, its source, provenance of the description)
JobTuple = Tuple[RawOverseasJob, OverseasSource, str]


# Category priority for source selection when overseasMaxSourcesPerRun truncates.
# Migration-corridor sources (manpower agencies + government labor portals) lead,
# then visa specialists and remote boards; generic aggregators and unknown boards
# (often domestic circular sites or anti-bot-blocked) are tried last.
_CATEGORY_PRIORITY: Dict[str, int] = {
    "manpower_agency": 0,
    "government": 1,
    "visa_specialist": 2,
    "remote_board": 3,
    "aggregator": 4,
    "unknown_board": 5,
}


def _source_priority(source: OverseasSource) -> Tuple[int, int, str]:
    """Sort key: priority category first, then tier1, then stable by domain."""
    category_rank = _CATEGORY_PRIORITY.get(source.category, 9)
    tier_rank = 0 if str(source.tier).startswith("tier1") else 1
    return (category_rank, tier_rank, source.domain)


class OverseasAdapter(SourceAdapter):
    """Aggregates the build-time-verified overseas source registry."""

    def __init__(self, config: JobSearchConfig) -> None:
        categories = set(config.overseas_categories or [])
        self.sources: List[OverseasSource] = get_enabled_sources(categories=categories or None)
        # Prioritize so budget-limited runs hit the highest-value corridors first.
        self.sources.sort(key=_source_priority)
        self.sources = self.sources[: max(0, int(config.overseas_max_sources_per_run or 0))]
        self.fetch_timeout_secs: int = int(config.overseas_budget_secs or 600)
        self.failed_sources: List[Dict[str, str]] = []
        self.skipped_sources: List[Dict[str, str]] = []
        self.stats: Dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "overseas"

    @property
    def source_type(self) -> str:
        return "aggregator"

    def supports_company_urls(self) -> bool:
        return False

    # ── fetch entrypoint ──

    async def fetch(self, config: JobSearchConfig) -> List[Job]:
        deadline = monotonic() + config.overseas_budget_secs * 0.9
        self.failed_sources = []
        self.skipped_sources = []
        self._job_tuples: List[JobTuple] = []
        self._robots_cache: Dict[str, Optional[robotparser.RobotFileParser]] = {}
        job_tuples = self._job_tuples
        state: Dict[str, Any] = {"detail_fetches": 0, "dropped_destination": 0}
        total_cap = max(1, int(config.max_results or 200)) * 3
        sem = asyncio.Semaphore(max(1, int(config.overseas_concurrency or 20)))
        host_sems: Dict[str, asyncio.Semaphore] = {}

        def host_sem_factory(domain: str) -> asyncio.Semaphore:
            s = host_sems.get(domain)
            if s is None:
                s = asyncio.Semaphore(PER_HOST_CONCURRENCY)
                host_sems[domain] = s
            return s

        limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
        attempted = 0

        async with httpx.AsyncClient(
            limits=limits,
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            tasks: List[asyncio.Task] = []
            for source in self.sources:
                if monotonic() > deadline:
                    break
                attempted += 1
                tasks.append(
                    asyncio.create_task(
                        self._fetch_source_isolated(
                            client, source, sem, host_sem_factory, state, deadline, config, job_tuples, total_cap
                        )
                    )
                )
            await asyncio.gather(*tasks, return_exceptions=False)
            # job_tuples is appended to inside each isolated task; nothing raises out.

        if attempted < len(self.sources):
            logger.info("overseas: deadline reached, %d/%d sources attempted", attempted, len(self.sources))

        jobs = self._build_jobs(job_tuples[:total_cap], config, state)

        self.stats = {
            "sources_total": len(self.sources),
            "sources_attempted": attempted,
            "raw_jobs": len(job_tuples),
            "detail_fetches": state["detail_fetches"],
            "dropped_destination_filter": state["dropped_destination"],
            "failed_sources": len(self.failed_sources),
            "skipped_sources": len(self.skipped_sources),
        }
        logger.info(
            "overseas: %d jobs built (%d attempted sources, %d failed, %d skipped, %d detail fetches)",
            len(jobs), attempted, len(self.failed_sources), len(self.skipped_sources), state["detail_fetches"],
        )
        return jobs

    # ── per-source isolation wrapper ──

    async def _fetch_source_isolated(
        self,
        client: httpx.AsyncClient,
        source: OverseasSource,
        sem: asyncio.Semaphore,
        host_sem_factory: Callable[[str], asyncio.Semaphore],
        state: Dict[str, Any],
        deadline: float,
        config: JobSearchConfig,
        job_tuples: List[JobTuple],
        total_cap: int,
    ) -> None:
        try:
            chunk = await asyncio.wait_for(
                self._fetch_source(client, source, sem, host_sem_factory, state, deadline, config, total_cap),
                timeout=PER_SOURCE_TIMEOUT_SECS,
            )
        except asyncio.TimeoutError:
            self.failed_sources.append({"domain": source.domain, "error": "timeout"})
            logger.debug("overseas: source %s timed out after %.0fs", source.domain, PER_SOURCE_TIMEOUT_SECS)
            return
        except Exception as e:
            self.failed_sources.append({"domain": source.domain, "error": str(e)[:200]})
            logger.debug("overseas: source %s failed: %s", source.domain, e)
            return
        if chunk:
            job_tuples.extend(chunk)

    async def _fetch_source(
        self,
        client: httpx.AsyncClient,
        source: OverseasSource,
        sem: asyncio.Semaphore,
        host_sem_factory: Callable[[str], asyncio.Semaphore],
        state: Dict[str, Any],
        deadline: float,
        config: JobSearchConfig,
        total_cap: int,
    ) -> List[JobTuple]:
        if monotonic() > deadline or len(self._job_tuples) >= total_cap:
            return []

        if config.respect_robots_txt and not await self._robots_allow(client, source, host_sem_factory):
            self.skipped_sources.append({"domain": source.domain, "error": "robots_disallowed"})
            logger.debug("overseas: robots.txt disallows %s, skipping", source.domain)
            return []

        last_error: Optional[str] = None
        async with sem:
            for url in source.start_urls:
                if monotonic() > deadline:
                    return []
                content, content_type, err = await self._get_page(client, url, host_sem_factory(source.domain))
                if content is None:
                    last_error = err or last_error
                    continue
                jobs, _strategy = extract_all(content, url, rss_capable=source.rss_capable, content_type=content_type)
                if not jobs:
                    continue
                jobs = jobs[:PER_DOMAIN_JOB_CAP]
                tuples: List[JobTuple] = [(j, source, "list_card") for j in jobs]
                if config.overseas_fetch_details and state["detail_fetches"] < config.overseas_max_detail_fetches:
                    tuples = await self._enrich_details(client, tuples, host_sem_factory(source.domain), state, config)
                return tuples
            if last_error:
                self.failed_sources.append({"domain": source.domain, "error": last_error})
            return []

    # ── HTTP primitives ──

    async def _get_page(
        self,
        client: httpx.AsyncClient,
        url: str,
        host_sem: asyncio.Semaphore,
    ) -> Tuple[Optional[str], str, Optional[str]]:
        """Fetch a page with streaming body cap.

        Returns (text_or_None, content_type, error_or_None).
        """
        async with host_sem:
            try:
                async with client.stream("GET", url) as resp:
                    if resp.status_code >= 400:
                        logger.debug("overseas: %s -> HTTP %d", url, resp.status_code)
                        return None, "", f"http_{resp.status_code}"
                    ct_low = (resp.headers.get("content-type", "") or "").lower()
                    if ct_low and not any(t in ct_low for t in _ALLOWED_CONTENT_TYPES):
                        logger.debug("overseas: %s -> unsupported content type %s", url, ct_low)
                        return None, "", f"content_type_{ct_low.split(';')[0].strip()}"
                    chunks: List[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= MAX_BODY_BYTES:
                            break
                    body = b"".join(chunks)
                    return body.decode("utf-8", errors="replace"), ct_low.split(";")[0].strip(), None
            except httpx.HTTPError as e:
                logger.debug("overseas: fetch %s failed: %s", url, e)
                return None, "", type(e).__name__
            except Exception as e:
                logger.debug("overseas: fetch %s unexpected error: %s", url, e)
                return None, "", type(e).__name__

    async def _robots_allow(
        self,
        client: httpx.AsyncClient,
        source: OverseasSource,
        host_sem_factory: Callable[[str], asyncio.Semaphore],
    ) -> bool:
        domain = source.domain
        if domain not in self._robots_cache:
            parser: Optional[robotparser.RobotFileParser] = None
            robots_url = f"https://{domain}/robots.txt"
            try:
                async with host_sem_factory(domain):
                    resp = await client.get(robots_url, timeout=ROBOTS_TIMEOUT_SECS)
                    if resp.status_code < 400:
                        parser = robotparser.RobotFileParser()
                        parser.parse(resp.text.splitlines())
                    else:
                        logger.debug("overseas: robots.txt for %s returned %d; proceeding", domain, resp.status_code)
            except Exception:
                logger.debug("overseas: robots.txt fetch failed for %s; proceeding", domain)
            self._robots_cache[domain] = parser

        parser = self._robots_cache.get(domain)
        if parser is None:
            return True
        for url in source.start_urls:
            if not parser.can_fetch(USER_AGENT, url):
                return False
        return True

    # ── detail-page enrichment ──

    async def _enrich_details(
        self,
        client: httpx.AsyncClient,
        tuples: List[JobTuple],
        host_sem: asyncio.Semaphore,
        state: Dict[str, Any],
        config: JobSearchConfig,
    ) -> List[JobTuple]:
        enriched: List[JobTuple] = []
        for raw, source, desc_source in tuples:
            if state["detail_fetches"] >= config.overseas_max_detail_fetches:
                enriched.append((raw, source, desc_source))
                continue
            if len(raw.description or "") >= DETAIL_ENRICH_MIN_CHARS or not raw.detail_url:
                enriched.append((raw, source, desc_source))
                continue
            state["detail_fetches"] += 1
            content, _ct, _err = await self._get_page(client, raw.detail_url, host_sem)
            if not content:
                enriched.append((raw, source, desc_source))
                continue
            try:
                detail_jobs, _strategy = extract_all(content, raw.detail_url)
            except Exception:
                enriched.append((raw, source, desc_source))
                continue
            if not detail_jobs:
                enriched.append((raw, source, desc_source))
                continue
            best = detail_jobs[0]
            if len(best.description or "") <= len(raw.description or ""):
                enriched.append((raw, source, desc_source))
                continue
            merged = dc_replace(
                raw,
                description=best.description,
                posted_at=best.posted_at or raw.posted_at,
                salary_min=raw.salary_min if raw.salary_min is not None else best.salary_min,
                salary_max=raw.salary_max if raw.salary_max is not None else best.salary_max,
                salary_currency=raw.salary_currency or best.salary_currency,
                salary_period=raw.salary_period or best.salary_period,
                company=raw.company or best.company,
                location=raw.location or best.location,
            )
            enriched.append((merged, source, "detail_page"))
        return enriched

    # ── canonical Job building ──

    def _build_jobs(
        self,
        job_tuples: List[JobTuple],
        config: JobSearchConfig,
        state: Dict[str, Any],
    ) -> List[Job]:
        dest_filter = {c.strip() for c in (config.overseas_destination_countries or []) if c and c.strip()}
        jobs: List[Job] = []
        seen_ids: set = set()

        for raw, source, desc_source in job_tuples:
            apply_url = raw.apply_url or raw.detail_url or ""
            if not apply_url:
                continue
            source_id = hashlib.sha256(apply_url.encode("utf-8")).hexdigest()[:16]
            job_id = f"ov-{source.domain}-{source_id}"
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            country = normalize_destination(f"{raw.location or ''} {raw.title} {(raw.description or '')[:300]}")

            if dest_filter:
                if country and country not in dest_filter:
                    state["dropped_destination"] += 1
                    continue

            jobs.append(
                Job(
                    id=job_id,
                    source="overseas",
                    source_id=source_id,
                    ats=source.domain,
                    title=raw.title or "Untitled",
                    company=raw.company or source.domain,
                    description=raw.description or raw.title or "",
                    location=raw.location or "",
                    country=country,
                    posted_at=raw.posted_at,
                    salary_min=raw.salary_min,
                    salary_max=raw.salary_max,
                    salary_currency=raw.salary_currency,
                    salary_period=raw.salary_period,
                    apply_url=apply_url,
                    url=apply_url,
                    metadata={
                        "source_category": source.category,
                        "source_country": source.country,
                        "overseas": True,
                        "extraction_strategy": raw.strategy,
                        "description_source": desc_source,
                        "source_domain": source.domain,
                    },
                )
            )
        if dest_filter and state["dropped_destination"]:
            logger.info("overseas: destination filter dropped %d jobs", state["dropped_destination"])
        return jobs

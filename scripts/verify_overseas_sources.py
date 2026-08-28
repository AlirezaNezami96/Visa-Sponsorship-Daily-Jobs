#!/usr/bin/env python3
"""
scripts/verify_overseas_sources.py

Runtime verification tool for the overseas source registry (manual, not CI).

Fetches every enabled source's start URLs with the same client settings as the
OverseasAdapter, runs the three-strategy extraction ladder, and reports the
yield + chosen strategy per source plus an aggregate summary.

With --write it quarantines sources that yielded 0 jobs by setting
    enabled: false
    disabled_reason: "zero_yield_at_verify <YYYY-MM-DD>"
in data/overseas_sources.json via an atomic write (temp file + os.replace).
It never adds or otherwise edits sources.

Usage:
    python scripts/verify_overseas_sources.py [--limit N] [--category C] [--write]
                                              [--concurrency M] [--timeout-secs S]

This tool makes real network calls. It is intentionally NOT imported by the
package and NOT run by pytest.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add src to python path for imports (mirrors scripts/build_sponsors_db.py).
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

import httpx  # noqa: E402

from job_radar.sources.overseas.extractors import extract_all  # noqa: E402
from job_radar.sources.overseas.registry import (  # noqa: E402
    OverseasSource,
    _registry_path,
    get_enabled_sources,
    registry_stats,
)

USER_AGENT = "JobRadarOverseas/1.0 (+https://apify.com)"
MAX_BODY_BYTES = 1_500_000
ROBOTS_TIMEOUT_SECS = 5.0
PER_HOST_CONCURRENCY = 2
DEFAULT_TIMEOUT_SECS = 15.0

_ALLOWED_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/xml",
    "application/xml",
    "application/rss+xml",
    "application/atom+xml",
)


async def _get_page(
    client: httpx.AsyncClient,
    url: str,
    host_sem: asyncio.Semaphore,
) -> Tuple[Optional[str], str, Optional[str]]:
    """Fetch a page with the streaming body cap. Returns (text_or_None, content_type, error_or_None)."""
    async with host_sem:
        try:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    return None, "", f"http_{resp.status_code}"
                ct_low = (resp.headers.get("content-type", "") or "").lower()
                if ct_low and not any(t in ct_low for t in _ALLOWED_CONTENT_TYPES):
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
            return None, "", type(e).__name__
        except Exception as e:  # noqa: BLE001
            return None, "", type(e).__name__


async def _robots_allow(
    client: httpx.AsyncClient,
    source: OverseasSource,
    host_sem: asyncio.Semaphore,
    robots_cache: Dict[str, object],
    user_agent: str,
) -> Optional[bool]:
    """Return True/False if robots decided, or None if undetermined (proceed)."""
    from urllib import robotparser

    domain = source.domain
    if domain not in robots_cache:
        parser: Optional[robotparser.RobotFileParser] = None
        try:
            async with host_sem:
                resp = await client.get(f"https://{domain}/robots.txt", timeout=ROBOTS_TIMEOUT_SECS)
                if resp.status_code < 400:
                    parser = robotparser.RobotFileParser()
                    parser.parse(resp.text.splitlines())
        except Exception:  # noqa: BLE001
            parser = None
        robots_cache[domain] = parser

    parser = robots_cache.get(domain)
    if parser is None:
        return None
    for url in source.start_urls:
        if not parser.can_fetch(user_agent, url):
            return False
    return True


async def _verify_source(
    client: httpx.AsyncClient,
    source: OverseasSource,
    sem: asyncio.Semaphore,
    host_sem: asyncio.Semaphore,
    robots_cache: Dict[str, object],
    respect_robots: bool,
    timeout: float,
) -> Dict[str, object]:
    """Fetch a source's start URLs until one yields jobs. Never raises."""
    result: Dict[str, object] = {
        "domain": source.domain,
        "category": source.category,
        "country": source.country,
        "yield": 0,
        "strategy": None,
        "url": None,
        "error": None,
    }

    if respect_robots:
        try:
            allowed = await _robots_allow(client, source, host_sem, robots_cache, USER_AGENT)
        except Exception:  # noqa: BLE001
            allowed = None
        if allowed is False:
            result["error"] = "robots_disallowed"
            return result

    last_error: Optional[str] = None
    async with sem:
        try:
            for url in source.start_urls:
                content, content_type, err = await asyncio.wait_for(
                    _get_page(client, url, host_sem), timeout=timeout
                )
                if content is None:
                    last_error = err or last_error
                    continue
                try:
                    jobs, strategy = extract_all(
                        content, url, rss_capable=source.rss_capable, content_type=content_type
                    )
                except Exception as e:  # noqa: BLE001
                    last_error = f"extract:{type(e).__name__}"
                    continue
                if not jobs:
                    last_error = last_error or "zero_yield"
                    continue
                result["yield"] = len(jobs)
                result["strategy"] = strategy
                result["url"] = url
                return result
        except asyncio.TimeoutError:
            result["error"] = "timeout"
            return result
        except Exception as e:  # noqa: BLE001
            result["error"] = type(e).__name__
            return result

    if last_error:
        result["error"] = last_error
    else:
        result["error"] = result["error"] or "zero_yield"
    return result


async def _run(limit: int, category: Optional[str], concurrency: int, timeout: float, respect_robots: bool) -> List[Dict[str, object]]:
    categories = {category} if category else None
    sources = get_enabled_sources(categories=categories)
    if limit > 0:
        sources = sources[:limit]

    if not sources:
        print("No enabled sources matched the filter.")
        return []

    print(f"Verifying {len(sources)} enabled source(s)...")
    stats = registry_stats()
    print(f"Registry: {stats['total']} total / {stats['enabled']} enabled")

    sem = asyncio.Semaphore(max(1, concurrency))
    host_sems: Dict[str, asyncio.Semaphore] = {}
    robots_cache: Dict[str, object] = {}
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)

    results: List[Dict[str, object]] = []
    async with httpx.AsyncClient(
        limits=limits,
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        tasks = []
        for s in sources:
            hs = host_sems.setdefault(s.domain, asyncio.Semaphore(PER_HOST_CONCURRENCY))
            tasks.append(
                asyncio.create_task(
                    _verify_source(client, s, sem, hs, robots_cache, respect_robots, timeout)
                )
            )
        results = await asyncio.gather(*tasks)
    return list(results)


def _print_summary(results: List[Dict[str, object]]) -> None:
    print("\n" + "=" * 78)
    yields = [int(r["yield"]) for r in results]
    total_jobs = sum(yields)
    productive = sum(1 for y in yields if y > 0)

    # Yield histogram
    buckets = Counter()
    for y in yields:
        if y == 0:
            buckets["0"] += 1
        elif y < 5:
            buckets["1-4"] += 1
        elif y < 10:
            buckets["5-9"] += 1
        elif y < 25:
            buckets["10-24"] += 1
        else:
            buckets["25+"] += 1
    print("YIELD HISTOGRAM")
    for key in ("0", "1-4", "5-9", "10-24", "25+"):
        print(f"  {key:>6}: {buckets.get(key, 0)}")

    # Strategy distribution
    strat = Counter(r["strategy"] for r in results if r["strategy"])
    print("\nSTRATEGY DISTRIBUTION")
    for strategy, count in strat.most_common():
        print(f"  {strategy}: {count}")

    # Failures by error type
    errors = Counter(str(r["error"]) for r in results if r["error"] and int(r["yield"]) == 0)
    print("\nFAILURES (zero-yield) BY ERROR TYPE")
    for error, count in errors.most_common():
        print(f"  {error}: {count}")

    print("\n" + "-" * 78)
    print(f"Total sources verified : {len(results)}")
    print(f"Productive (>0 jobs)   : {productive}")
    print(f"Zero-yield             : {len(results) - productive}")
    print(f"Total jobs extracted   : {total_jobs}")

    # Per-source table (sorted by yield desc)
    print("\nPER-SOURCE (top 40 by yield)")
    print(f"  {'YIELD':>5}  {'STRATEGY':<12}  {'CATEGORY':<16}  DOMAIN")
    for r in sorted(results, key=lambda x: -int(x["yield"]))[:40]:
        print(
            f"  {int(r['yield']):>5}  {str(r['strategy'] or '-'):<12}  "
            f"{str(r['category']):<16}  {r['domain']}"
        )


def _write_quarantine(results: List[Dict[str, object]]) -> None:
    zero_yield_domains = {
        str(r["domain"]) for r in results
        if int(r["yield"]) == 0 and str(r.get("error") or "") not in ("robots_disallowed", "timeout")
    }
    if not zero_yield_domains:
        print("\n--write: no zero-yield sources to quarantine (robots/timeouts excluded).")
        return

    registry_file = _registry_path()
    with open(registry_file, "r", encoding="utf-8") as f:
        raw = json.load(f)

    date_str = datetime.date.today().isoformat()
    disabled_count = 0
    for entry in raw:
        domain = str(entry.get("domain") or "").strip().lower()
        if domain in zero_yield_domains and entry.get("enabled"):
            entry["enabled"] = False
            entry["disabled_reason"] = f"zero_yield_at_verify {date_str}"
            disabled_count += 1

    if disabled_count == 0:
        print("\n--write: matched domains already disabled; nothing to write.")
        return

    fd, tmp_path = tempfile.mkstemp(
        dir=str(registry_file.parent), prefix=".overseas_sources_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, registry_file)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    print(f"\n--write: quarantined {disabled_count} zero-yield source(s) in {registry_file}")
    print("Review the diff and commit the updated registry.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify overseas source registry yields.")
    parser.add_argument("--limit", type=int, default=0, help="Verify only the first N enabled sources (0 = all).")
    parser.add_argument("--category", type=str, default=None, help="Restrict to one category.")
    parser.add_argument("--write", action="store_true", help="Disable zero-yield sources in the registry (atomic write).")
    parser.add_argument("--concurrency", type=int, default=20, help="Max concurrent source fetches.")
    parser.add_argument("--timeout-secs", type=float, default=DEFAULT_TIMEOUT_SECS, help="Per-URL fetch timeout.")
    parser.add_argument("--no-robots", action="store_true", help="Skip robots.txt checks (use with caution).")
    args = parser.parse_args()

    results = asyncio.run(
        _run(
            limit=args.limit,
            category=args.category,
            concurrency=args.concurrency,
            timeout=args.timeout_secs,
            respect_robots=not args.no_robots,
        )
    )
    if results:
        _print_summary(results)
        if args.write:
            _write_quarantine(results)


if __name__ == "__main__":
    main()

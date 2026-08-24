#!/usr/bin/env python3
"""
scripts/benchmark_overseas.py

Offline benchmark for the overseas expansion pack (manual, not CI).

Spins up a local http.server in a daemon thread serving 50 synthetic fixture
pages (10-12 DOM job cards each), points the overseas registry at a generated
temp file via OVERSEAS_REGISTRY_PATH, runs OverseasAdapter.fetch end-to-end,
then the SimHash stage, and prints:

  - wall time
  - jobs extracted
  - jobs after SimHash
  - per-strategy counts

Targets on 1 vCPU: 50 sources / >=400 jobs in < 60 s, and
SimHash of 1,000 mixed descriptions in < 2 s.

Usage:
    python scripts/benchmark_overseas.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

NUM_SOURCES = 50
CARDS_PER_PAGE = 10

_TITLE_POOL = [
    "Mason", "Electrician", "Plumber", "Carpenter", "Steel Fixer",
    "Heavy Driver", "Pipe Fitter", "Painter", "Welder", "Scaffolder",
    "Tile Fixer", "AC Technician",
]
_LOC_POOL = [
    "Dubai", "Riyadh", "Doha", "Muscat", "Manama", "Kuwait City",
    "Sharjah", "Abu Dhabi", "Jeddah", "Dammam",
]
_COUNTRY_POOL = [
    "UAE", "Saudi Arabia", "Qatar", "Oman", "Bahrain", "Kuwait",
]
_COMPANY_POOL = [
    "Al Rashid Manpower", "Desert Star Recruiting", "Gulf Horizons Employment",
    "Muscat Works Agency", "Bahrain Build Recruitment", "Falcon Overseas Jobs",
]

# Long responsibility template (~55 tokens) so SimHash actually engages.
_LONG_DESC = (
    "Responsibilities include reading blueprints, preparing materials, coordinating with site "
    "supervisors, following safety standards at all times, operating basic power tools, mixing "
    "mortar and cement, measuring and cutting materials to specification, maintaining a clean "
    "work area, completing daily progress reports, and supporting other trades as required on "
    "site. Food and accommodation provided with immediate deployment for selected candidates."
)


def _card_html(base_url: str, page_idx: int, card_idx: int, title: str, location: str, company: str, salary: int) -> str:
    slug = f"{title.lower().replace(' ', '-')}-{location.lower().replace(' ', '-')}-{card_idx}"
    return f"""    <div class="job-card">
      <a href="{base_url}/vacancies/{slug}/">{title} – {location} overseas job vacancy</a>
      <p>Company: {company} | Location: {location} | Salary: AED {salary} per month</p>
      <p>{_LONG_DESC}</p>
      <span class="date">Posted: 2026-08-{(card_idx % 28) + 1:02d}</span>
    </div>"""


def _page_html(base_url: str, page_idx: int) -> str:
    cards = []
    for i in range(CARDS_PER_PAGE):
        title = _TITLE_POOL[(page_idx + i) % len(_TITLE_POOL)]
        location = _LOC_POOL[(page_idx * 3 + i) % len(_LOC_POOL)]
        company = _COMPANY_POOL[(page_idx + i) % len(_COMPANY_POOL)]
        salary = 2000 + ((page_idx * 137 + i * 211) % 15) * 100
        cards.append(_card_html(base_url, page_idx, i, title, location, company, salary))
    return (
        "<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\">"
        f"<title>Bench Agency {page_idx} Vacancies</title></head>\n"
        "<body>\n<header><nav><a href=\"/\">Home</a> <a href=\"/about/\">About</a></nav></header>\n"
        "<main><div class=\"job-cards\">\n" + "\n".join(cards) + "\n</div></main>\n</body></html>\n"
    )


def _write_fixture_site(directory: Path, port: int) -> None:
    base_url = f"http://127.0.0.1:{port}"
    for page_idx in range(NUM_SOURCES):
        (directory / f"page_{page_idx}.html").write_text(_page_html(base_url, page_idx), encoding="utf-8")


def _write_temp_registry(directory: Path, port: int) -> Path:
    entries = []
    for page_idx in range(NUM_SOURCES):
        entries.append({
            "domain": f"bench-{page_idx}.localhost",
            "start_urls": [f"http://127.0.0.1:{port}/page_{page_idx}.html"],
            "category": "manpower_agency",
            "tier": "1",
            "enabled": True,
            "country": _COUNTRY_POOL[page_idx % len(_COUNTRY_POOL)],
            "capabilities": {"rss": False, "sitemap": False, "wordpress": True},
        })
    path = directory / "bench_registry.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def _start_server(directory: Path) -> tuple[ThreadingHTTPServer, int]:
    class _QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, format, *args):  # noqa: A002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def _bench_simhash_standalone() -> tuple[float, int, int]:
    """SimHash 1,000 mixed descriptions (long + short + duplicates). Returns (secs, in, out)."""
    from job_radar.models.config import JobSearchConfig
    from job_radar.models.job import Job
    from job_radar.pipeline.simhash import simhash_deduplicate

    jobs = []
    for i in range(1000):
        if i % 5 == 0:
            desc = _LONG_DESC  # duplicated long text across ~200 jobs
        elif i % 3 == 0:
            desc = f"Short note {i}"
        else:
            desc = (
                f"Role {i}: we need someone to handle duties number {i} across the region, "
                f"coordinating with teams, following procedures, and delivering quality work on "
                f"schedule while observing every applicable safety rule and reporting progress to "
                f"the supervisor assigned to project {i} in location {i % 7}."
            )
        jobs.append(Job(
            id=f"ov-bench-{i}",
            source="overseas",
            ats=f"bench-{i % 50}.localhost",
            title=f"Worker {i}",
            description=desc,
            metadata={"source_domain": f"bench-{i % 50}.localhost", "description_source": "list_card"},
        ))
    cfg = JobSearchConfig(enable_overseas_sources=True, overseas_simhash_dedup=True)
    started = time.perf_counter()
    survivors, dups = simhash_deduplicate(jobs, cfg)
    elapsed = time.perf_counter() - started
    return elapsed, len(jobs), len(survivors)


def main() -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="overseas_bench_"))
    server, port = _start_server(tmpdir)
    try:
        _write_fixture_site(tmpdir, port)
        registry_path = _write_temp_registry(tmpdir, port)
        os.environ["OVERSEAS_REGISTRY_PATH"] = str(registry_path)

        from job_radar.models.config import JobSearchConfig
        from job_radar.pipeline.simhash import simhash_deduplicate
        from job_radar.sources.overseas.adapter import OverseasAdapter

        config = JobSearchConfig(
            enable_overseas_sources=True,
            overseas_max_sources_per_run=NUM_SOURCES,
            overseas_concurrency=20,
            overseas_budget_secs=60,
            overseas_fetch_details=False,
            overseas_simhash_dedup=True,
            respect_robots_txt=False,
            max_results=1000,
        )

        adapter = OverseasAdapter(config)
        started = time.perf_counter()
        jobs = asyncio.run(adapter.fetch(config))
        elapsed = time.perf_counter() - started

        strategies = Counter(j.metadata.get("extraction_strategy") for j in jobs)
        survivors, dup_count = simhash_deduplicate(jobs, config)

        print("=" * 60)
        print("OverseasAdapter benchmark")
        print("=" * 60)
        print(f"sources attempted : {adapter.stats.get('sources_attempted')}")
        print(f"failed sources    : {adapter.stats.get('failed_sources')}")
        print(f"jobs extracted    : {len(jobs)}")
        print(f"jobs after simhash: {len(survivors)} (-{dup_count} near-duplicates)")
        print(f"wall time         : {elapsed:.2f}s")
        for strategy, count in strategies.most_common():
            print(f"strategy {strategy}: {count}")

        sim_secs, sim_in, sim_out = _bench_simhash_standalone()
        print("-" * 60)
        print(f"SimHash standalone: {sim_in} mixed descriptions -> {sim_out} survivors in {sim_secs:.3f}s")
        print("-" * 60)
        ok_fetch = elapsed < 60 and len(jobs) >= 400
        ok_sim = sim_secs < 2.0
        print(f"fetch target (>=400 jobs, <60s): {'PASS' if ok_fetch else 'FAIL'}")
        print(f"simhash target (<2s for 1000)  : {'PASS' if ok_sim else 'FAIL'}")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()

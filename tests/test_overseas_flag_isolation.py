"""Flag isolation: with enable_overseas_sources off, behavior is unchanged."""
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.sources.registry import SOURCE_REGISTRY, get_enabled_sources

EXPECTED_BASELINE_NAMES = {
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "smartrecruiters",
    "personio",
    "remoteok",
    "remotive",
    "arbeitnow",
    "himalayas",
    "hn_whoshiring",
    "jobicy",
}


def test_flag_off_returns_exactly_the_12_baseline_adapters():
    cfg = JobSearchConfig()
    adapters = get_enabled_sources(cfg)
    names = {a.name for a in adapters}
    assert names == EXPECTED_BASELINE_NAMES
    assert "overseas" not in names


def test_flag_off_with_explicit_sources_has_no_overseas():
    # "overseas" is not selectable via the sources input.
    cfg = JobSearchConfig(sources=["overseas", "greenhouse"])
    adapters = get_enabled_sources(cfg)
    names = {a.name for a in adapters}
    assert names == {"greenhouse"}


def test_flag_on_adds_exactly_one_overseas_adapter():
    cfg = JobSearchConfig(enable_overseas_sources=True)
    adapters = get_enabled_sources(cfg)
    names = [a.name for a in adapters]
    assert names.count("overseas") == 1
    assert set(names) == EXPECTED_BASELINE_NAMES | {"overseas"}


def test_overseas_not_in_source_registry():
    assert "overseas" not in SOURCE_REGISTRY


def test_flag_off_output_has_no_overseas_keys():
    job = Job(
        id="x1",
        source="greenhouse",
        title="Engineer",
        company="Acme",
        description="Build things",
    )
    out = job.to_apify_dict()
    assert "sourceCategory" not in out
    assert "destinationCountry" not in out


def test_baseline_dataset_keyset_includes_core_fields():
    job = Job(
        id="x1",
        source="greenhouse",
        title="Engineer",
        company="Acme",
        description="Build things",
        country="United Kingdom",
        apply_url="https://acme.example/apply",
    )
    keys = set(job.to_apify_dict())
    for key in (
        "id",
        "title",
        "company",
        "location",
        "applyUrl",
        "source",
        "description",
        "visaSignal",
        "visaConfidence",
    ):
        assert key in keys, key


def test_overseas_job_output_includes_overseas_keys():
    job = Job(
        id="ov-x.example-abc",
        source="overseas",
        ats="x.example",
        title="Mason",
        company="Agency",
        description="Build masonry in Dubai",
        country="UAE",
        apply_url="https://x.example/jobs/1",
        metadata={
            "overseas": True,
            "source_category": "manpower_agency",
            "source_domain": "x.example",
        },
    )
    out = job.to_apify_dict()
    assert out["sourceCategory"] == "manpower_agency"
    assert out["destinationCountry"] == "UAE"


def _long_overseas_job(job_id: str, domain: str, company: str = "Agency") -> Job:
    desc = (
        "We are looking for an experienced mason to join our construction team in Dubai. "
        "Responsibilities include bricklaying, concrete work, reading blueprints, and working with "
        "site supervisors to complete villa projects on time. Food and accommodation provided. "
        "Minimum two years of Gulf experience preferred. Immediate deployment available for selected candidates."
    )
    return Job(
        id=job_id,
        source="overseas",
        ats=domain,
        title="Mason",
        company=company,
        description=desc,
        country="UAE",
        apply_url=f"https://{domain}/jobs/{job_id}",
        metadata={
            "overseas": True,
            "source_category": "manpower_agency",
            "source_domain": domain,
        },
    )


def test_pipeline_stats_include_simhash_duplicates_key_flag_off():
    import asyncio
    from unittest.mock import patch

    from job_radar.pipeline.orchestrator import run_pipeline
    from job_radar.pipeline.sink import InMemoryJobSink

    async def _test():
        config = JobSearchConfig(
            keywords=["Mason"],
            visa_sponsorship_only=False,
            max_results=10,
            enable_overseas_sources=False,
        )
        sink = InMemoryJobSink()
        jobs = [
            Job(id="gh-1", source="greenhouse", company="Acme", title="Mason", description="Masonry work"),
        ]
        with patch("job_radar.pipeline.orchestrator.fetch_all_sources") as mock_fetch:
            mock_fetch.return_value = (jobs, ["greenhouse"], [])
            result = await run_pipeline(config, sink)
        assert "simhashDuplicates" in result.stats
        assert result.stats["simhashDuplicates"] == 0

    asyncio.run(_test())


def test_pipeline_stats_simhash_duplicates_flag_on():
    import asyncio
    from unittest.mock import patch

    from job_radar.pipeline.orchestrator import run_pipeline
    from job_radar.pipeline.sink import InMemoryJobSink

    async def _test():
        cfg = JobSearchConfig(
            keywords=["Mason"],
            visa_sponsorship_only=False,
            max_results=10,
            enable_overseas_sources=True,
            overseas_simhash_dedup=True,
        )
        sink = InMemoryJobSink()
        # Two copy-pasted JDs from different agencies: fingerprint dedupe cannot
        # catch them (different company domains), SimHash must.
        jobs = [
            _long_overseas_job("ov-a.example-1", "a.example", company="Alpha Manpower"),
            _long_overseas_job("ov-b.example-2", "b.example", company="Beta Recruiting"),
        ]
        with patch("job_radar.pipeline.orchestrator.fetch_all_sources") as mock_fetch:
            mock_fetch.return_value = (jobs, ["overseas"], [])
            result = await run_pipeline(cfg, sink)
        assert result.stats["simhashDuplicates"] == 1
        assert result.stats["totalEmitted"] == 1

    asyncio.run(_test())

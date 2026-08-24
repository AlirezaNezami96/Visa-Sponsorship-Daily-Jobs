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

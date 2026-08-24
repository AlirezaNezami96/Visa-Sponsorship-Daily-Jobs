"""Tests for the SimHash near-duplicate dedup stage.

These tests guard against the specific failure mode of the previous broken
draft: hashing empty/short text collapses every job to hash 0 and dedupes
the entire run down to ~1 job. That must never happen again.
"""
from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.pipeline.simhash import (
    MIN_TOKENS,
    hamming_distance,
    simhash_deduplicate,
    simhash_value,
    _normalize,
    _shingles,
)

LONG_JD = (
    "We are looking for an experienced mason to join our construction team in Dubai. "
    "Responsibilities include bricklaying, concrete work, reading blueprints, and working with "
    "site supervisors to complete villa projects on time. Food and accommodation provided. "
    "Minimum two years of Gulf experience preferred. Immediate deployment available for selected candidates. "
    "The ideal candidate has strong knowledge of construction safety standards, can operate basic power "
    "tools, and is comfortable working outdoors in hot weather conditions. Duties also involve measuring "
    "and cutting materials to specification, mixing mortar and cement, and maintaining a clean and safe "
    "work area at all times while following the site foreman instructions carefully every day."
)
DIFFERENT_JD = (
    "Senior software engineer needed for fintech startup in Berlin. You will design and build distributed "
    "payment systems using Python and Kubernetes, lead code reviews, mentor junior engineers, and collaborate "
    "with product managers on roadmap planning. Remote friendly within Europe. Competitive salary and equity "
    "offered to the right candidate with strong system design skills and experience in modern cloud "
    "infrastructure, observability tooling, and delivering customer facing products at scale across teams."
)


def _job(desc: str, domain: str, title: str = "Mason", description_source: str = "list_card") -> Job:
    return Job(
        id=f"ov-{domain}-{abs(hash(desc + domain)) % 10**9}",
        source="overseas",
        ats=domain,
        title=title,
        description=desc,
        metadata={"source_domain": domain, "description_source": description_source},
    )


def _cfg(**kw) -> JobSearchConfig:
    kw.setdefault("enable_overseas_sources", True)
    kw.setdefault("overseas_simhash_dedup", True)
    return JobSearchConfig(**kw)


def test_identical_descriptions_from_two_domains_collapse_to_one():
    jobs = [_job(LONG_JD, "agency-a.example"), _job(LONG_JD, "agency-b.example")]
    survivors, dups = simhash_deduplicate(jobs, _cfg())
    assert len(survivors) == 1
    assert dups == 1


def test_lightly_edited_description_collapses_to_one():
    # one-token city synonym swap: must still be considered a near-duplicate
    edited = LONG_JD.replace("Dubai", "Sharjah")
    h1 = simhash_value(_shingles(_normalize(LONG_JD + " Mason")))
    h2 = simhash_value(_shingles(_normalize(edited + " Mason")))
    assert hamming_distance(h1, h2) <= 6

    jobs = [_job(LONG_JD, "agency-a.example"), _job(edited, "agency-b.example")]
    survivors, dups = simhash_deduplicate(jobs, _cfg())
    assert len(survivors) == 1
    assert dups == 1


def test_genuinely_different_descriptions_both_survive():
    jobs = [
        _job(LONG_JD, "agency-a.example", title="Mason"),
        _job(DIFFERENT_JD, "agency-b.example", title="Software Engineer"),
    ]
    survivors, dups = simhash_deduplicate(jobs, _cfg())
    assert len(survivors) == 2
    assert dups == 0


def test_short_descriptions_are_never_hashed_or_collapsed():
    # The previously broken version hashed "" -> everything collapsed to 1 job.
    # Three sub-threshold jobs must all survive.
    shorts = [
        _job("Hiring masons urgently", "a.example"),
        _job("Hiring masons urgently", "b.example"),  # even identical text
        _job("Welders wanted in Qatar", "c.example"),
    ]
    assert all(len(j.description.split()) < MIN_TOKENS for j in shorts)
    survivors, dups = simhash_deduplicate(shorts, _cfg())
    assert len(survivors) == 3
    assert dups == 0


def test_empty_description_never_collapses_with_others():
    jobs = [
        _job(LONG_JD, "a.example"),
        _job("", "b.example"),
        _job("short one", "c.example"),
    ]
    survivors, dups = simhash_deduplicate(jobs, _cfg())
    assert len(survivors) == 3
    assert dups == 0


def test_collision_keeps_longer_description():
    longer = LONG_JD + " Scaffolding."
    shorter = LONG_JD
    jobs = [_job(shorter, "short.example"), _job(longer, "long.example")]
    survivors, dups = simhash_deduplicate(jobs, _cfg())
    assert len(survivors) == 1
    assert dups == 1
    assert survivors[0].metadata["source_domain"] == "long.example"


def test_collision_tiebreak_prefers_detail_page_source():
    a = _job(LONG_JD, "list.example", description_source="list_card")
    b = _job(LONG_JD, "detail.example", description_source="detail_page")
    survivors, dups = simhash_deduplicate([a, b], _cfg())
    assert len(survivors) == 1
    assert survivors[0].metadata["description_source"] == "detail_page"


def test_threshold_zero_only_exact_hash_duplicates():
    jobs = [_job(LONG_JD, "a.example"), _job(LONG_JD, "b.example")]
    survivors, dups = simhash_deduplicate(jobs, _cfg(overseas_simhash_threshold=0))
    assert len(survivors) == 1
    assert dups == 1

"""Tests for the employer_sponsored_region visa model applied to overseas jobs."""
from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job
from job_radar.pipeline.visa import evaluate_and_filter_visa, evaluate_visa_for_job

GULF_JD = (
    "We are looking for an experienced mason to join our construction team. Responsibilities include "
    "bricklaying, concrete work and reading blueprints. Food and accommodation provided. Minimum two "
    "years of experience preferred. Immediate deployment for selected candidates from Asia and Africa "
    "who pass the trade test and medical examination arranged at our regional office."
)


def _overseas_job(desc: str = GULF_JD, country: str = "UAE", location: str = "Dubai") -> Job:
    return Job(
        id="ov-agency.example-1234abcd",
        source="overseas",
        ats="agency.example",
        title="Mason – Construction",
        company="Al Rashid Manpower",
        description=desc,
        location=location,
        country=country,
        metadata={"overseas": True, "source_domain": "agency.example", "source_category": "manpower_agency"},
    )


def _default_config(**kw) -> JobSearchConfig:
    return JobSearchConfig(**kw)


def test_gulf_overseas_job_gets_employer_sponsored_region():
    job = _overseas_job()
    result = evaluate_visa_for_job(job)
    conf = result.visa_confidence if isinstance(result.visa_confidence, str) else result.visa_confidence.value
    assert conf == "employer_sponsored_region"
    assert result.visa_sponsorship is True
    assert result.visa_type == "UAE Work Permit"
    meta = result.visa_sponsor_meta
    assert meta["model"] == "employer_sponsored_region"
    assert meta["destination_country"] == "UAE"
    assert "not a verified registry match" in meta["disclaimer"]


def test_destination_country_maps_to_specific_visa_type():
    cases = [
        ("Saudi Arabia", "Riyadh", "Saudi Work Visa (Iqama)"),
        ("Qatar", "Doha", "Qatar Work Permit"),
        ("Japan", "Tokyo", "Japan Work Visa (SSW/Engineer)"),
        ("South Korea", "Seoul", "Korea EPS E-9 Visa"),
        ("Germany", "Berlin", "Germany Work Visa / EU Blue Card"),
    ]
    for country, location, expected_visa in cases:
        job = _overseas_job(country=country, location=location)
        evaluate_visa_for_job(job)
        assert job.visa_type == expected_visa, country


def test_unknown_destination_uses_fallback_visa_type():
    job = _overseas_job(country=None, location="Somewhere Remote")
    job.location = ""
    evaluate_visa_for_job(job)
    assert job.visa_type == "Employer-sponsored work visa"


def test_overseas_job_passes_visa_sponsorship_only_filter():
    config = _default_config(visa_sponsorship_only=True)
    passed, enriched = evaluate_and_filter_visa([_overseas_job()], config)
    assert len(passed) == 1
    assert enriched == 1  # employer_sponsored_region counts as enrichment


def test_jd_explicit_sponsorship_stays_stated_in_jd():
    jd = GULF_JD + " Visa sponsorship is provided for successful candidates joining this project."
    job = _overseas_job(desc=jd)
    result = evaluate_visa_for_job(job)
    conf = result.visa_confidence if isinstance(result.visa_confidence, str) else result.visa_confidence.value
    assert conf == "stated_in_jd"


def test_jd_explicit_no_sponsorship_always_wins():
    jd = GULF_JD + " Please note: no visa sponsorship is offered; candidates must hold a valid visa."
    job = _overseas_job(desc=jd)
    result = evaluate_visa_for_job(job)
    conf = result.visa_confidence if isinstance(result.visa_confidence, str) else result.visa_confidence.value
    assert conf == "explicit_no"

    config = _default_config(visa_sponsorship_only=True, exclude_explicit_no_sponsorship=True)
    passed, _enriched = evaluate_and_filter_visa([_overseas_job(desc=jd)], config)
    assert passed == []


def test_non_overseas_job_behavior_unchanged():
    job = Job(
        id="gh-999",
        source="greenhouse",
        company="Totally Unknown Startup Inc",
        title="Backend Engineer",
        description="Build APIs and services with Go and PostgreSQL in a small product team.",
        location="Amsterdam, Netherlands",
    )
    config = _default_config(visa_sponsorship_only=True, include_unknown_visa=False)
    passed, enriched = evaluate_and_filter_visa([job], config)
    # No registry match and no overseas flag -> unknown -> filtered out, exactly as before
    assert passed == []
    assert enriched == 0

    conf = job.visa_confidence if isinstance(job.visa_confidence, str) else job.visa_confidence.value
    assert conf == "unknown"


def test_min_confidence_on_sponsor_list_excludes_employer_sponsored_region():
    config = _default_config(visa_sponsorship_only=True, min_visa_confidence="on_sponsor_list")
    passed, _ = evaluate_and_filter_visa([_overseas_job()], config)
    assert passed == []


def test_confidence_float_mapping_exists():
    from job_radar.models.job import VISA_CONFIDENCE_FLOAT_MAP

    assert VISA_CONFIDENCE_FLOAT_MAP["employer_sponsored_region"] == 0.70

    job = _overseas_job()
    evaluate_visa_for_job(job)
    d = job.to_apify_dict()
    assert d["visaSignal"] == "employer_sponsored_region"
    assert d["visaConfidence"] == 0.70

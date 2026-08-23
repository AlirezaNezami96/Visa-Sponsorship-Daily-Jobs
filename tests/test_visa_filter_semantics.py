"""Regression tests for visa sponsorship filtering semantics."""
from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job
from job_radar.pipeline.visa import evaluate_and_filter_visa


def _make_job(conf: VisaConfidence) -> Job:
    return Job(
        id=f"job-{conf.value}",
        company="TestCompany",
        title="Software Engineer",
        location="Remote",
        visa_confidence=conf,
    )


def test_visa_filter_semantics_all_cases():
    # 1. visaSponsorshipOnly=True, includeUnknownVisa=False, visaConfidence=unknown => excluded
    cfg1 = JobSearchConfig(visa_sponsorship_only=True, include_unknown_visa=False)
    passed1, _ = evaluate_and_filter_visa([_make_job(VisaConfidence.UNKNOWN)], cfg1)
    assert len(passed1) == 0

    # 2. visaSponsorshipOnly=True, includeUnknownVisa=True, visaConfidence=unknown => included
    cfg2 = JobSearchConfig(visa_sponsorship_only=True, include_unknown_visa=True)
    passed2, _ = evaluate_and_filter_visa([_make_job(VisaConfidence.UNKNOWN)], cfg2)
    assert len(passed2) == 1

    # 3. visaSponsorshipOnly=True, visaConfidence=on_sponsor_list => included
    cfg3 = JobSearchConfig(visa_sponsorship_only=True, include_unknown_visa=False)
    passed3, _ = evaluate_and_filter_visa([_make_job(VisaConfidence.ON_SPONSOR_LIST)], cfg3)
    assert len(passed3) == 1

    # 4. visaSponsorshipOnly=True, visaConfidence=stated_in_jd => included
    cfg4 = JobSearchConfig(visa_sponsorship_only=True, include_unknown_visa=False)
    passed4, _ = evaluate_and_filter_visa([_make_job(VisaConfidence.STATED_IN_JD)], cfg4)
    assert len(passed4) == 1

    # 5. visaSponsorshipOnly=True, visaConfidence=explicit_no => excluded
    cfg5 = JobSearchConfig(visa_sponsorship_only=True, include_unknown_visa=True, exclude_explicit_no_sponsorship=True)
    passed5, _ = evaluate_and_filter_visa([_make_job(VisaConfidence.EXPLICIT_NO)], cfg5)
    assert len(passed5) == 0

    # 6. visaSponsorshipOnly=False, visaConfidence=unknown => included unless min confidence excludes it
    cfg6 = JobSearchConfig(visa_sponsorship_only=False, min_visa_confidence="unknown")
    passed6, _ = evaluate_and_filter_visa([_make_job(VisaConfidence.UNKNOWN)], cfg6)
    assert len(passed6) == 1

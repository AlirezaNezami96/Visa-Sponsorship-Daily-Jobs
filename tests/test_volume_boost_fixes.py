"""Tests for volume boost, known sponsors allowlist, keyword expansion, and ATS sources."""
from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job
from job_radar.pipeline.filter import expand_keywords, filter_job, matches_keywords
from job_radar.pipeline.visa import evaluate_and_filter_visa, evaluate_visa_for_job
from job_radar.sources.ats_utils import get_curated_companies_for_ats
from job_radar.visa.evaluator import check_known_sponsor, evaluate_job_visa


def test_known_sponsors_allowlist():
    assert check_known_sponsor("Google") is not None
    assert check_known_sponsor("Google LLC") is not None
    assert check_known_sponsor("Alphabet Inc") is not None
    assert check_known_sponsor("Amazon Web Services") is not None
    assert check_known_sponsor("Meta Platforms") is not None
    assert check_known_sponsor("Anthropic") is not None
    assert check_known_sponsor("OpenAI") is not None
    assert check_known_sponsor("DeepMind") is not None
    assert check_known_sponsor("Mistral AI") is not None
    assert check_known_sponsor("Stripe") is not None
    assert check_known_sponsor("NonExistentCompany12345XYZ") is None


def test_matches_keywords_permissive():
    assert matches_keywords("Senior Software Developer", "", ["Software Engineer"]) is True
    assert matches_keywords("SWE II", "", ["Software Engineer"]) is True
    assert matches_keywords("ML Engineer", "", ["Machine Learning"]) is True
    assert matches_keywords("Android Dev", "", ["Android"]) is True
    assert matches_keywords("Staff Front-End Engineer", "", ["Frontend"]) is True
    assert matches_keywords("Head of Marketing", "Sales and marketing strategy", ["Software Engineer"]) is False


def test_expand_keywords():
    expanded = expand_keywords(["Software Engineer"])
    assert "software developer" in expanded
    assert "swe" in expanded
    assert "programmer" in expanded


def test_curated_ats_slugs():
    gh_slugs = get_curated_companies_for_ats("greenhouse")
    assert len(gh_slugs) >= 40
    lever_slugs = get_curated_companies_for_ats("lever")
    assert len(lever_slugs) >= 10
    ashby_slugs = get_curated_companies_for_ats("ashby")
    assert len(ashby_slugs) >= 10


def test_known_sponsor_in_pipeline():
    job = Job(
        id="gh-google-1",
        company="Google",
        title="Software Engineer III",
        location="London, UK",
        country="United Kingdom",
        description="Join Google engineering team.",
    )
    evaluate_visa_for_job(job)
    assert job.visa_confidence == VisaConfidence.KNOWN_SPONSOR
    assert job.visa_sponsorship is True
    assert job.visa_sponsor_meta.get("source") == "known_sponsors_allowlist"

    # Filter with visa_sponsorship_only=True
    cfg = JobSearchConfig(visa_sponsorship_only=True, include_unknown_visa=False)
    passed, enriched = evaluate_and_filter_visa([job], cfg)
    assert len(passed) == 1
    assert enriched == 1

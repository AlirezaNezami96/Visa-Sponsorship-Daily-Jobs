"""Tests for canonical domain models, enums, and dict conversions."""
import datetime
from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import AuthFit, RemoteScope, Seniority, VisaConfidence, VisaStatus
from job_radar.models.job import Job


def test_job_canonical_initialization():
    job = Job(
        id="gh-test-123",
        source="greenhouse",
        company="Stripe",
        title="Software Engineer",
        url="https://boards.greenhouse.io/stripe/jobs/123",
        location="Berlin, Germany",
        remote=True,
        seniority="senior",
        salary_min=80000,
        salary_max=110000,
        salary_currency="EUR",
        visa_confidence=VisaConfidence.ON_SPONSOR_LIST,
    )

    assert job.id == "gh-test-123"
    assert job.company_normalized == "stripe"
    assert job.remote is True
    assert job.is_remote is True
    assert job.visa_confidence == VisaConfidence.ON_SPONSOR_LIST
    assert len(job.fingerprint) == 64  # SHA256 hex


def test_job_to_apify_dict_camel_case():
    posted_time = datetime.datetime(2026, 8, 20, 10, 0, 0, tzinfo=datetime.timezone.utc)
    job = Job(
        id="lever-abc",
        source="lever",
        company="Example Corp, Inc.",
        title="AI Engineer",
        url="https://jobs.lever.co/example/abc",
        location="London, UK",
        remote=True,
        remote_type=RemoteScope.REGION_RESTRICTED,
        employment_type="full_time",
        seniority="junior",
        salary_min=60000,
        salary_max=85000,
        salary_currency="GBP",
        posted_at=posted_time,
        technologies=["Python", "PyTorch"],
        visa_confidence=VisaConfidence.STATED_IN_JD,
        visa_type="UK Skilled Worker",
        visa_sponsor_meta={"rating": "A", "matched_sponsor": "Example Corp"},
        relevance_score=0.95,
        composite_score=0.88,
        classification_reason="Core machine learning role",
        description="Great AI job description",
    )

    data = job.to_apify_dict(include_description=True, include_raw_metadata=False)

    # Verify camelCase keys
    assert data["companyNormalized"] == "example"
    assert data["remoteType"] == "region_restricted"
    assert data["employmentType"] == "full_time"
    assert data["salaryMin"] == 60000
    assert data["salaryMax"] == 85000
    assert data["salaryCurrency"] == "GBP"
    assert data["applyUrl"] == "https://jobs.lever.co/example/abc"
    assert data["visaSponsorship"] is True
    assert data["visaConfidence"] == "stated_in_jd"
    assert data["visaType"] == "UK Skilled Worker"
    assert data["visaSponsorMeta"]["rating"] == "A"
    assert data["relevanceScore"] == 0.95
    assert data["compositeScore"] == 0.88
    assert data["classificationReason"] == "Core machine learning role"
    assert data["description"] == "Great AI job description"


def test_job_legacy_conversion_roundtrip():
    legacy_dict = {
        "id": "gh-12345",
        "company": "DeepMind",
        "title": "Research Scientist",
        "url": "https://deepmind.google/jobs/123",
        "location": "London, UK",
        "remote": False,
        "description": "Frontier AI research",
        "visa_status": "sponsors",
        "classified_track": "engineer",
        "relevance_score": 90,
        "why_matched": "Matches AI track",
    }

    job = Job.from_legacy_dict(legacy_dict)
    assert job.company == "DeepMind"
    assert job.company_normalized == "deepmind"
    assert job.title == "Research Scientist"
    assert job.visa_confidence == VisaConfidence.STATED_IN_JD
    assert job.relevance_score == 90

    back_to_dict = job.to_legacy_dict()
    assert back_to_dict["location"] == "London, UK"
    assert back_to_dict["visa_sponsorship"] is True
    assert back_to_dict["classified_track"] == "engineer"
    assert back_to_dict["_fingerprint"] == job.fingerprint

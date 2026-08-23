"""Tests for pipeline filtering rules."""
import datetime
from job_radar.models.config import JobSearchConfig
from job_radar.models.enums import VisaConfidence
from job_radar.models.job import Job
from job_radar.pipeline.filter import filter_job, is_job_fresh


def test_freshness_filter():
    now = datetime.datetime.now(datetime.timezone.utc)
    recent_job = Job(id="1", company="A", title="T", location="Remote", posted_at=now - datetime.timedelta(days=2))
    stale_job = Job(id="2", company="B", title="T", location="Remote", posted_at=now - datetime.timedelta(days=45))

    assert is_job_fresh(recent_job, max_age_days=30) is True
    assert is_job_fresh(stale_job, max_age_days=30) is False


def test_keyword_and_exclusion_filter():
    config = JobSearchConfig(
        keywords=["Android", "Kotlin"],
        exclude_keywords=["Manager", "Director"],
    )

    matching_job = Job(id="1", company="A", title="Senior Android Developer", description="Uses Kotlin daily", location="Remote")
    excluded_job = Job(id="2", company="B", title="Engineering Manager - Android", description="Lead team", location="Remote")
    irrelevant_job = Job(id="3", company="C", title="Frontend React Engineer", description="TypeScript only", location="Remote")

    assert filter_job(matching_job, config) is True
    assert filter_job(excluded_job, config) is False
    assert filter_job(irrelevant_job, config) is False


def test_remote_and_country_filter():
    config = JobSearchConfig(
        remote_only=True,
        countries=["Germany", "United Kingdom"],
    )

    remote_germany = Job(id="1", company="A", title="SWE", location="Berlin, Germany", remote=True)
    onsite_germany = Job(id="2", company="B", title="SWE", location="Munich, Germany", remote=False)
    remote_japan = Job(id="3", company="C", title="SWE", location="Tokyo, Japan", remote=True)

    assert filter_job(remote_germany, config) is True
    assert filter_job(onsite_germany, config) is False
    assert filter_job(remote_japan, config) is False


def test_salary_floor_filter():
    config = JobSearchConfig(min_salary=80000)

    good_salary = Job(id="1", company="A", title="SWE", location="Remote", salary_min=90000, salary_max=120000)
    low_salary = Job(id="2", company="B", title="SWE", location="Remote", salary_min=50000, salary_max=70000)
    unstated_salary = Job(id="3", company="C", title="SWE", location="Remote", salary_min=None, salary_max=None)

    assert filter_job(good_salary, config) is True
    assert filter_job(low_salary, config) is False
    assert filter_job(unstated_salary, config) is True  # Fails open for unstated salary

"""Tests for Visa Intelligence evaluator and priority rules."""
from job_radar.models.enums import AuthFit, VisaConfidence
from job_radar.visa.evaluator import VisaEvaluator
from job_radar.visa.models import SponsorRecord
from job_radar.visa.normalizer import normalize_company_name


def test_normalize_company_name():
    assert normalize_company_name("Google LLC") == "google"
    assert normalize_company_name("DeepMind Technologies Ltd.") == "deepmind"
    assert normalize_company_name("Example GMBH") == "example"
    assert normalize_company_name("Stripe, Inc.") == "stripe"


def test_visa_priority_explicit_no_wins():
    evaluator = VisaEvaluator()
    # Mock sponsor database
    evaluator._sponsors = {
        "stripe": SponsorRecord(
            normalized_name="stripe",
            country="GB",
            legal_name="Stripe Payments UK Limited",
            rating="A",
            routes=["Skilled Worker"],
            source="govuk_register",
        )
    }
    evaluator._aliases = {}

    # Job from a licensed sponsor, but JD explicitly refuses sponsorship
    job = {
        "company": "Stripe",
        "title": "Software Engineer",
        "location": "London, UK",
        "description": "We are looking for engineers. Must already have the right to work. No visa sponsorship provided.",
    }

    conf, auth, meta = evaluator.evaluate_job(job)
    assert conf == VisaConfidence.EXPLICIT_NO
    assert auth == AuthFit.INELIGIBLE


def test_visa_priority_stated_in_jd_positive():
    evaluator = VisaEvaluator()
    evaluator._sponsors = {}
    evaluator._aliases = {}

    job = {
        "company": "Some Unknown Startup",
        "title": "Staff AI Engineer",
        "location": "Berlin, Germany",
        "description": "Join our team! Full visa sponsorship and relocation package is provided.",
    }

    conf, auth, meta = evaluator.evaluate_job(job)
    assert conf == VisaConfidence.STATED_IN_JD
    assert auth == AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE


def test_visa_priority_on_sponsor_list():
    evaluator = VisaEvaluator()
    norm_name = normalize_company_name("Acme Innovations UK Ltd")
    evaluator._sponsors = {
        norm_name: SponsorRecord(
            normalized_name=norm_name,
            country="GB",
            legal_name="Acme Innovations UK Ltd",
            rating="A",
            routes=["Skilled Worker"],
            source="govuk_register",
        )
    }
    evaluator._aliases = {}

    job = {
        "company": "Acme Innovations UK Ltd",
        "title": "Research Engineer",
        "location": "London, UK",
        "description": "Work on backend systems.",
    }

    conf, auth, meta = evaluator.evaluate_job(job)
    assert conf == VisaConfidence.ON_SPONSOR_LIST
    assert auth == AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE
    assert meta.get("rating") == "A"


def test_visa_known_sponsor_fast_path():
    evaluator = VisaEvaluator()
    job = {
        "company": "DeepMind",
        "title": "Research Engineer",
        "location": "London, UK",
        "description": "Work on frontier AGI problems.",
    }

    conf, auth, meta = evaluator.evaluate_job(job)
    assert conf == VisaConfidence.KNOWN_SPONSOR
    assert auth == AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE
    assert meta.get("source") == "known_sponsors_allowlist"

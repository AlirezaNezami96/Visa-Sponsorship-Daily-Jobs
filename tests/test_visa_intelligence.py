"""Unit tests for Visa Intelligence: normalizer, UK/US ingestors, and evaluator."""
import json
import pytest
from pathlib import Path

from job_radar.visa.models import VisaConfidence, AuthFit, SponsorRecord
from job_radar.visa.normalizer import normalize_company_name, match_company_to_sponsor
from job_radar.visa.db import init_sponsor_db, bulk_upsert_sponsors, load_all_sponsors
from job_radar.visa.ingest_uk import parse_uk_csv_stream
from job_radar.visa.ingest_us import aggregate_lca_records
from job_radar.visa.evaluator import VisaEvaluator


def test_normalize_company_name():
    assert normalize_company_name("Google LLC") == "google"
    assert normalize_company_name("DeepMind Technologies Ltd.") == "deepmind"
    assert normalize_company_name("Allegro Sp. z o.o.") == "allegro"
    assert normalize_company_name("Poznań Systems GmbH") == "poznan systems"
    assert normalize_company_name("Stripe, Inc.") == "stripe"


def test_match_company_to_sponsor():
    sponsors = {
        "deepmind": SponsorRecord(
            normalized_name="deepmind",
            country="UK",
            legal_name="DeepMind Technologies Ltd",
            routes=["Skilled Worker"],
            rating="A",
            source="govuk_register",
            as_of="2026-08-01",
        ),
        "google": SponsorRecord(
            normalized_name="google",
            country="US",
            legal_name="Google LLC",
            routes=["H-1B"],
            rating="Certified",
            source="dol_lca",
            as_of="2026-08-01",
        ),
    }

    # Exact match
    rec, method = match_company_to_sponsor("DeepMind", sponsors)
    assert rec is not None
    assert rec.legal_name == "DeepMind Technologies Ltd"
    assert method == "exact"

    # Alias / normalized match
    rec, method = match_company_to_sponsor("Google LLC", sponsors)
    assert rec is not None
    assert rec.legal_name == "Google LLC"

    # False positive prevention: "Data Ltd" should NOT match "DataRobot"
    sponsors["datarobot"] = SponsorRecord(
        normalized_name="datarobot",
        country="US",
        legal_name="DataRobot Inc",
        routes=["H-1B"],
    )
    rec, method = match_company_to_sponsor("Data Ltd", sponsors)
    assert rec is None
    assert method == "none"


def test_uk_csv_parsing():
    sample_csv = """Organisation Name,Town/City,County,Type & Rating,Route
DeepMind Technologies Ltd,London,,Worker (A rating),Skilled Worker
Bad Rating Ltd,Manchester,,Worker (B rating),Skilled Worker
Temp Worker Only Ltd,Bristol,,Temporary Worker (A rating),Seasonal Worker
Invalid Company Name,,,,
"""
    records = parse_uk_csv_stream(sample_csv, as_of_date="2026-08-20")
    assert len(records) == 2

    # Verify A rating
    deepmind = next(r for r in records if r.normalized_name == "deepmind")
    assert deepmind.rating == "A"
    assert "Skilled Worker" in deepmind.routes

    # Verify B rating has licence warning
    bad = next(r for r in records if r.normalized_name == "bad rating")
    assert "licence_warning" in bad.rating


def test_us_lca_aggregation():
    sample_rows = [
        {"EMPLOYER_NAME": "Stripe Inc", "CASE_STATUS": "Certified", "WAGE_RATE_OF_PAY_FROM": "180000", "JOB_TITLE": "Software Engineer", "VISA_CLASS": "H-1B"},
        {"EMPLOYER_NAME": "Stripe Inc", "CASE_STATUS": "Certified", "WAGE_RATE_OF_PAY_FROM": "200000", "JOB_TITLE": "Software Engineer", "VISA_CLASS": "H-1B"},
        {"EMPLOYER_NAME": "Stripe Inc", "CASE_STATUS": "Denied", "WAGE_RATE_OF_PAY_FROM": "150000", "JOB_TITLE": "Designer", "VISA_CLASS": "H-1B"},
    ]
    records = aggregate_lca_records(sample_rows)
    assert len(records) == 1
    stripe = records[0]
    assert stripe.normalized_name == "stripe"
    assert stripe.extra["lca_count_12m"] == 2
    assert stripe.extra["median_wage"] == 190000 or stripe.extra["median_wage"] in (180000, 200000)


def test_visa_evaluator_priorities(tmp_path):
    db_file = tmp_path / "test_sponsors.db"
    init_sponsor_db(db_file)

    # Insert verified sponsor
    bulk_upsert_sponsors(
        [
            SponsorRecord(
                normalized_name="amazon",
                country="UK",
                legal_name="Amazon UK Services Ltd",
                routes=["Skilled Worker"],
                rating="A",
                source="govuk_register",
            )
        ],
        db_path=db_file,
    )

    evaluator = VisaEvaluator(db_path=db_file)

    # Test 1: Explicit NO beats on_sponsor_list
    job_explicit_no = {
        "company": "Amazon",
        "title": "Software Engineer",
        "location": "London, UK",
        "description": "We are looking for an engineer. Unfortunately, we cannot sponsor visas for this role. Must already have right to work in the UK.",
        "remote_scope": "hybrid",
    }
    v_conf, auth_fit, meta = evaluator.evaluate_job(job_explicit_no)
    assert v_conf == VisaConfidence.EXPLICIT_NO
    assert auth_fit == AuthFit.INELIGIBLE

    # Test 2: On sponsor list (no explicit disclaimer)
    job_on_list = {
        "company": "Amazon",
        "title": "Software Engineer",
        "location": "London, UK",
        "description": "Join our London team to build scalable services in AWS.",
        "remote_scope": "hybrid",
    }
    v_conf, auth_fit, meta = evaluator.evaluate_job(job_on_list)
    assert v_conf == VisaConfidence.ON_SPONSOR_LIST
    assert auth_fit == AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE
    assert meta["matched_sponsor"] == "Amazon UK Services Ltd"

    # Test 3: Stated in JD
    job_stated_in_jd = {
        "company": "Unknown Startup",
        "title": "AI Engineer",
        "location": "Berlin, Germany",
        "description": "Full visa sponsorship and relocation assistance provided for EU Blue Card holders.",
        "remote_scope": "onsite",
    }
    v_conf, auth_fit, meta = evaluator.evaluate_job(job_stated_in_jd)
    assert v_conf == VisaConfidence.STATED_IN_JD
    assert auth_fit == AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE

    # Test 4: Worldwide remote
    job_worldwide = {
        "company": "Global Tech",
        "title": "Backend Developer",
        "location": "Worldwide",
        "description": "Work from anywhere in the world.",
        "remote_scope": "worldwide",
    }
    v_conf, auth_fit, meta = evaluator.evaluate_job(job_worldwide)
    assert auth_fit == AuthFit.REMOTE_OK

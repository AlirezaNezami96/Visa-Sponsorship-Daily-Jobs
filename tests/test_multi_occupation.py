"""
tests/test_multi_occupation.py

Master 10-Occupation Family Fixture Test Suite & Standing CI Regression Test.
Verifies that Visa Lane treats all 10 major global occupation families with full parity:
  1. Healthcare
  2. Skilled Trades & Construction
  3. Hospitality & Culinary
  4. Finance & Accounting
  5. Manufacturing & Operations
  6. Logistics & Supply Chain
  7. Education & Academia
  8. Agriculture & Energy
  9. Public Sector & Non-Profit
  10. Technology & Software

STANDING CI RULE:
Zero legitimate jobs from ANY occupation family may ever be rejected by classification or ingestion filters.
"""
from __future__ import annotations

import pytest

from job_radar.classifiers.relevance import classify_and_filter_jobs
from job_radar.config import ClassifierConfig, GeographyConfig, RadarConfig
from job_radar.employers.model import Employer
from job_radar.employers.resolver import EmployerResolver
from job_radar.models.job import Job
from job_radar.taxonomy import normalize_job_posting
from job_radar.visa.confidence import (
    ConfidenceTier,
    EvidenceProvenance,
    evaluate_sponsorship_confidence,
)
from job_radar.visa.gulf_kafala import evaluate_gulf_sponsorship

OCCUPATION_FAMILY_FIXTURES = [
    # 1. Healthcare
    {
        "family": "Healthcare",
        "title": "Clinical Nurse Specialist - Critical Care / ICU",
        "company": "Barts Health NHS Trust",
        "country": "UK",
        "location": "London, United Kingdom",
        "description": "We are seeking an experienced Critical Care Nurse. Full visa sponsorship provided under the UK Health and Care Worker Visa route. BLS/ACLS required.",
        "expected_isco_code": "2221",
        "expected_major_group": "2",
        "expected_tier": ConfidenceTier.VERIFIED,
        "gov_record": {"source": "GOV.UK Register", "rating": "A (Skilled Worker)", "routes": ["Health and Care Worker Visa"]},
    },
    # 2. Skilled Trades & Construction
    {
        "family": "Skilled Trades & Construction",
        "title": "Journeyman Heavy Industrial Electrician",
        "company": "Stantec Canada",
        "country": "CA",
        "location": "Calgary, Canada",
        "description": "Red Seal certified industrial electrician needed for clean energy projects. Positive LMIA support available for eligible international tradespeople.",
        "expected_isco_code": "7411",
        "expected_major_group": "7",
        "expected_tier": ConfidenceTier.HIGH,
        "gov_record": None,
    },
    # 3. Hospitality & Culinary
    {
        "family": "Hospitality & Culinary",
        "title": "Executive Sous Chef",
        "company": "Jumeirah Luxury Hotels",
        "country": "AE",
        "location": "Dubai, United Arab Emirates",
        "description": "Leading 5-star resort in Dubai seeking an Executive Sous Chef. Full employment visa, annual flights, medical insurance, and accommodation provided.",
        "expected_isco_code": "3434",
        "expected_major_group": "3",
        "expected_tier": ConfidenceTier.HIGH,
        "gov_record": None,
    },
    # 4. Finance & Accounting
    {
        "family": "Finance & Accounting",
        "title": "Senior Chartered Accountant (Audit & Assurance)",
        "company": "KPMG Australia",
        "country": "AU",
        "location": "Sydney, Australia",
        "description": "CPA/CA certified auditor needed. Subclass 482 (TSS) Standard Business Sponsorship provided for qualified international applicants.",
        "expected_isco_code": "2411",
        "expected_major_group": "2",
        "expected_tier": ConfidenceTier.VERIFIED,
        "gov_record": {"source": "Home Affairs SBS", "rating": "Approved Standard Business Sponsor", "routes": ["Subclass 482 (TSS)"]},
    },
    # 5. Manufacturing & Operations
    {
        "family": "Manufacturing & Operations",
        "title": "Precision CNC Machinist & Toolmaker",
        "company": "Siemens Energy",
        "country": "DE",
        "location": "Munich, Germany",
        "description": "Experienced CNC 5-axis operator and precision toolmaker. EU Blue Card work permit sponsorship supported.",
        "expected_isco_code": "7222",
        "expected_major_group": "7",
        "expected_tier": ConfidenceTier.HIGH,
        "gov_record": None,
    },
    # 6. Logistics & Supply Chain
    {
        "family": "Logistics & Supply Chain",
        "title": "Heavy Truck Driver (HGV Class 1 / CDL)",
        "company": "Mainfreight New Zealand",
        "country": "NZ",
        "location": "Auckland, New Zealand",
        "description": "Class 5 / HGV driver needed for inter-island routes. Accredited Employer Work Visa (AEWV) sponsorship offered.",
        "expected_isco_code": "8332",
        "expected_major_group": "8",
        "expected_tier": ConfidenceTier.VERIFIED,
        "gov_record": {"source": "INZ Accredited Register", "rating": "Accredited", "routes": ["AEWV"]},
    },
    # 7. Education & Academia
    {
        "family": "Education & Academia",
        "title": "Assistant Professor of Data Science and Economics",
        "company": "National University of Singapore",
        "country": "SG",
        "location": "Singapore",
        "description": "Tenure-track faculty position. Full Employment Pass (EP) work visa sponsorship provided for international scholars.",
        "expected_isco_code": "2310",
        "expected_major_group": "2",
        "expected_tier": ConfidenceTier.HIGH,
        "gov_record": None,
    },
    # 8. Agriculture & Energy
    {
        "family": "Agriculture & Energy",
        "title": "Subsea Petroleum Engineer / Sondage pétrolier",
        "company": "TotalEnergies",
        "country": "UK",
        "location": "Aberdeen, United Kingdom",
        "description": "Offshore drilling and reservoir petroleum engineer. Skilled Worker visa sponsorship and relocation support provided.",
        "expected_isco_code": "2146",
        "expected_major_group": "2",
        "expected_tier": ConfidenceTier.HIGH,
        "gov_record": None,
    },
    # 9. Public Sector & Non-Profit
    {
        "family": "Public Sector & Non-Profit",
        "title": "Senior Policy Analyst - Climate Regulation",
        "company": "International Renewable Energy Agency",
        "country": "DE",
        "location": "Bonn, Germany",
        "description": "Global environmental policy analyst. International treaty and work authorization support provided.",
        "expected_isco_code": "2422",
        "expected_major_group": "2",
        "expected_tier": ConfidenceTier.HIGH,
        "gov_record": None,
    },
    # 10. Technology & Software
    {
        "family": "Technology & Software",
        "title": "Senior Mobile Engineer (Flutter & Android)",
        "company": "Spotify",
        "country": "SE",
        "location": "Stockholm, Sweden",
        "description": "Mobile engineer building cross-platform audio experiences. Full Swedish work permit sponsorship and international relocation package.",
        "expected_isco_code": "2512",
        "expected_major_group": "2",
        "expected_tier": ConfidenceTier.HIGH,
        "gov_record": None,
    },
]


def test_all_ten_occupation_families_normalize_and_classify():
    """
    CRITICAL STANDING TEST:
    Verify that all 10 occupation families normalize to accurate ISCO-08 codes
    and evaluate with high-confidence, explainable visa intelligence.
    """
    resolver = EmployerResolver()

    test_cfg = RadarConfig(
        classifier=ClassifierConfig(enabled=False, min_relevance_score=50),
        geography=GeographyConfig(allowed_remote_scopes=["worldwide", "region_restricted", "onsite_only", "onsite", "hybrid"]),
    )

    jobs_payload = []
    for fixture in OCCUPATION_FAMILY_FIXTURES:
        jobs_payload.append({
            "title": fixture["title"],
            "company": fixture["company"],
            "location": fixture["location"],
            "description": fixture["description"],
            "country": fixture["country"],
        })

    passed_jobs, stats = classify_and_filter_jobs(jobs_payload, config=test_cfg)

    # 1. Assert 100% pass rate across all 10 occupation families
    assert stats["passed"] == 10, f"Expected all 10 families to pass, got {stats['passed']}. Stats: {stats}"
    assert len(passed_jobs) == 10

    # 2. Check each occupation family's taxonomy and evidence individually
    for fixture in OCCUPATION_FAMILY_FIXTURES:
        job = next(j for j in passed_jobs if fixture["company"] in j["company"])

        # Check ISCO Code mapping
        assert job["isco_code"] == fixture["expected_isco_code"], (
            f"Family '{fixture['family']}': expected ISCO {fixture['expected_isco_code']}, got {job.get('isco_code')} ({job.get('isco_title')})"
        )
        assert job["isco_major_group_code"] == fixture["expected_major_group"]

        # Check 5-Tier Sponsorship Confidence
        eval_result = evaluate_sponsorship_confidence(
            employer_name=fixture["company"],
            job_description=fixture["description"],
            country=fixture["country"],
            isco_code=job["isco_code"],
            government_match=fixture["gov_record"],
        )

        assert eval_result.tier == fixture["expected_tier"], (
            f"Family '{fixture['family']}': expected tier {fixture['expected_tier']}, got {eval_result.tier}. Explanation: {eval_result.explanation}"
        )
        assert len(eval_result.evidence) > 0
        assert len(eval_result.explanation) > 10

        # Check Employer Entity Resolution
        emp, conf, method = resolver.resolve(name=fixture["company"], country=fixture["country"])
        assert emp is not None
        assert emp.canonical_name == fixture["company"]


def test_gulf_kafala_evaluation_engine():
    """Verify calibrated GCC work-permit evidence for UAE and Saudi Arabia."""
    # UAE Expatriate Perk package
    uae_res = evaluate_gulf_sponsorship(
        employer_name="Emirates Group",
        country_code="AE",
        job_description="Flight ticket, furnished accommodation, and UAE employment visa provided.",
        job_title="Hotel Manager",
    )
    assert uae_res.tier == ConfidenceTier.HIGH
    assert "annual flight tickets" in uae_res.evidence[0].description
    assert uae_res.eligible_visa_routes == ["UAE Employment Residence Visa"]

    # Local Quota / Emiratisation Refusal
    uae_refusal = evaluate_gulf_sponsorship(
        employer_name="Dubai Islamic Bank",
        country_code="AE",
        job_description="This position is strictly open to UAE Nationals Only (Emiratisation role).",
        job_title="Branch Accountant",
    )
    assert uae_refusal.tier == ConfidenceTier.NEGATIVE
    assert uae_refusal.score == 0.0

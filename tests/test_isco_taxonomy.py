"""
tests/test_isco_taxonomy.py

Comprehensive tests for the ISCO-08 global occupation taxonomy,
title normalization, skill/credential extraction, and occupation-agnostic classification.
"""
from __future__ import annotations

import pytest

from job_radar.classifiers.relevance import classify_and_filter_jobs, classify_single_job
from job_radar.models.job import Job
from job_radar.taxonomy import (
    ISCO_MAJOR_GROUPS,
    ISCO_UNIT_GROUPS,
    detect_sponsorship_language,
    extract_employment_type,
    extract_remote_scope,
    extract_seniority,
    extract_skills_from_text,
    get_country_specific_occupation_code,
    lookup_isco_by_code,
    normalize_job_posting,
    normalize_location,
    normalize_title_string,
    search_isco_by_keywords,
)


def test_isco_major_groups_structure():
    """Verify all 10 ISCO-08 major groups are registered."""
    assert len(ISCO_MAJOR_GROUPS) == 10
    assert ISCO_MAJOR_GROUPS["1"] == "Managers"
    assert ISCO_MAJOR_GROUPS["2"] == "Professionals"
    assert ISCO_MAJOR_GROUPS["7"] == "Craft and Related Trades Workers"


def test_title_normalization_and_isco_mapping():
    """Verify distinct occupational titles map accurately to ISCO unit groups."""
    test_cases = [
        # Healthcare
        ("Senior RN — ICU (REQ-99281)", "2221", "Nursing Professionals", "2"),
        ("Staff Physician / Cardiologist", "2212", "Specialist Medical Practitioners", "2"),
        ("Hospital Pharmacist", "2262", "Pharmacists", "2"),
        # Engineering & Sciences
        ("Civil & Structural Engineer - Bridges", "2142", "Civil Engineers", "2"),
        ("Sondage pétrolier — ingénieur de forage", "2146", "Mining, Metallurgical and Petroleum Engineers", "2"),
        ("Industrial Process Engineer", "2141", "Industrial and Production Engineers", "2"),
        # Skilled Trades
        ("Licensed Master Electrician", "7411", "Building and Related Electricians", "7"),
        ("TIG / MIG Pipe Welder", "7212", "Welders and Flamecutters", "7"),
        ("Journeyman Carpenter", "7115", "Carpenters and Joiners", "7"),
        # Hospitality
        ("Executive Pastry Chef", "3434", "Chefs", "3"),
        ("General Manager - Luxury Hotel", "1411", "Hotel Managers", "1"),
        # Finance & Business
        ("Senior Chartered Accountant (CPA)", "2411", "Accountants", "2"),
        ("Investment Analyst", "2412", "Financial and Investment Advisers", "2"),
        # Technology
        ("Senior Mobile Engineer (Android & Flutter)", "2512", "Software Developers", "2"),
        ("Machine Learning & AI Research Scientist", "2519", "Software and Applications Developers and Analysts Not Elsewhere Classified", "2"),
        # Logistics & Education
        ("Heavy Truck Driver (HGV Class 1)", "8332", "Heavy Truck and Lorry Drivers", "8"),
        ("University Assistant Professor of Economics", "2310", "University and Higher Education Teachers", "2"),
    ]

    for raw_title, expected_code, expected_title, expected_major in test_cases:
        norm_title = normalize_title_string(raw_title)
        matches = search_isco_by_keywords(f"{norm_title} {raw_title}")
        assert len(matches) > 0, f"Failed to match ISCO code for: {raw_title}"
        top_unit, confidence = matches[0]
        assert top_unit.code == expected_code, f"Expected {expected_code} for '{raw_title}', got {top_unit.code} ({top_unit.title})"
        assert top_unit.major_group_code == expected_major


def test_country_crosswalks_anzsco_noc_onet():
    """Verify ISCO codes crosswalk to Australia ANZSCO, Canada NOC, and US ONET."""
    # Nurse (ISCO 2221) -> Canada NOC 31301 / Australia ANZSCO 254411
    ca_crosswalk = get_country_specific_occupation_code("2221", "Canada")
    assert ca_crosswalk is not None
    assert ca_crosswalk["system"] == "NOC_2021"
    assert "31301" in ca_crosswalk["codes"] or "31300" in ca_crosswalk["codes"]

    au_crosswalk = get_country_specific_occupation_code("2221", "Australia")
    assert au_crosswalk is not None
    assert au_crosswalk["system"] == "ANZSCO"
    assert "254411" in au_crosswalk["codes"]

    us_crosswalk = get_country_specific_occupation_code("2221", "US")
    assert us_crosswalk is not None
    assert us_crosswalk["system"] == "ONET_SOC_2019"
    assert "29-1141.00" in us_crosswalk["codes"]


def test_seniority_extraction():
    """Verify seniority extraction is decoupled from occupation."""
    assert extract_seniority("Senior Nurse Practitioner")[0] == "senior"
    assert extract_seniority("Junior Welder Apprentice")[0] == "junior"
    assert extract_seniority("Lead Hotel Manager")[0] == "lead"
    assert extract_seniority("Graduate Accountant (0-2 years exp)")[0] == "junior"
    assert extract_seniority("Clinical Pharmacist")[0] == "unspecified"


def test_remote_scope_and_location():
    """Verify remote scope and location canonicalization."""
    scope, is_remote, is_hybrid, regions = extract_remote_scope("London, UK", "Work from anywhere worldwide")
    assert scope == "worldwide"
    assert is_remote is True

    country, city = normalize_location("Toronto, Canada")
    assert country == "CA"
    assert "Toronto" in city

    country, city = normalize_location("Berlin, Germany")
    assert country == "DE"


def test_skill_and_credential_extraction():
    """Verify sector-aware named skill and license extraction."""
    # Healthcare JD
    nurse_jd = "Requirements: Active BLS and ACLS certification. Experience with ICU patient care and Epic EHR."
    skills = extract_skills_from_text(nurse_jd, target_sector="healthcare")
    assert "BLS" in skills["credentials"]
    assert "ACLS" in skills["credentials"]
    assert "ICU" in skills["technical_skills"]

    # Trades JD
    welder_jd = "Looking for a Journeyman welder with Red Seal certification, skilled in TIG Welding and Blueprint Reading."
    trades_skills = extract_skills_from_text(welder_jd, target_sector="trades_and_construction")
    assert "Red Seal" in trades_skills["credentials"]
    assert "TIG Welding" in trades_skills["technical_skills"]


def test_sponsorship_language_independent_from_occupation():
    """Verify sponsorship language extraction works on non-tech postings."""
    # Explicit refusal
    text_no = "Must already have the right to work in the UK without sponsorship. No visa sponsorship provided."
    has_spons, s_type, quotes = detect_sponsorship_language(text_no)
    assert has_spons is True
    assert s_type == "explicit_refusal"

    # Positive offer
    text_yes = "We provide full visa sponsorship (Skilled Worker Visa) and relocation assistance."
    has_spons, s_type, quotes = detect_sponsorship_language(text_yes)
    assert has_spons is True
    assert s_type == "offers_sponsorship"


def test_occupation_agnostic_classification_end_to_end():
    """
    CRITICAL REGRESSION TEST:
    Verify that postings from diverse non-tech occupation families (Healthcare, Trades, Hospitality, Finance)
    pass through classification with high relevance scores and valid ISCO taxonomy metadata.
    """
    jobs = [
        {
            "title": "Senior Registered Nurse - ICU",
            "company": "NHS Trust",
            "location": "London, UK",
            "description": "We are seeking an experienced ICU Nurse. Full visa sponsorship under the Health and Care Worker Visa is available. Must hold BLS/ACLS.",
        },
        {
            "title": "Journeyman Electrician",
            "company": "Pacific Power Ltd",
            "location": "Vancouver, Canada",
            "description": "Red Seal or Journeyman licensed industrial electrician needed for major infrastructure projects. LMIA support provided.",
        },
        {
            "title": "Executive Sous Chef",
            "company": "Grand Hyatt",
            "location": "Dubai, UAE",
            "description": "Fine dining restaurant seeking an experienced Sous Chef. Flight ticket, visa, and accommodation provided.",
        },
        {
            "title": "Chartered Financial Analyst (CPA/CFA)",
            "company": "Deloitte",
            "location": "Frankfurt, Germany",
            "description": "Join our audit and corporate finance team. EU Blue Card sponsorship supported for qualified international candidates.",
        },
    ]

    from job_radar.config import RadarConfig, ClassifierConfig, GeographyConfig
    test_cfg = RadarConfig(
        classifier=ClassifierConfig(enabled=False, min_relevance_score=50),
        geography=GeographyConfig(allowed_remote_scopes=["worldwide", "region_restricted", "onsite_only", "onsite", "hybrid"]),
    )

    passed_jobs, stats = classify_and_filter_jobs(jobs, config=test_cfg)

    assert stats["passed"] == 4, f"Expected all 4 non-tech jobs to pass, but only {stats['passed']} passed! Stats: {stats}"
    assert len(passed_jobs) == 4

    # Verify ISCO taxonomy attributes are enriched on each job
    rn_job = next(j for j in passed_jobs if "Nurse" in j["title"])
    assert rn_job["isco_code"] == "2221"
    assert rn_job["isco_major_group_code"] == "2"
    assert rn_job["visa_sponsorship"] is True

    electrician_job = next(j for j in passed_jobs if "Electrician" in j["title"])
    assert electrician_job["isco_code"] == "7411"
    assert electrician_job["isco_major_group_code"] == "7"

    chef_job = next(j for j in passed_jobs if "Chef" in j["title"])
    assert chef_job["isco_code"] == "3434"

    cpa_job = next(j for j in passed_jobs if "Financial" in j["title"])
    assert cpa_job["isco_code"] in ("2411", "2412")

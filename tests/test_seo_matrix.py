"""
tests/test_seo_matrix.py

Unit tests for Programmatic SEO Matrix and Employer Profile generation.
"""
from __future__ import annotations

import pytest

from job_radar.employers.model import Employer
from job_radar.seo.employer_profile import generate_employer_seo_profile
from job_radar.seo.matrix import generate_matrix_page


def test_occupation_country_matrix_generation():
    """Verify matrix page generation for healthcare, engineering, and tech occupations."""
    # 1. Registered Nurse in the UK (Shortage Occupation)
    page_uk_nurse = generate_matrix_page("2221", "UK")
    assert page_uk_nurse is not None
    assert page_uk_nurse.is_shortage_occupation is True
    assert "Nursing Professionals" in page_uk_nurse.occupation_title
    assert "United Kingdom" in page_uk_nurse.country_name
    assert "Health and Care Worker Visa" in page_uk_nurse.visa_routes[0]
    assert page_uk_nurse.schema_org_json_ld["@graph"][0]["@type"] == "BreadcrumbList"
    assert len(page_uk_nurse.faq_items) == 3

    # 2. Civil Engineer in Canada (NOC Crosswalk)
    page_ca_civil = generate_matrix_page("2142", "CA")
    assert page_ca_civil is not None
    assert page_ca_civil.national_code_system == "NOC 2021"
    assert page_ca_civil.national_occupation_code == "21300"
    assert "Canada" in page_ca_civil.meta_title

    # 3. Software Developer in Australia (ANZSCO Crosswalk)
    page_au_dev = generate_matrix_page("2512", "AU")
    assert page_au_dev is not None
    assert page_au_dev.national_code_system == "ANZSCO"
    assert page_au_dev.national_occupation_code == "261312"
    assert page_au_dev.is_shortage_occupation is True


def test_employer_seo_profile_generation():
    """Verify employer SEO profile generation with schema.org organization metadata."""
    emp = Employer.create("Stantec", domain="stantec.com", hq_country="CA")
    emp.add_sponsorship_filing(country="CA", route="Positive LMIA", filing_date="2025-06-01", occupation="Civil Engineer")
    emp.add_sponsorship_filing(country="US", route="H-1B", filing_date="2025-08-01", occupation="Structural Engineer")

    profile = generate_employer_seo_profile(emp, active_job_count=12)
    assert profile.canonical_name == "Stantec"
    assert profile.active_job_count == 12
    assert "stantec" in profile.slug
    assert profile.schema_org_json_ld["@type"] == "Organization"
    assert "2+ certified government filings" in profile.sponsorship_summary

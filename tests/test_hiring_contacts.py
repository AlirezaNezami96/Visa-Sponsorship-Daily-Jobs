"""Unit tests for the Find Hiring Contacts feature."""
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from job_radar.contacts.company_resolver import (
    resolve_company_and_domain,
    normalize_domain,
    clean_company_name,
    derive_company_and_domain_from_url,
)
from job_radar.contacts.company_linkedin import extract_linkedin_company_id_from_url
from job_radar.contacts.contact_ranker import (
    score_contact,
    deduplicate_contacts,
    rank_and_deduplicate_contacts,
)
from job_radar.contacts.linkedin_search_builder import build_linkedin_people_search_url
from job_radar.contacts.service import HiringContactsService
from engine.api.main import app


# ── 1. Company and Domain Extraction Tests ────────────────────────────────────

def test_domain_normalization():
    """Verify domain normalization strips schemes, www, paths, and lowercases."""
    assert normalize_domain("https://example.com") == "example.com"
    assert normalize_domain("https://www.example.com/careers/") == "example.com"
    assert normalize_domain("http://www.Example.COM/jobs/123?ref=xyz") == "example.com"
    assert normalize_domain("www.company.co.uk/apply") == "company.co.uk"
    assert normalize_domain("HTTPS://ALLEGRO.EU") == "allegro.eu"
    assert normalize_domain("") == ""


def test_company_resolution_from_structured_data():
    """Verify company resolution prioritizes structured job data."""
    job_data = {
        "company": "Allegro",
        "company_domain": "allegro.eu",
    }
    company, domain = resolve_company_and_domain(job_data=job_data)
    assert company == "Allegro"
    assert domain == "allegro.eu"


def test_company_resolution_from_urls():
    """Verify derivation from Greenhouse, Lever, Ashby, Workday, and custom domains."""
    # Greenhouse
    comp, dom = derive_company_and_domain_from_url("https://boards.greenhouse.io/apollo/jobs/123")
    assert comp == "Apollo"
    assert dom == "apollo.com"

    # Lever
    comp, dom = derive_company_and_domain_from_url("https://jobs.lever.co/stripe/abc-123")
    assert comp == "Stripe"
    assert dom == "stripe.com"

    # Ashby
    comp, dom = derive_company_and_domain_from_url("https://jobs.ashbyhq.com/linear/456")
    assert comp == "Linear"
    assert dom == "linear.com"

    # Custom Career domain
    comp, dom = derive_company_and_domain_from_url("https://careers.allegro.eu/job/12345")
    assert comp == "Allegro"
    assert dom == "allegro.eu"


def test_company_resolution_from_jd_text():
    """Verify fallback company extraction from job description text."""
    jd_text = "About Allegro: We are the leading e-commerce platform in Central Europe."
    comp, dom = resolve_company_and_domain(job_data=None, page_url="", jd_text=jd_text)
    assert comp == "Allegro"
    assert dom == "allegro.com"


# ── 2. Contact Ranking & Deduplication Tests ─────────────────────────────────

def test_contact_ranking_order():
    """Verify deterministic ranking order (Technical Recruiter > Eng Manager > HR Manager)."""
    p_tech_recruiter = {"title": "Technical Recruiter", "seniority": "senior", "departments": ["recruiting"]}
    p_eng_manager = {"title": "Engineering Manager", "seniority": "manager", "departments": ["engineering"]}
    p_hr_manager = {"title": "HR Manager", "seniority": "manager", "departments": ["human_resources"]}
    p_sales = {"title": "Sales Account Executive", "departments": ["sales"]}

    score_tr = score_contact(p_tech_recruiter, job_title="Senior Android Engineer")
    score_em = score_contact(p_eng_manager, job_title="Senior Android Engineer")
    score_hr = score_contact(p_hr_manager, job_title="Senior Android Engineer")
    score_sales = score_contact(p_sales, job_title="Senior Android Engineer")

    # Technical Recruiter (+100 +15 tech +10 recruiting = 125) > Eng Manager (+90 +15 tech +10 mgr = 115) > HR Manager
    assert score_tr > score_em
    assert score_em > score_hr
    assert score_hr > score_sales


def test_contact_deduplication():
    """Verify duplicate person entries are properly deduplicated."""
    raw_contacts = [
        {"id": "1", "name": "Ertan Bera", "title": "Technical Recruiter"},
        {"id": "1", "name": "Ertan Bera", "title": "Technical Recruiter"},
        {"id": "2", "name": "Ertan Bera", "title": "Technical Recruiter"},  # Same name & title
        {"id": "3", "name": "Jane Smith", "title": "Engineering Manager"},
    ]

    deduped = deduplicate_contacts(raw_contacts)
    assert len(deduped) == 2
    names = [p["name"] for p in deduped]
    assert "Ertan Bera" in names
    assert "Jane Smith" in names


# ── 3. LinkedIn Search URL Builder Tests ──────────────────────────────────────

def test_linkedin_search_url_generation():
    """Verify Boolean OR query generation with safe URL encoding and currentCompany parameter."""
    names = ["Ertan Bera", "Jane Smith", "John Doe"]
    company_id = "101649602"

    url = build_linkedin_people_search_url(names=names, company_linkedin_id=company_id)

    assert "https://www.linkedin.com/search/results/people/" in url
    assert "origin=GLOBAL_SEARCH_HEADER" in url
    assert "currentCompany=%5B%22101649602%22%5D" in url
    # Verify Boolean OR in encoded query
    assert "%22Ertan%20Bera%22%20OR%20%22Jane%20Smith%22%20OR%20%22John%20Doe%22" in url


def test_linkedin_search_url_with_unicode_and_quotes():
    """Verify handling of Unicode characters (e.g. Turkish characters) and preexisting quotes."""
    names = ['"Ali Rıza"', "Ömer Faruk", "Şükrü Kaya"]
    company_id = "998877"

    url = build_linkedin_people_search_url(names=names, company_linkedin_id=company_id)
    assert "currentCompany=%5B%22998877%22%5D" in url
    assert "%22Ali%20R%C4%B1za%22" in url


# ── 4. Hiring Contacts Service & API Tests ───────────────────────────────────

@patch("job_radar.contacts.service.find_company_linkedin_info")
@patch("job_radar.contacts.service.search_apollo_people")
def test_hiring_contacts_service_end_to_end(mock_apollo, mock_linkedin, tmp_path):
    """Verify end-to-end service execution with mocked external services."""
    mock_linkedin.return_value = {
        "companyName": "Allegro",
        "linkedinUrl": "https://www.linkedin.com/company/allegro",
        "linkedinCompanyId": "101649602",
    }
    mock_apollo.return_value = [
        {"id": "c1", "name": "Ertan Bera", "title": "Technical Talent Acquisition Partner", "departments": ["recruiting"]},
        {"id": "c2", "name": "Jane Smith", "title": "Engineering Recruiter", "departments": ["recruiting"]},
        {"id": "c3", "name": "John Doe", "title": "Engineering Manager", "departments": ["engineering"]},
    ]

    cache_file = str(tmp_path / "test_contacts_cache.json")
    service = HiringContactsService(cache_path=cache_file)

    res = service.find_hiring_contacts(
        company_name="Allegro",
        company_domain="allegro.eu",
        job_title="Senior Android Engineer",
        force_refresh=True,
    )

    assert res["success"] is True
    assert res["company_name"] == "Allegro"
    assert res["linkedin_company_id"] == "101649602"
    assert len(res["contacts"]) == 3
    assert "linkedin_search_url" in res
    assert "Ertan%20Bera" in res["linkedin_search_url"]


@patch("job_radar.contacts.service.find_company_linkedin_info")
@patch("job_radar.contacts.service.search_apollo_people")
def test_api_contacts_endpoint(mock_apollo, mock_linkedin):
    """Test POST /api/v1/contacts/find endpoint."""
    mock_linkedin.return_value = {
        "companyName": "Stripe",
        "linkedinUrl": "https://www.linkedin.com/company/stripe",
        "linkedinCompanyId": "123456",
    }
    mock_apollo.return_value = [
        {"id": "s1", "name": "Sarah Connor", "title": "Technical Recruiter"},
    ]

    client = TestClient(app)
    payload = {
        "company_name": "Stripe",
        "company_domain": "stripe.com",
        "job_title": "Software Engineer",
        "force_refresh": True,
    }

    resp = client.post("/api/v1/contacts/find", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["company_name"] == "Stripe"
    assert len(data["contacts"]) == 1
    assert data["contacts"][0]["name"] == "Sarah Connor"

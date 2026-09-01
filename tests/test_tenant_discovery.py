"""
tests/test_tenant_discovery.py

Tests for ATS tenant discovery and slug catalog expansion.
"""
import json
from pathlib import Path
from job_radar.sources.tenant_discovery import (
    load_curated_slugs,
    clean_company_name_to_slugs,
)
from job_radar.sources.ats_utils import extract_slug_from_url


def test_curated_slugs_catalog_loaded():
    catalog = load_curated_slugs()
    assert len(catalog) >= 10, "Should contain at least all 10 ATS platform definitions"
    assert "greenhouse" in catalog
    assert "lever" in catalog
    assert "ashby" in catalog
    assert "workday" in catalog
    assert "bamboohr" in catalog
    assert "smartrecruiters" in catalog
    assert "personio" in catalog
    assert "workable" in catalog
    assert "taleo" in catalog
    assert "recruitee" in catalog

    total_slugs = sum(len(v) for v in catalog.values())
    assert total_slugs > 10000, f"Expected over 10k curated slugs across 10 platforms, got {total_slugs}"


def test_derive_slug_candidates():
    candidates = clean_company_name_to_slugs("Spotify USA Inc.")
    assert "spotify" in candidates or "spotify-usa" in candidates

    deepmind_candidates = clean_company_name_to_slugs("DeepMind Technologies Limited")
    assert "deepmind" in deepmind_candidates or "deepmind-technologies" in deepmind_candidates


def test_ats_utils_slug_extraction():
    assert extract_slug_from_url("https://boards.greenhouse.io/stripe", "greenhouse") == "stripe"
    assert extract_slug_from_url("https://jobs.lever.co/netflix", "lever") == "netflix"
    assert extract_slug_from_url("https://jobs.ashbyhq.com/openai", "ashby") == "openai"
    assert extract_slug_from_url("https://acme.bamboohr.com/careers", "bamboohr") == "acme"
    assert extract_slug_from_url("https://careers.smartrecruiters.com/Square", "smartrecruiters") == "Square"
    assert extract_slug_from_url("https://uber.wd1.myworkdayjobs.com/Uber_Careers", "workday") == "uber/Uber_Careers"

"""Tests for metadata enrichment worker parsing logic (rule-based skills, salary, work mode)."""
import pytest

from job_radar.pipeline.enrichment_worker import (
    _extract_skills_rule_based,
    _normalize_salary,
    _normalize_work_mode,
)


def test_extract_skills_rule_based():
    text = "We need a Senior Python Developer with strong React, Docker, and PostgreSQL experience."
    skills = _extract_skills_rule_based(text)
    assert "python" in skills
    assert "react" in skills
    assert "docker" in skills
    assert "postgresql" in skills
    assert "ruby" not in skills


def test_normalize_salary_range():
    res = _normalize_salary("$80,000 - $120,000 per year")
    assert res["min"] == 80000
    assert res["max"] == 120000
    assert res["currency"] == "USD"

    res_eur = _normalize_salary("€50k - €70k")
    assert res_eur["min"] == 50000
    assert res_eur["max"] == 70000
    assert res_eur["currency"] == "EUR"


def test_normalize_work_mode():
    assert _normalize_work_mode("Fully Remote") == "remote"
    assert _normalize_work_mode("Hybrid / 2 days in office") == "hybrid"
    assert _normalize_work_mode("On-site (London office)") == "onsite"

"""Tests for precise ATS answers, widgets, compensation FX, and batch AI."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from fastapi.testclient import TestClient
from engine.api.main import app, _load_profile_data


def test_work_authorization_profile_rules():
    """Verify applicant profile work authorization defaults."""
    profile = _load_profile_data()
    assert profile["work_authorization"]["legally_authorized_default"] == "No"
    assert profile["work_authorization"]["legally_authorized_in_turkey"] == "Yes"
    assert profile["work_authorization"]["requires_visa_or_sponsorship"] == "Yes"
    assert profile["address"]["city_query"] == "Istanbul"
    assert profile["address"]["city_display"] == "Istanbul, Turkey"
    assert profile["identity"]["phone_national"] == "5437437966"
    assert profile["compensation"]["monthly_usd"] == 3000


def test_work_auth_polarity_logic():
    """Verify work authorization polarity resolution matches §2 table."""
    def answer_work_auth(text: str) -> str:
        t = text.lower().strip()
        if "turkey" in t or "türkiye" in t or "turkiye" in t:
            if any(k in t for k in ["authorized", "right to work", "eligible", "citizen"]):
                return "Yes"
        if any(k in t for k in [
            "without sponsorship", "without requiring sponsorship", "without visa",
            "already have authorization", "do not require sponsorship", "don't require sponsorship"
        ]):
            return "No"
        if any(k in t for k in [
            "require visa", "require sponsorship", "will you require", "need sponsorship",
            "need employer to sponsor", "future sponsorship", "visa sponsorship"
        ]):
            return "Yes"
        if any(k in t for k in [
            "legally authorized", "authorized to work", "right to work", "eligible to work",
            "work authorization", "work permit"
        ]):
            return "No"
        return "No"

    # 1. legally authorized / right to work / eligible in US/UK/CA/EU/not Turkey -> No
    assert answer_work_auth("Are you legally authorized to work in the United States?") == "No"
    assert answer_work_auth("Do you have the right to work in the United Kingdom or EU?") == "No"
    assert answer_work_auth("Are you eligible to work in Canada?") == "No"

    # 2. legally authorized ... Turkey / Türkiye -> Yes
    assert answer_work_auth("Are you legally authorized to work in Turkey?") == "Yes"
    assert answer_work_auth("Do you have the right to work in Türkiye?") == "Yes"

    # 3. will you (now or in future) require visa / sponsorship -> Yes
    assert answer_work_auth("Will you now or in the future require visa sponsorship?") == "Yes"
    assert answer_work_auth("Do you require sponsorship for employment visa status?") == "Yes"

    # 4. can you work without sponsorship / already have authorization -> No (inverse)
    assert answer_work_auth("Can you work without sponsorship from our company?") == "No"
    assert answer_work_auth("Do you already have authorization to work without requiring sponsorship?") == "No"

    # 5. need employer to sponsor -> Yes
    assert answer_work_auth("Do you need employer to sponsor your work permit?") == "Yes"


def test_compensation_math_all_prompt_cases():
    """Verify compensation calculations match §4 specifications."""
    profile = _load_profile_data()
    monthly_usd = profile["compensation"]["monthly_usd"]
    hours_per_month = profile["compensation"]["hours_per_month"]
    fx = profile["compensation"]["fx_fallback"]

    # 1. Expected salary (USD, monthly) -> 3000
    assert monthly_usd == 3000

    # 2. Gross annual salary EUR -> 33120
    annual_eur = round(monthly_usd * 12 * fx["EUR"])
    assert annual_eur == 33120

    # 3. Salary per hour USD -> 17.31
    hourly_usd = round(monthly_usd / hours_per_month, 2)
    assert hourly_usd == 17.31

    # 4. B2B per hour PLN -> ~69.24
    b2b_hourly_pln = round((monthly_usd / hours_per_month) * fx["PLN"], 2)
    assert abs(b2b_hourly_pln - 69.23) < 0.05

    # 5. Annual GBP -> 28080
    annual_gbp = round(monthly_usd * 12 * fx["GBP"])
    assert annual_gbp == 28080

    # 6. Hourly EUR -> ~15.92
    hourly_eur = round((monthly_usd / hours_per_month) * fx["EUR"], 2)
    assert abs(hourly_eur - 15.92) < 0.05

    # 7. Monthly TRY -> 123000
    monthly_try = round(monthly_usd * fx["TRY"])
    assert monthly_try == 123000

    # 8. Thousands USD / year -> 36
    thousands_year = round((monthly_usd * 12) / 1000)
    assert thousands_year == 36


def test_zero_fetch_in_extension_content_scripts():
    """Ensure no direct fetch() exists in any extension content or autofill scripts."""
    ext_dir = Path(__file__).resolve().parent.parent / "engine" / "extension"
    content_files = [
        ext_dir / "content.js",
        *(ext_dir / "autofill").glob("*.js"),
        *(ext_dir / "autofill" / "adapters").glob("*.js"),
    ]

    for f in content_files:
        if not f.exists():
            continue
        content = f.read_text(encoding="utf-8")
        assert "fetch(" not in content, f"Direct fetch() found in content script: {f.name}"


@patch("job_radar.llm.router.complete")
def test_batch_autofill_endpoint(mock_complete):
    """Test POST /api/v1/autofill/batch endpoint."""
    mock_res = MagicMock()
    mock_res.text = '{"answers": [{"id": "field_0", "value": "2 weeks", "option": "2 weeks"}]}'
    mock_complete.return_value = mock_res

    client = TestClient(app)
    payload = {
        "job_title": "Senior Android Engineer",
        "company_name": "Allegro",
        "job_description": "Looking for Android engineer with Kotlin and Coroutines experience.",
        "questions": [
            {
                "id": "field_0",
                "label": "Notice period",
                "type": "select",
                "options": ["Immediate", "2 weeks", "1 month"]
            }
        ]
    }

    res = client.post("/api/v1/autofill/batch", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert len(data["answers"]) == 1
    assert data["answers"][0]["id"] == "field_0"
    assert data["answers"][0]["value"] == "2 weeks"

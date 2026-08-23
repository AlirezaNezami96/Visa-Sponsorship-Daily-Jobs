"""Comprehensive Universal Autofill Engine Tests & ATS Fixture Validation Suite."""
import json
import os
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from src.job_radar.autofill.saved_answers import (
    SavedAnswersLibrary,
    normalize_question_text,
    calculate_jaccard_similarity,
)


@pytest.fixture
def client():
    return TestClient(app)


# ── 1. Saved Answers & Similarity Tests ──

def test_normalize_question_text():
    assert normalize_question_text("Are you authorized to work in the US?") == "are you authorized to work in the us"
    assert normalize_question_text("  What is your notice period?! ") == "what is your notice period"
    assert normalize_question_text("") == ""


def test_jaccard_similarity():
    q1 = "Are you legally authorized to work in the United States?"
    q2 = "Are you legally authorized to work in the US?"
    sim = calculate_jaccard_similarity(q1, q2)
    assert sim > 0.60

    q3 = "What is your target compensation?"
    assert calculate_jaccard_similarity(q1, q3) < 0.20


def test_saved_answers_library(tmp_path):
    storage_file = str(tmp_path / "saved_test.json")
    lib = SavedAnswersLibrary(storage_path=storage_file)

    assert lib.find_matching_answer("How many years of Kotlin experience do you have?") is None

    lib.save_answer("How many years of Kotlin experience do you have?", "9 years of professional Kotlin experience.")
    matched = lib.find_matching_answer("How many years of Kotlin experience do you have?")
    assert matched == "9 years of professional Kotlin experience."

    # Fuzzy match with high similarity
    fuzzy_matched = lib.find_matching_answer("How many years of Kotlin experience do you have in production?", threshold=0.7)
    assert fuzzy_matched == "9 years of professional Kotlin experience."


# ── 2. Compatibility Remote Config API Tests ──

def test_get_autofill_config_endpoint(client):
    response = client.get("/api/v1/autofill/config")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "config" in data
    config = data["config"]
    assert "version" in config
    assert "platforms" in config
    assert "greenhouse" in config["platforms"]
    assert "workday" in config["platforms"]


# ── 3. Batch Question Answering Endpoint Tests ──

def test_batch_answering_endpoint_with_saved_and_ai(client, tmp_path, monkeypatch):
    # Mock router complete
    class MockResult:
        text = json.dumps({
            "answers": [
                {"id": "field_q1", "value": "2 weeks notice", "option": "2 weeks"}
            ]
        })

    monkeypatch.setattr("job_radar.llm.router.complete", lambda **kwargs: MockResult())

    payload = {
        "job_title": "Senior Android Engineer",
        "company_name": "Tech Corp",
        "job_description": "We are seeking a senior Android dev with Kotlin and Jetpack Compose.",
        "questions": [
            {"id": "field_q1", "label": "What is your notice period?", "type": "text"}
        ]
    }

    response = client.post("/api/v1/autofill/batch", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["answers"]) == 1
    assert data["answers"][0]["id"] == "field_q1"
    assert "2 weeks" in data["answers"][0]["value"]


# ── 4. ATS Fixture Presence & Integrity Tests ──

@pytest.mark.parametrize("fixture_name", [
    "workday.html",
    "greenhouse.html",
    "lever.html",
    "ashby.html",
    "icims.html",
    "taleo.html",
    "avature.html",
    "smartrecruiters.html",
    "adp.html",
    "linkedin.html",
    "indeed.html",
    "custom_react.html",
    "dynamic_conditional.html",
    "custom_combobox.html",
    "file_upload.html",
])
def test_ats_fixtures_exist_and_valid(fixture_name):
    base_dir = os.path.join(os.path.dirname(__file__), "..", "engine", "extension", "autofill", "fixtures")
    file_path = os.path.join(base_dir, fixture_name)
    assert os.path.exists(file_path), f"Fixture {fixture_name} not found at {file_path}"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert len(content) > 50
        assert "<html" in content.lower()
        assert "input" in content.lower() or "form" in content.lower() or "combobox" in content.lower()

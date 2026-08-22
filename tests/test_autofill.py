"""Unit tests for ATS Autofill, applicant profile APIs, and human-voice answer sanitization."""
import json
import pytest
from unittest.mock import MagicMock, patch
from engine.api.main import _load_profile_data, BANNED_ANSWER_WORDS


def test_applicant_profile_structure():
    profile = _load_profile_data()
    assert profile is not None
    assert "identity" in profile
    assert profile["identity"]["first_name"] == "Alireza"
    assert profile["identity"]["last_name"] == "Nezami"
    assert "skills" in profile
    assert len(profile["skills"]["core"]) > 20
    assert "Kotlin" in profile["skills"]["core"]
    assert "Flutter" in profile["skills"]["core"]
    assert "Turkey" in profile["address"]["country_aliases"]
    assert "Türkiye" in profile["address"]["country_aliases"]


def test_banned_words_sanitization():
    import re
    raw_answer = "I am passionate about Flutter and excited to leverage Clean Architecture."
    cleaned = raw_answer
    for pat in BANNED_ANSWER_WORDS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    assert "passionate" not in cleaned.lower()
    assert "excited" not in cleaned.lower()
    assert "leverage" not in cleaned.lower()
    assert "Clean Architecture" in cleaned

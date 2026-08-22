"""Comprehensive test suite for Simplify-class ATS Autofill Copilot."""
import os
import re
from pathlib import Path
import pytest
from engine.api.main import _load_profile_data, BANNED_ANSWER_WORDS


def test_no_fetch_in_extension_content_scripts():
    """Fail CI if any content script or autofill module contains fetch( calls."""
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
        assert "fetch(" not in content, f"Forbidden direct fetch() call found in content script: {f.name}"


def test_applicant_profile_contains_real_candidate_and_aliases():
    profile = _load_profile_data()
    assert profile is not None
    assert profile["identity"]["first_name"] == "Alireza"
    assert profile["identity"]["last_name"] == "Nezami"
    assert profile["identity"]["email"] == "alirezanezami1996@gmail.com"
    assert profile["identity"]["phone_national"] == "5437437966"
    assert profile["address"]["city"] == "Istanbul"

    aliases = profile["address"]["country_aliases"]
    assert "Türkiye" in aliases
    assert "Turkey" in aliases
    assert "Turkiye" in aliases
    assert "TR" in aliases


def test_eeo_and_work_auth_answers():
    profile = _load_profile_data()
    assert profile["work_authorization"]["authorized_us"] == "No"
    assert profile["work_authorization"]["authorized_uk"] == "No"
    assert profile["work_authorization"]["legally_authorized_default"] == "No"
    assert profile["work_authorization"]["legally_authorized_in_turkey"] == "Yes"
    assert profile["work_authorization"]["requires_sponsorship_now_or_future"] == "Yes"
    assert profile["eeo_and_screening"]["disability"] == "No"
    assert profile["eeo_and_screening"]["gender"] == "Male"
    assert profile["eeo_and_screening"]["ethnicity"] == "Middle Eastern"

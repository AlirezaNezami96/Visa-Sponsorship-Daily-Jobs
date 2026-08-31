"""Live test for Alireza Nezami's Resume Parsing.

Tests the full Gemini multi-model extraction pipeline with actual resume content.
"""
import os
import json
import re
import requests
import pytest

RESUME_PATH = "/Users/alirezanezami/Documents/Visa-Sponsorship-Daily-Jobs/tests/fixtures/resumes/Alireza_Nezami_Resume.txt"

def get_test_keys():
    raw = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
    extra = [os.getenv("GEMINI_API_KEY_2", ""), os.getenv("GEMINI_API_KEY_3", "")]
    keys = [k.strip() for k in re.split(r"[,;\s]+", raw) if k.strip() and k.strip() != "PLACEHOLDER_KEY"]
    for k in extra:
        if k.strip() and k.strip() not in keys and k.strip() != "PLACEHOLDER_KEY":
            keys.append(k.strip())
    return keys

def test_alireza_resume_live_parsing():
    assert os.path.exists(RESUME_PATH), f"Resume file not found at {RESUME_PATH}"
    with open(RESUME_PATH, "r", encoding="utf-8") as f:
        resume_text = f.read()

    assert len(resume_text) > 200, "Resume text is too short"

    keys = get_test_keys()
    if not keys:
        pytest.skip("No GEMINI_API_KEY configured in environment")

    models = ["gemini-3.6-flash", "gemini-flash-latest", "gemini-3.7-flash", "gemini-flash-lite-latest", "gemini-pro-latest"]

    prompt = f"""You are an expert resume parser for VisaLane.
Extract structured data from the following resume in JSON format.
Return ONLY valid JSON matching this schema:
{{
  "full_name": string,
  "job_titles": string[],
  "skills": string[],
  "years_of_experience": number,
  "current_location": string,
  "preferred_locations": string[],
  "experience": [
    {{
      "company": string,
      "title": string,
      "location": string,
      "start_date": string,
      "end_date": string,
      "bullets": string[]
    }}
  ],
  "education": [
    {{
      "institution": string,
      "degree": string,
      "field": string,
      "graduation_year": string
    }}
  ]
}}

Resume:
{resume_text}"""

    parsed_result = None
    last_error = ""

    for key in keys:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                resp = requests.post(
                    url,
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed_result = json.loads(raw_json)
                    break
                else:
                    last_error = f"Status {resp.status_code}: {resp.text[:120]}"
            except Exception as e:
                last_error = str(e)
        if parsed_result:
            break

    assert parsed_result is not None, f"Failed to parse resume across all keys/models: {last_error}"

    # Assertions on parsed resume structure
    print("\n--- Parsed Resume Verification ---")
    print(f"Full Name: {parsed_result.get('full_name')}")
    print(f"Job Titles: {parsed_result.get('job_titles')}")
    print(f"Skills Count: {len(parsed_result.get('skills', []))}")
    print(f"Top Skills: {parsed_result.get('skills', [])[:10]}")
    print(f"Experience Count: {len(parsed_result.get('experience', []))}")

    assert "Alireza" in parsed_result.get("full_name", ""), "Full name should contain Alireza"
    assert len(parsed_result.get("skills", [])) >= 10, "Should extract at least 10 skills"
    assert any("Kotlin" in s or "Flutter" in s or "Android" in s for s in parsed_result.get("skills", [])), "Should extract core mobile skills"
    assert len(parsed_result.get("experience", [])) >= 3, "Should extract at least 3 work experiences"
    assert any("Devotel" in exp.get("company", "") or "Golden Equator" in exp.get("company", "") for exp in parsed_result.get("experience", [])), "Should extract verified companies"
    print("ALL ASSERTIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_alireza_resume_live_parsing()

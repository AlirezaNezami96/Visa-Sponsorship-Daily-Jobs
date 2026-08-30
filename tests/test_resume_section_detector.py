"""Unit tests for multi-language resume section detector."""
from __future__ import annotations

from job_radar.resume.section_detector import (
    detect_all_sections,
    detect_sections_from_parsed_data,
    detect_sections_from_text,
)


def test_detect_sections_from_english_text():
    text = """
    Jane Doe
    jane@example.com

    SUMMARY
    Senior Software Engineer with 8 years of experience in distributed systems.

    EXPERIENCE
    Staff Engineer at Acme Corp (2020-Present)
    - Led backend migration to Go

    EDUCATION
    BS in Computer Science, Stanford University (2016)

    SKILLS
    Python, Go, PostgreSQL, Kubernetes, AWS

    PROJECTS
    Open Source Database Profiler

    CERTIFICATIONS
    AWS Certified Solutions Architect

    LANGUAGES
    English (Native), French (Fluent)

    VOLUNTEER WORK
    Code in Place Teaching Assistant

    PUBLICATIONS
    Optimizing Distributed Transactions (VLDB 2021)

    AWARDS
    Acme Innovator of the Year

    INTERESTS
    Rock climbing, Chess

    REFERENCES
    Available upon request
    """
    detected = detect_sections_from_text(text)
    assert "summary" in detected
    assert "experience" in detected
    assert "education" in detected
    assert "skills" in detected
    assert "projects" in detected
    assert "certifications" in detected
    assert "languages" in detected
    assert "volunteer_work" in detected
    assert "publications" in detected
    assert "awards" in detected
    assert "interests" in detected
    assert "references" in detected


def test_detect_sections_from_multilingual_text():
    # German CV
    de_text = """
    Hans Mueller
    BERUFLICHER WERDEGANG
    Softwareentwickler bei Bosch (2018-2023)

    AUSBILDUNG
    Master Informatik, TU Muenchen

    KENNTNISSE
    Java, Spring Boot, Docker

    SPRACHEN
    Deutsch (Muttersprache), Englisch (C1)
    """
    detected_de = detect_sections_from_text(de_text)
    assert "experience" in detected_de
    assert "education" in detected_de
    assert "skills" in detected_de
    assert "languages" in detected_de

    # Spanish CV
    es_text = """
    Carlos Gomez
    EXPERIENCIA LABORAL
    Desarrollador Full Stack

    FORMACIÓN ACADÉMICA
    Ingeniería en Sistemas

    HABILIDADES
    React, Python, SQL
    """
    detected_es = detect_sections_from_text(es_text)
    assert "experience" in detected_es
    assert "education" in detected_es
    assert "skills" in detected_es


def test_detect_sections_from_parsed_data():
    data = {
        "summary": "Experienced engineer",
        "experience": [{"company": "Google", "title": "SWE"}],
        "education": [{"institution": "MIT"}],
        "skills": ["Python", "FastAPI"],
        "projects": [],  # empty list shouldn't count
        "languages": None,  # None shouldn't count
    }
    sections = detect_sections_from_parsed_data(data)
    assert "summary" in sections
    assert "experience" in sections
    assert "education" in sections
    assert "skills" in sections
    assert "projects" not in sections
    assert "languages" not in sections


def test_detect_all_sections_union():
    text = "SUMMARY\nExperienced Developer\n\nHOBBIES\nReading"
    data = {"skills": ["Python"], "education": [{"institution": "Oxford"}]}
    all_secs = detect_all_sections(text, data)
    assert "summary" in all_secs
    assert "interests" in all_secs
    assert "skills" in all_secs
    assert "education" in all_secs

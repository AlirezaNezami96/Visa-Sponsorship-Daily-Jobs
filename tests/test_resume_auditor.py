"""Unit tests for the Entailment Auditor and Google Docs bullet replacements."""
import pytest
from job_radar.resume.auditor import audit_bullet_replacement, audit_all_replacements


def test_auditor_catches_fake_percentages():
    orig_bullet = "Optimized build performance and reduced app crash rates across releases."
    hallucinated_bullet = "Optimized build performance and achieved a 99% crash reduction across releases."

    is_valid, sanitized, dropped = audit_bullet_replacement(
        original_bullet_text=orig_bullet,
        rewritten_bullet_text=hallucinated_bullet,
    )
    assert is_valid is False
    assert len(dropped) >= 1
    assert "99%" in dropped[0] or "99%" not in sanitized


def test_auditor_permits_grounded_rephrasing():
    orig_bullet = "Architected a modular codebase with Flutter, Bloc, and Clean Architecture for 400K users."
    rewritten_bullet = "Engineered a scalable, modular Flutter application following Clean Architecture and Bloc state management serving 400K users."

    is_valid, sanitized, dropped = audit_bullet_replacement(
        original_bullet_text=orig_bullet,
        rewritten_bullet_text=rewritten_bullet,
    )
    assert is_valid is True
    assert len(dropped) == 0

"""
tests/test_additive_confidence.py

Unit tests for the additive multi-signal confidence scoring engine:
- Hard negative refusal override
- Additive score accumulation (Government match + JD statement + Shortage list)
- Multi-evidence confidence tier calibration
- New Zealand (INZ AEWV) & Australia (Subclass 482) Direct Government Tier
- Strict third-party evidence boundary (Jaabz / community seeds)
"""
import pytest
from job_radar.visa.confidence import (
    ConfidenceTier,
    EvidenceProvenance,
    evaluate_sponsorship_confidence,
)


def test_hard_negative_override():
    """Explicit refusal in JD immediately returns NEGATIVE with score 0.0, regardless of other positive factors."""
    res = evaluate_sponsorship_confidence(
        employer_name="Acme Corp",
        job_description="Must already have the right to work in the UK. No visa sponsorship provided.",
        country="UK",
        government_match={"source": "govuk_register", "rating": "A", "routes": ["Skilled Worker"]},
        isco_code="2512",
    )
    assert res.tier == ConfidenceTier.NEGATIVE
    assert res.score == 0.0
    assert res.is_verified is False
    assert len(res.evidence) == 1
    assert res.evidence[0].signal_strength == -1.0


def test_additive_multi_signal_score_accumulation():
    """Combining direct government registry match with explicit JD text produces high additive score."""
    # 1. Direct Government alone
    res_gov_only = evaluate_sponsorship_confidence(
        employer_name="DeepMind",
        job_description="Research Scientist in Artificial Intelligence.",
        country="UK",
        government_match={"source": "govuk_register", "rating": "A", "routes": ["Skilled Worker"]},
    )
    assert res_gov_only.tier == ConfidenceTier.VERIFIED
    assert res_gov_only.is_verified is True
    assert res_gov_only.score >= 0.85

    # 2. Direct Government + Explicit JD Statement + Shortage List (ISCO 2512)
    res_combined = evaluate_sponsorship_confidence(
        employer_name="DeepMind",
        job_description="Research Scientist in AI. Full visa sponsorship provided and international relocation package included.",
        country="UK",
        government_match={"source": "govuk_register", "rating": "A", "routes": ["Skilled Worker"]},
        isco_code="2512",
    )
    assert res_combined.tier == ConfidenceTier.VERIFIED
    assert res_combined.score == 1.0  # Capped at 1.0
    assert len(res_combined.evidence) >= 3


def test_explicit_employer_claim_alone_yields_high_or_medium():
    """Explicit positive JD statement without official government register match."""
    res = evaluate_sponsorship_confidence(
        employer_name="Global Tech Startup",
        job_description="Senior Backend Engineer. We provide full visa sponsorship and relocation support for international candidates.",
        country="DE",
        isco_code="2512",
    )
    # JD text (0.25) + Shortage list (0.15) + Country framework (0.05)
    assert res.is_verified is False
    assert res.score >= 0.45
    assert any(e.provenance == EvidenceProvenance.EMPLOYER_CLAIM for e in res.evidence)


def test_new_zealand_aewv_direct_government():
    """New Zealand INZ Accredited Employer maps to direct government verified tier."""
    res = evaluate_sponsorship_confidence(
        employer_name="Xero Limited",
        job_description="Senior Software Developer in Wellington.",
        country="NZ",
        government_match={
            "source": "inz_accredited_register",
            "rating": "Standard Accreditation",
            "routes": ["AEWV", "Green List Straight to Residence"],
        },
        isco_code="2512",
    )
    assert res.tier == ConfidenceTier.VERIFIED
    assert res.is_verified is True
    assert "AEWV" in str(res.eligible_visa_routes)


def test_australia_home_affairs_direct_government():
    """Australia Department of Home Affairs Approved Business Sponsor maps to verified tier."""
    res = evaluate_sponsorship_confidence(
        employer_name="Atlassian Pty Ltd",
        job_description="Site Reliability Engineer in Sydney.",
        country="AU",
        government_match={
            "source": "home_affairs_sponsors",
            "rating": "Accredited Sponsor",
            "routes": ["Subclass 482", "Subclass 186"],
        },
        isco_code="2512",
    )
    assert res.tier == ConfidenceTier.VERIFIED
    assert res.is_verified is True
    assert "Subclass 482" in str(res.eligible_visa_routes)


def test_third_party_jaabz_seed_strict_tier_boundary():
    """Third-party / Jaabz seed signal alone never reaches VERIFIED or HIGH confidence."""
    res = evaluate_sponsorship_confidence(
        employer_name="Random Unverified Employer",
        job_description="Software developer position.",
        country="US",
        is_third_party_seed=True,
    )
    assert res.tier in (ConfidenceTier.LOW, ConfidenceTier.UNKNOWN)
    assert res.is_verified is False
    assert res.score < 0.50
    assert any(e.provenance == EvidenceProvenance.THIRD_PARTY for e in res.evidence)

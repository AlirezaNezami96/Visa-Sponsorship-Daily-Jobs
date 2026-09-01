"""
src/job_radar/visa/gulf_kafala.py

Gulf States & Destination-Permit Sponsorship Evidence Engine.
Implements calibrated legal-framework rules for Gulf Cooperation Council (GCC) countries:
  - UAE (MOHRE Work Permit & Employment Visa)
  - Saudi Arabia (Qiwa Work Permit & MHRSD Nitaqat Compliance)
  - Qatar (ADLSA Work Residence Permit)
  - Kuwait, Bahrain, Oman

In GCC jurisdictions, private employment of expatriates legally mandates employer-provided
visas, labor cards, and basic medical coverage.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from job_radar.visa.confidence import (
    ConfidenceTier,
    EvidenceProvenance,
    SponsorshipEvaluationResult,
    SponsorshipEvidence,
    build_explanation,
)

GCC_COUNTRIES = {
    "AE": {
        "name": "United Arab Emirates",
        "authority": "MOHRE / GDRFA",
        "visa_name": "UAE Employment Residence Visa",
        "mandatory_coverage": ["Employment Visa", "Labor Card", "Medical Insurance"],
    },
    "SA": {
        "name": "Saudi Arabia",
        "authority": "MHRSD / Qiwa",
        "visa_name": "Iqama / Work Visa (Nitaqat Compliant)",
        "mandatory_coverage": ["Work Visa", "Iqama Transfer/Issuance", "Chi Medical Insurance"],
    },
    "QA": {
        "name": "Qatar",
        "authority": "Ministry of Labour (MOL)",
        "visa_name": "Qatar Work Residence Permit (QID)",
        "mandatory_coverage": ["Work Permit", "Qatar ID (QID)", "Hamad Medical / Private"],
    },
    "KW": {
        "name": "Kuwait",
        "authority": "PAM (Public Authority for Manpower)",
        "visa_name": "Kuwait Article 18 Work Visa",
        "mandatory_coverage": ["Work Permit", "Civil ID"],
    },
    "BH": {
        "name": "Bahrain",
        "authority": "LMRA (Labour Market Regulatory Authority)",
        "visa_name": "LMRA Work Permit",
        "mandatory_coverage": ["LMRA Work Visa", "CPR Card"],
    },
    "OM": {
        "name": "Oman",
        "authority": "Ministry of Labour",
        "visa_name": "Oman Employment Visa",
        "mandatory_coverage": ["Labour Card", "Resident Card"],
    },
}


def evaluate_gulf_sponsorship(
    employer_name: str,
    country_code: str,
    job_description: str = "",
    job_title: str = "",
) -> SponsorshipEvaluationResult:
    """
    Evaluate sponsorship for a GCC posting based on legal employment obligations and JD perks.
    """
    c_code = (country_code or "").upper().strip()
    gcc_meta = GCC_COUNTRIES.get(c_code)
    if not gcc_meta:
        raise ValueError(f"Country code '{c_code}' is not a recognized GCC jurisdiction.")

    evidence: List[SponsorshipEvidence] = []
    desc_lower = job_description.lower()
    title_lower = job_title.lower()
    combined = f"{title_lower} {desc_lower}"

    # 1. Check for explicit local-only or refusal conditions
    refusal_patterns = [
        r"\b(?:gcc\s+nationals\s+only|uae\s+nationals\s+only|saudi\s+nationals\s+only|emiratisation|saudization)\b",
        r"\b(?:only\s+candidates\s+with\s+own\s+visa|freelance\s+visa\s+holders\s+only|spouse\s+visa\s+only)\b",
    ]
    for pat in refusal_patterns:
        m = re.search(pat, combined)
        if m:
            quote = combined[max(0, m.start() - 10):min(len(combined), m.end() + 10)].strip()
            evidence.append(
                SponsorshipEvidence(
                    provenance=EvidenceProvenance.EMPLOYER_CLAIM,
                    source_name="job_description",
                    signal_strength=-1.0,
                    description=f"Local quota or self-sponsored restriction: \"{quote}\"",
                )
            )
            return SponsorshipEvaluationResult(
                tier=ConfidenceTier.NEGATIVE,
                score=0.0,
                is_verified=False,
                evidence=evidence,
                explanation=f"Not Sponsored: Position restricted to local nationals or self-sponsored visa holders (\"{quote}\").",
            )

    # 2. Check for explicit relocation / flight / accommodation perks (HIGH Confidence)
    perk_matches = []
    if re.search(r"\b(?:flight|ticket|airfare|annual\s+ticket)\b", combined):
        perk_matches.append("annual flight tickets")
    if re.search(r"\b(?:accommodation|housing\s+allowance|furnished\s+apartment)\b", combined):
        perk_matches.append("housing/accommodation")
    if re.search(r"\b(?:visa\s+provided|employment\s+visa|iqama\s+transferable|work\s+permit\s+provided)\b", combined):
        perk_matches.append("explicit visa sponsorship")

    if perk_matches:
        evidence.append(
            SponsorshipEvidence(
                provenance=EvidenceProvenance.EMPLOYER_CLAIM,
                source_name="job_description",
                signal_strength=0.90,
                description=f"Employer offers full expatriate package: {', '.join(perk_matches)}",
            )
        )
        return SponsorshipEvaluationResult(
            tier=ConfidenceTier.HIGH,
            score=0.90,
            is_verified=False,
            evidence=evidence,
            explanation=f"High Confidence: Employer explicitly provides expatriate sponsorship package ({', '.join(perk_matches)}) under {gcc_meta['name']} labor regulations.",
            eligible_visa_routes=[gcc_meta["visa_name"]],
        )

    # 3. Standard GCC Statutory Framework (MEDIUM Confidence)
    evidence.append(
        SponsorshipEvidence(
            provenance=EvidenceProvenance.INDIRECT_GOVERNMENT,
            source_name=f"{gcc_meta['authority']} statutory_requirement",
            signal_strength=0.70,
            description=f"Under {gcc_meta['name']} labor law ({gcc_meta['authority']}), hiring foreign talent mandates employer-sponsored {gcc_meta['visa_name']}",
        )
    )

    return SponsorshipEvaluationResult(
        tier=ConfidenceTier.MEDIUM,
        score=0.70,
        is_verified=False,
        evidence=evidence,
        explanation=f"Medium Confidence: Verified position in {gcc_meta['name']} where employer is legally responsible for {gcc_meta['visa_name']} issuance.",
        eligible_visa_routes=[gcc_meta["visa_name"]],
    )

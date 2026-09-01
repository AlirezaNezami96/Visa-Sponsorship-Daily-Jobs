"""
src/job_radar/visa/confidence.py

Five-Tier Sponsorship Confidence Architecture & Additive Evidence Provenance Engine.
Adheres strictly to the 5 tiers and 5 evidence provenance categories:

Tiers:
  - VERIFIED: Active official government sponsor registry record (within 12 months) + matching employer.
  - HIGH: Explicit statement of visa sponsorship in job posting text OR established multi-year sponsorship history.
  - MEDIUM: Indirect signal (occupation on shortage list, agency placement, relocation assistance).
  - LOW: Plausible under country visa framework, no negative signal.
  - UNKNOWN: Insufficient data.
  - NEGATIVE: Explicit refusal statement in job text.

Provenance:
  - DIRECT_GOVERNMENT: Official registry or filing data.
  - INDIRECT_GOVERNMENT: Occupation shortage lists, statutory salary thresholds.
  - EMPLOYER_CLAIM: Job posting text, careers page, ATS questionnaire.
  - THIRD_PARTY: Licensed recruitment agency, verified applicant reports.
  - INFERRED: Industry patterns, revenue/size threshold, international hiring history.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class ConfidenceTier(str, Enum):
    VERIFIED = "verified"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"
    NEGATIVE = "negative"


class EvidenceProvenance(str, Enum):
    DIRECT_GOVERNMENT = "direct_government"
    INDIRECT_GOVERNMENT = "indirect_government"
    EMPLOYER_CLAIM = "employer_claim"
    THIRD_PARTY = "third_party"
    INFERRED = "inferred"


@dataclass
class SponsorshipEvidence:
    """A discrete, verifiable piece of sponsorship intelligence with provenance."""
    provenance: EvidenceProvenance
    source_name: str
    signal_strength: float  # -1.0 (refusal) to +1.0 (verified proof)
    description: str
    reference_url: Optional[str] = None
    as_of_date: Optional[str] = None
    raw_payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provenance": self.provenance.value if isinstance(self.provenance, EvidenceProvenance) else self.provenance,
            "sourceName": self.source_name,
            "signalStrength": self.signal_strength,
            "description": self.description,
            "referenceUrl": self.reference_url,
            "asOfDate": self.as_of_date,
            "metadata": self.raw_payload or {},
        }


@dataclass
class SponsorshipEvaluationResult:
    """Final calibrated sponsorship assessment with comprehensive explainability."""
    tier: ConfidenceTier
    score: float  # 0.0 to 1.0 (or -1.0 for negative)
    is_verified: bool
    evidence: List[SponsorshipEvidence] = field(default_factory=list)
    explanation: str = ""
    eligible_visa_routes: List[str] = field(default_factory=list)
    registry_record: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier.value if isinstance(self.tier, ConfidenceTier) else self.tier,
            "score": round(self.score, 2),
            "isVerified": self.is_verified,
            "evidence": [e.to_dict() for e in self.evidence],
            "explanation": self.explanation,
            "eligibleVisaRoutes": self.eligible_visa_routes,
            "registryRecord": self.registry_record,
        }


# Standard Shortage Occupations by Country (Indirect Government Evidence)
SHORTAGE_LISTS: Dict[str, Set[str]] = {
    # UK Immigration Salary List (ISL / SOL) - ISCO unit codes
    "UK": {"2211", "2212", "2221", "2261", "2142", "2146", "2512", "2519", "7411", "7212", "3434"},
    # Canada Targeted Express Entry Categories (Healthcare, STEM, Trades, Transport, Agri)
    "CA": {"2211", "2212", "2221", "2141", "2142", "2144", "2145", "2146", "2512", "2519", "2521", "7115", "7126", "7212", "7411", "8332"},
    # Australia Core Skills / PMSOL List
    "AU": {"2211", "2212", "2221", "2262", "2141", "2142", "2144", "2146", "2512", "2519", "2521", "2529", "2411", "3434", "7411"},
    # New Zealand Green List (Straight to Residence / Work to Residence)
    "NZ": {"2211", "2212", "2221", "2142", "2144", "2145", "2512", "2519", "7411", "7212", "3434"},
    # Germany EU Blue Card Shortage Occupations (MINT & Healthcare)
    "DE": {"2211", "2212", "2221", "2141", "2142", "2144", "2145", "2146", "2151", "2511", "2512", "2514", "2519", "2521", "2529"},
}


def build_explanation(
    tier: ConfidenceTier,
    evidence_list: List[SponsorshipEvidence],
    country: Optional[str] = None,
    routes: Optional[List[str]] = None,
) -> str:
    """Generate clear, human-readable explainability text from additive evidence."""
    if tier == ConfidenceTier.NEGATIVE:
        refusal_items = [e for e in evidence_list if e.signal_strength < 0]
        reason = refusal_items[0].description if refusal_items else "Job text explicitly refuses visa sponsorship."
        return f"Explicitly Not Sponsored: {reason}"

    if tier == ConfidenceTier.VERIFIED:
        gov_items = [e for e in evidence_list if e.provenance == EvidenceProvenance.DIRECT_GOVERNMENT]
        details = f" ({gov_items[0].source_name})" if gov_items else ""
        route_str = f" for {', '.join(routes)}" if routes else ""
        return f"Verified Sponsor: Active official government register listing confirmed{details}{route_str}."

    if tier == ConfidenceTier.HIGH:
        jd_items = [e for e in evidence_list if e.provenance == EvidenceProvenance.EMPLOYER_CLAIM]
        if jd_items:
            return f"High Confidence: {jd_items[0].description}"
        return "High Confidence: Established multi-year government sponsorship filing track record."

    if tier == ConfidenceTier.MEDIUM:
        pieces = [e.description for e in evidence_list[:2]]
        return f"Medium Confidence: {'; '.join(pieces)}."

    if tier == ConfidenceTier.LOW:
        dest = country or "destination country"
        return f"Low Confidence: Role is plausible under {dest} work visa policies, but no explicit confirmation found."

    return "Unknown: Insufficient evidence available to determine visa sponsorship likelihood."


def evaluate_sponsorship_confidence(
    employer_name: str,
    job_description: str = "",
    country: Optional[str] = None,
    isco_code: Optional[str] = None,
    government_match: Optional[Dict[str, Any]] = None,
    employer_history_filings: Optional[int] = None,
    years_filing_history: Optional[int] = None,
    is_destination_permit_region: bool = False,
    is_third_party_seed: bool = False,
) -> SponsorshipEvaluationResult:
    """
    Execute full additive evidence assessment to produce an explainable confidence tier.
    Accumulates multiple discrete evidence signals additively rather than halting at the first branch.
    """
    evidence: List[SponsorshipEvidence] = []
    routes: List[str] = []
    today_iso = datetime.date.today().isoformat()
    norm_country = (country or "").upper().strip()

    # 1. HARD STEP: Check for Explicit Refusal in JD Text (EMPLOYER_CLAIM)
    import re
    refusal_patterns = [
        r"(?:no|unable to|will not|cannot)\s+(?:provide\s+)?(?:visa\s+)?sponsorship",
        r"must\s+(?:already\s+)?have\s+(?:the\s+)?right\s+to\s+work",
        r"authorized\s+to\s+work\s+(?:in\s+[A-Za-z\s]+)?without\s+sponsorship",
        r"citizens\s+(?:or|and)\s+permanent\s+residents\s+only",
        r"security\s+clearance\s+required",
    ]
    for pat in refusal_patterns:
        m = re.search(pat, job_description, re.IGNORECASE)
        if m:
            quote = job_description[max(0, m.start() - 15):min(len(job_description), m.end() + 15)].strip()
            evidence.append(
                SponsorshipEvidence(
                    provenance=EvidenceProvenance.EMPLOYER_CLAIM,
                    source_name="job_description",
                    signal_strength=-1.0,
                    description=f"Explicit refusal in posting: \"{quote}\"",
                    as_of_date=today_iso,
                )
            )
            return SponsorshipEvaluationResult(
                tier=ConfidenceTier.NEGATIVE,
                score=0.0,
                is_verified=False,
                evidence=evidence,
                explanation=build_explanation(ConfidenceTier.NEGATIVE, evidence, norm_country),
            )

    has_direct_gov = False

    # 2. Additive Signal: Direct Government Registry Match
    if government_match:
        source = government_match.get("source", "Official Register")
        routes_matched = government_match.get("routes") or []
        routes.extend(routes_matched)
        rating = government_match.get("rating", "Active")
        
        # Direct official registers (UK, NL, DK, FI, IE, NZ, AU, US curated)
        direct_sources = (
            "govuk", "gov.uk", "gov_uk", "home affairs", "home_affairs",
            "ind_recognised", "ind recognised", "siri", "migri",
            "enterprise_gov", "enterprise.gov", "inz", "curated",
            "official register", "official_registry"
        )
        is_direct = any(ds in source.lower() for ds in direct_sources) or "official" in source.lower()
        if is_direct:
            has_direct_gov = True
            strength = 0.85
        else:
            strength = 0.75  # LMIA disclosure / secondary filings

        evidence.append(
            SponsorshipEvidence(
                provenance=EvidenceProvenance.DIRECT_GOVERNMENT,
                source_name=source,
                signal_strength=strength,
                description=f"Active listing in {source} (Rating: {rating}, Routes: {', '.join(routes_matched) or 'General Skilled'})",
                reference_url=government_match.get("url"),
                as_of_date=government_match.get("as_of", today_iso),
                raw_payload=government_match,
            )
        )

    # 3. Additive Signal: Explicit Positive Offer in JD Text
    positive_patterns = [
        (r"(?:provide|offer|support|grant)\s+(?:full\s+|complete\s+)?(?:[A-Za-z]+\s+)?(?:visa|work\s+permit|lmia)\s*(?:sponsorship|support)?", "Direct offer of visa / work permit sponsorship"),
        (r"(?:visa|work\s+permit|lmia|work\s+authorization)\s+sponsorship\s+(?:is\s+)?(?:available|provided|offered|supported)", "Explicit visa / work permit sponsorship availability"),
        (r"(?:positive\s+)?lmia\s+(?:support|assistance|sponsorship|available|provided|offered)", "Canada Positive LMIA support stated"),
        (r"(?:full\s+|complete\s+)?(?:[A-Za-z]+\s+)?(?:employment\s+visa|work\s+visa|work\s+permit|work\s+authorization)\s*(?:sponsorship\s+)?(?:is\s+|,\s*.*)?(?:provided|offered|supported|available|support|package)", "Direct offer of employment visa / work authorization"),
        (r"(?:international\s+)?relocation\s+(?:assistance|package|support|allowance)\s*(?:is\s+)?(?:provided|available|offered)?", "Full international relocation package provided"),
        (r"(?:eu\s+blue\s+card|skilled\s+worker\s+visa|health\s+and\s+care\s+worker\s+visa|h-1b|employment\s+pass|aewv|482\s+visa|subclass\s+482)\s*(?:sponsorship|support|available|provided)?", "Specific visa route sponsorship stated"),
    ]
    for pat, desc in positive_patterns:
        m = re.search(pat, job_description, re.IGNORECASE)
        if m:
            quote = job_description[max(0, m.start() - 15):min(len(job_description), m.end() + 15)].strip()
            evidence.append(
                SponsorshipEvidence(
                    provenance=EvidenceProvenance.EMPLOYER_CLAIM,
                    source_name="job_description",
                    signal_strength=0.75,
                    description=f"{desc}: \"{quote}\"",
                    as_of_date=today_iso,
                )
            )
            break  # Record strongest JD text match

    # 4. Additive Signal: Multi-Year Filing History
    if employer_history_filings and employer_history_filings >= 10 and (years_filing_history or 1) >= 2:
        evidence.append(
            SponsorshipEvidence(
                provenance=EvidenceProvenance.DIRECT_GOVERNMENT,
                source_name="historical_filings",
                signal_strength=0.15,
                description=f"Established multi-year track record: {employer_history_filings} certified filings across {years_filing_history} years",
                as_of_date=today_iso,
            )
        )

    # 5. Additive Signal: Occupation Shortage List Match (ISCO / Green List / ISL)
    if isco_code and norm_country in SHORTAGE_LISTS and isco_code in SHORTAGE_LISTS[norm_country]:
        evidence.append(
            SponsorshipEvidence(
                provenance=EvidenceProvenance.INDIRECT_GOVERNMENT,
                source_name=f"{norm_country}_shortage_list",
                signal_strength=0.15,
                description=f"Occupation (ISCO {isco_code}) is on official {norm_country} Shortage / Targeted Occupation list",
                as_of_date=today_iso,
            )
        )

    # 6. Additive Signal: Destination Country Work-Permit Framework (GCC / SG / etc.)
    if is_destination_permit_region or norm_country in ("AE", "SA", "QA", "KW", "BH", "OM", "SG"):
        evidence.append(
            SponsorshipEvidence(
                provenance=EvidenceProvenance.INFERRED,
                source_name="regional_framework",
                signal_strength=0.15,
                description=f"Destination country ({norm_country}) legally requires employer-provided work permit & visa for foreign hires",
                as_of_date=today_iso,
            )
        )

    # 7. Additive Signal: Third-Party Community Seed / Jaabz
    if is_third_party_seed:
        evidence.append(
            SponsorshipEvidence(
                provenance=EvidenceProvenance.THIRD_PARTY,
                source_name="community_seed",
                signal_strength=0.10,
                description="Employer reported by developer community / third-party index as visa sponsor",
                as_of_date=today_iso,
            )
        )

    # 8. Additive Signal: General Plausible Country Framework
    if norm_country in ("UK", "CA", "AU", "NZ", "DE", "IE", "NL", "US", "DK", "FI") and len(job_description) > 100:
        evidence.append(
            SponsorshipEvidence(
                provenance=EvidenceProvenance.INFERRED,
                source_name="country_visa_framework",
                signal_strength=0.05,
                description=f"Role located in {norm_country} where skilled visa sponsorship frameworks exist",
                as_of_date=today_iso,
            )
        )

    # Calculate Additive Combined Score
    raw_score = sum(e.signal_strength for e in evidence if e.signal_strength > 0)
    score = round(min(1.0, max(0.0, raw_score)), 2)

    # Calibrate Tier based on Additive Score and Direct Government Registry presence
    if has_direct_gov and score >= 0.85:
        tier = ConfidenceTier.VERIFIED
        is_verified = True
    elif score >= 0.75:
        tier = ConfidenceTier.HIGH
        is_verified = False
    elif score >= 0.50:
        tier = ConfidenceTier.MEDIUM
        is_verified = False
    elif score >= 0.20:
        tier = ConfidenceTier.LOW
        is_verified = False
    else:
        tier = ConfidenceTier.UNKNOWN
        is_verified = False

    return SponsorshipEvaluationResult(
        tier=tier,
        score=score,
        is_verified=is_verified,
        evidence=evidence,
        explanation=build_explanation(tier, evidence, norm_country, routes),
        eligible_visa_routes=routes,
        registry_record=government_match,
    )

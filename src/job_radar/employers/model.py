"""
src/job_radar/employers/model.py

First-Class Employer domain model for Visa Lane global intelligence.
Tracks identity, corporate lineage, operating jurisdictions, ATS platforms,
and persistent, multi-year sponsorship filing records.
"""
from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from job_radar.visa.confidence import ConfidenceTier, SponsorshipEvidence


@dataclass
class EmployerSponsorshipRecord:
    """A country-specific sponsorship intelligence record for an employer."""
    country: str  # ISO Alpha-2 or UK
    status: str  # active | certified | revoked | expired
    rating: Optional[str] = None
    licence_number: Optional[str] = None
    routes: List[str] = field(default_factory=list)
    certified_filings_count: int = 0
    first_filing_date: Optional[str] = None
    latest_filing_date: Optional[str] = None
    median_sponsored_wage: Optional[float] = None
    top_sponsored_occupations: List[str] = field(default_factory=list)
    source: str = "government_registry"
    as_of: Optional[str] = None


@dataclass
class Employer:
    """Canonical Employer entity with cross-source deduplication and persistent sponsorship history."""
    id: str  # Deterministic UUID or hash
    canonical_name: str
    normalized_name: str
    legal_names: Set[str] = field(default_factory=set)
    aliases: Set[str] = field(default_factory=set)
    domains: Set[str] = field(default_factory=set)
    hq_country: Optional[str] = None
    operating_countries: Set[str] = field(default_factory=set)
    industry: Optional[str] = None
    size_bracket: Optional[str] = None  # startup (1-50) | mid (51-500) | enterprise (501-5000) | global (5000+)
    careers_url: Optional[str] = None
    ats_platform: Optional[str] = None  # greenhouse | lever | workday | taleo | ashby | ...
    confidence_tier: ConfidenceTier = ConfidenceTier.UNKNOWN
    sponsorship_records: Dict[str, EmployerSponsorshipRecord] = field(default_factory=dict)
    active_job_ids: Set[str] = field(default_factory=set)
    historical_job_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    @classmethod
    def create(
        cls,
        name: str,
        domain: Optional[str] = None,
        hq_country: Optional[str] = None,
        ats_platform: Optional[str] = None,
    ) -> Employer:
        from job_radar.visa.normalizer import normalize_company_name
        norm = normalize_company_name(name)
        emp_id = hashlib.sha256(f"{norm}|{domain or ''}".encode("utf-8")).hexdigest()[:16]
        return cls(
            id=emp_id,
            canonical_name=name.strip(),
            normalized_name=norm,
            legal_names={name.strip()},
            aliases=set(),
            domains={domain.lower().strip()} if domain else set(),
            hq_country=hq_country,
            operating_countries={hq_country} if hq_country else set(),
            ats_platform=ats_platform,
        )

    def add_sponsorship_filing(
        self,
        country: str,
        route: str,
        filing_date: Optional[str] = None,
        wage: Optional[float] = None,
        occupation: Optional[str] = None,
        source: str = "government_registry",
        licence_number: Optional[str] = None,
    ) -> None:
        c_code = country.upper().strip()
        rec = self.sponsorship_records.get(c_code)
        if not rec:
            rec = EmployerSponsorshipRecord(
                country=c_code,
                status="active",
                routes=[route],
                certified_filings_count=1,
                first_filing_date=filing_date,
                latest_filing_date=filing_date,
                source=source,
                licence_number=licence_number,
                as_of=datetime.date.today().isoformat(),
            )
            self.sponsorship_records[c_code] = rec
        else:
            rec.certified_filings_count += 1
            if route not in rec.routes:
                rec.routes.append(route)
            if filing_date:
                if not rec.first_filing_date or filing_date < rec.first_filing_date:
                    rec.first_filing_date = filing_date
                if not rec.latest_filing_date or filing_date > rec.latest_filing_date:
                    rec.latest_filing_date = filing_date

        if occupation and occupation not in rec.top_sponsored_occupations:
            rec.top_sponsored_occupations.append(occupation)

        # Update overall confidence tier
        if rec.status == "active" and rec.certified_filings_count > 0:
            if rec.certified_filings_count >= 10:
                self.confidence_tier = ConfidenceTier.VERIFIED
            elif self.confidence_tier != ConfidenceTier.VERIFIED:
                self.confidence_tier = ConfidenceTier.HIGH

        self.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

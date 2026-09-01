"""
src/job_radar/seo/employer_profile.py

Programmatic Employer Sponsorship Profile & Public Directory Generator.
Generates structured metadata, schema.org Organization JSON-LD, and filing history profiles
for canonical employers in the Visa Lane ecosystem.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from job_radar.employers.model import Employer


@dataclass
class EmployerSEOProfile:
    """Public SEO Profile and Structured Data for a Sponsoring Employer."""
    employer_id: str
    canonical_name: str
    slug: str
    meta_title: str
    meta_description: str
    h1: str
    confidence_tier: str
    operating_countries: List[str]
    sponsorship_summary: str
    schema_org_json_ld: Dict[str, Any]
    active_job_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "employerId": self.employer_id,
            "canonicalName": self.canonical_name,
            "slug": self.slug,
            "metaTitle": self.meta_title,
            "metaDescription": self.meta_description,
            "h1": self.h1,
            "confidenceTier": self.confidence_tier,
            "operatingCountries": self.operating_countries,
            "sponsorshipSummary": self.sponsorship_summary,
            "activeJobCount": self.active_job_count,
            "schemaOrg": self.schema_org_json_ld,
        }


def generate_employer_seo_profile(employer: Employer, active_job_count: int = 0) -> EmployerSEOProfile:
    """Generate SEO metadata and schema.org Organization JSON-LD for an Employer."""
    name = employer.canonical_name
    slug = f"visa-sponsor-{name.lower().replace(' ', '-').replace(',', '')}"
    countries = list(employer.operating_countries) or ([employer.hq_country] if employer.hq_country else ["Global"])
    country_str = ", ".join(countries[:3])

    tier_str = employer.confidence_tier.value.upper()
    meta_title = f"{name} Visa Sponsorship Track Record & Jobs ({tier_str} Sponsor)"
    meta_desc = f"Explore {name}'s verified visa sponsorship history, approved visa routes, operating countries ({country_str}), and active sponsored job openings on Visa Lane."
    h1 = f"{name} — Visa Sponsorship Intelligence & Jobs"

    # Build summary
    total_filings = sum(r.certified_filings_count for r in employer.sponsorship_records.values())
    if total_filings > 0:
        summary = f"{name} is a confirmed visa sponsor with {total_filings}+ certified government filings across {len(employer.sponsorship_records)} jurisdictions."
    else:
        summary = f"{name} has demonstrated positive international hiring signals across {country_str}."

    schema = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": name,
        "url": f"https://visalane.com/employers/{slug}",
        "description": summary,
        "knowsAbout": ["Visa Sponsorship", "Global Relocation", "International Talent Hiring"],
    }

    return EmployerSEOProfile(
        employer_id=employer.id,
        canonical_name=name,
        slug=slug,
        meta_title=meta_title,
        meta_description=meta_desc,
        h1=h1,
        confidence_tier=employer.confidence_tier.value,
        operating_countries=countries,
        sponsorship_summary=summary,
        schema_org_json_ld=schema,
        active_job_count=active_job_count,
    )

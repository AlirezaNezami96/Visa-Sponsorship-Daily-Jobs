"""
src/job_radar/seo/matrix.py

Programmatic SEO Matrix Page & Intelligence Dataset Generator.
Generates structured data, landing page schemas (JobPosting + FAQPage + BreadcrumbList),
and analytical matrices across (ISCO Occupation) x (Destination Country).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from job_radar.taxonomy.isco import ISCO_UNIT_GROUPS, ISCOUnitGroup, get_country_specific_occupation_code
from job_radar.visa.confidence import SHORTAGE_LISTS

COUNTRY_VISA_FRAMEWORKS: Dict[str, Dict[str, Any]] = {
    "UK": {
        "name": "United Kingdom",
        "primary_visa": "Skilled Worker Visa / Health and Care Worker Visa",
        "min_salary_threshold": "£38,700 / annum (or discounted for ISL)",
        "processing_time": "3 - 8 weeks",
        "official_register": "GOV.UK Register of Licensed Sponsors",
    },
    "CA": {
        "name": "Canada",
        "primary_visa": "Temporary Foreign Worker Program (LMIA) / Global Talent Stream (GTS)",
        "min_salary_threshold": "Provincial median prevailing wage",
        "processing_time": "2 - 12 weeks",
        "official_register": "ESDC Positive LMIA Registry",
    },
    "AU": {
        "name": "Australia",
        "primary_visa": "Temporary Skill Shortage (TSS Subclass 482 / Core Skills)",
        "min_salary_threshold": "AUD $73,150 (TSMIT)",
        "processing_time": "4 - 12 weeks",
        "official_register": "Home Affairs Standard Business Sponsors",
    },
    "NZ": {
        "name": "New Zealand",
        "primary_visa": "Accredited Employer Work Visa (AEWV) / Green List",
        "min_salary_threshold": "NZD $29.66 / hour (Median Wage benchmark)",
        "processing_time": "3 - 6 weeks",
        "official_register": "INZ Accredited Employer Register",
    },
    "DE": {
        "name": "Germany",
        "primary_visa": "EU Blue Card / Skilled Immigration Act (Fachkräfteeinwanderungsgesetz)",
        "min_salary_threshold": "€45,300 (or €41,041 for MINT shortage)",
        "processing_time": "4 - 12 weeks",
        "official_register": "Federal Employment Agency (BA)",
    },
    "AE": {
        "name": "United Arab Emirates",
        "primary_visa": "UAE Employment Residence Visa / Green Visa / Golden Visa",
        "min_salary_threshold": "AED 5,000 - 30,000 / month depending on skill level",
        "processing_time": "1 - 3 weeks",
        "official_register": "MOHRE / GDRFA Registry",
    },
}


@dataclass
class OccupationCountryMatrixPage:
    """Structured programmatic landing page for SEO & Visa Intelligence."""
    isco_code: str
    occupation_title: str
    country_code: str
    country_name: str
    page_slug: str
    meta_title: str
    meta_description: str
    h1: str
    is_shortage_occupation: bool
    national_occupation_code: Optional[str]
    national_code_system: Optional[str]  # NOC | ANZSCO | ONET_SOC
    visa_routes: List[str]
    salary_threshold: str
    schema_org_json_ld: Dict[str, Any]
    faq_items: List[Dict[str, str]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iscoCode": self.isco_code,
            "occupationTitle": self.occupation_title,
            "countryCode": self.country_code,
            "countryName": self.country_name,
            "pageSlug": self.page_slug,
            "metaTitle": self.meta_title,
            "metaDescription": self.meta_description,
            "h1": self.h1,
            "isShortageOccupation": self.is_shortage_occupation,
            "nationalOccupationCode": self.national_occupation_code,
            "nationalCodeSystem": self.national_code_system,
            "visaRoutes": self.visa_routes,
            "salaryThreshold": self.salary_threshold,
            "faq": self.faq_items,
            "schemaOrg": self.schema_org_json_ld,
        }


def generate_matrix_page(isco_code: str, country_code: str) -> Optional[OccupationCountryMatrixPage]:
    """Generate SEO metadata and schema.org JSON-LD for an occupation x country pair."""
    unit = ISCO_UNIT_GROUPS.get(isco_code)
    if not unit:
        return None

    c_code = country_code.upper().strip()
    c_meta = COUNTRY_VISA_FRAMEWORKS.get(c_code, {
        "name": c_code,
        "primary_visa": f"{c_code} Skilled Work Visa",
        "min_salary_threshold": "Prevailing industry statutory wage",
        "processing_time": "4 - 8 weeks",
        "official_register": "National Immigration Authority",
    })

    country_name = c_meta["name"]
    title = unit.title
    slug = f"visa-sponsorship-{title.lower().replace(' ', '-').replace(',', '')}-jobs-in-{country_name.lower().replace(' ', '-')}"

    # Check shortage list
    is_shortage = isco_code in SHORTAGE_LISTS.get(c_code, set())

    # Get national occupation code
    nat_sys, nat_code = None, None
    if c_code == "CA" and unit.noc_codes:
        nat_sys, nat_code = "NOC 2021", unit.noc_codes[0]
    elif c_code in ("AU", "NZ") and unit.anzsco_codes:
        nat_sys, nat_code = "ANZSCO", unit.anzsco_codes[0]
    elif c_code == "US" and unit.onet_soc_codes:
        nat_sys, nat_code = "O*NET-SOC", unit.onet_soc_codes[0]

    meta_title = f"{title} Visa Sponsorship Jobs in {country_name} (2026 Verified List)"
    shortage_str = " (On Official Shortage List)" if is_shortage else ""
    meta_desc = f"Discover verified visa sponsored {title} jobs in {country_name}{shortage_str}. Explore government registered employers, salary thresholds ({c_meta['min_salary_threshold']}), and {c_meta['primary_visa']} routes."
    h1 = f"{title} Jobs with Visa Sponsorship in {country_name}"

    faq_items = [
        {
            "question": f"Can international {title.lower()} get visa sponsorship in {country_name}?",
            "answer": f"Yes. Employers in {country_name} can sponsor international {title.lower()} under the {c_meta['primary_visa']}. Candidates must meet minimum statutory salary requirements ({c_meta['min_salary_threshold']}).",
        },
        {
            "question": f"Is {title} on the {country_name} skills shortage list?",
            "answer": f"{'Yes, ' + title + ' is listed on the official ' + country_name + ' targeted shortage list, making visa sponsorship faster and qualifying for streamlined thresholds.' if is_shortage else 'While not formally on the shortage list, employers can still sponsor qualified candidates meeting prevailing wage standards.'}",
        },
        {
            "question": f"What is the average processing time for a {country_name} work visa?",
            "answer": f"Work visa applications in {country_name} for skilled professionals typically take {c_meta['processing_time']} once employer sponsorship documents are certified.",
        },
    ]

    # Build schema.org BreadcrumbList + FAQPage
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://visalane.com"},
                    {"@type": "ListItem", "position": 2, "name": f"Jobs in {country_name}", "item": f"https://visalane.com/country/{c_code.lower()}"},
                    {"@type": "ListItem", "position": 3, "name": title, "item": f"https://visalane.com/{slug}"},
                ],
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["question"],
                        "acceptedAnswer": {"@type": "Answer", "text": item["answer"]},
                    }
                    for item in faq_items
                ],
            },
        ],
    }

    return OccupationCountryMatrixPage(
        isco_code=isco_code,
        occupation_title=title,
        country_code=c_code,
        country_name=country_name,
        page_slug=slug,
        meta_title=meta_title,
        meta_description=meta_desc,
        h1=h1,
        is_shortage_occupation=is_shortage,
        national_occupation_code=nat_code,
        national_code_system=nat_sys,
        visa_routes=[c_meta["primary_visa"]],
        salary_threshold=c_meta["min_salary_threshold"],
        schema_org_json_ld=schema,
        faq_items=faq_items,
    )

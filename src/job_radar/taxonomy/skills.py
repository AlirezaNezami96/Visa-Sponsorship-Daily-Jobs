"""
src/job_radar/taxonomy/skills.py

Generic, occupation-aware skill and credential extraction across all global industries.
Extracts named entities, certifications, licenses, and domain skills without hard-coded occupation limits.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Broad, extensible skills & credentials dictionary by sector
SECTOR_SKILLS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "healthcare": {
        "credentials": (
            "BLS", "ACLS", "PALS", "NRP", "CCRN", "CEN", "TNCC", "CRNA", "NP",
            "GMC", "AHPRA", "NMC", "NCLEX", "USMLE", "PLAB", "AMC", "CPSO", "CPSBC"
        ),
        "clinical_specialties": (
            "ICU", "CCU", "Emergency", "Oncology", "Pediatrics", "Cardiology",
            "Dialysis", "Perioperative", "Surgical", "Geriatrics", "Phlebotomy",
            "Infection Control", "Epic EHR", "Cerner", "Meditech"
        ),
    },
    "trades_and_construction": {
        "licenses_and_certifications": (
            "Red Seal", "OSHA 10", "OSHA 30", "CSCS Card", "EPA 608", "CWB Certified",
            "AWS D1.1", "ASME", "NCCER", "Journeyman", "Master Electrician", "Gas Safe"
        ),
        "technical_skills": (
            "TIG Welding", "MIG Welding", "Stick Welding", "CNC Programming",
            "AutoCAD", "Revit", "BIM", "HVAC Diagnostics", "Pipe Fitting", "Hydraulics",
            "Pneumatics", "Blueprint Reading", "PLC Troubleshooting", "High Voltage"
        ),
    },
    "culinary_and_hospitality": {
        "certifications": (
            "ServSafe", "Food Hygiene Level 2", "Food Hygiene Level 3", "HACCP",
            "WSET Level 2", "WSET Level 3", "Sommelier", "First Aid"
        ),
        "culinary_skills": (
            "Menu Planning", "Food Costing", "Pastry Arts", "French Cuisine",
            "Italian Cuisine", "Fine Dining", "Banqueting", "Inventory Control",
            "Kitchen Management", "Opera PMS", "Micros POS"
        ),
    },
    "engineering_and_sciences": {
        "credentials": (
            "PE License", "FE", "Chartered Engineer", "CEng", "P.Eng", "Six Sigma Black Belt",
            "Six Sigma Green Belt", "PMP", "PRINCE2"
        ),
        "technical_skills": (
            "SolidWorks", "CATIA", "MATLAB", "Simulink", "ANSYS", "Finite Element Analysis",
            "FEA", "SCADA", "Reservoir Simulation", "Drilling Engineering", "Process Safety",
            "HAZOP", "ArcGIS", "Geotechnical Analysis", "Structural Design"
        ),
    },
    "finance_and_business": {
        "credentials": (
            "CPA", "ACCA", "CIMA", "CFA", "ACA", "CIA", "FRM", "Series 7", "Series 63",
            "CFP", "SHRM-CP", "SHRM-SCP", "CIPD"
        ),
        "core_skills": (
            "Financial Modeling", "Valuation", "DCF", "GAAP", "IFRS", "SOX Compliance",
            "Tax Compliance", "SAP ERP", "Oracle NetSuite", "QuickBooks", "Power BI",
            "Tableau", "Bloomberg Terminal", "Auditing", "Budgeting", "Forecasting"
        ),
    },
    "information_technology": {
        "certifications": (
            "AWS Certified", "Azure Certified", "GCP Certified", "CISSP", "CISM",
            "CompTIA Security+", "CKA", "Kubernetes", "PMP", "ITIL"
        ),
        "technical_skills": (
            "Python", "Java", "Kotlin", "Swift", "Dart", "Flutter", "Android",
            "TypeScript", "JavaScript", "React", "Node.js", "Go", "Golang", "Rust",
            "C++", "C#", ".NET", "PostgreSQL", "MySQL", "MongoDB", "Redis",
            "Docker", "Kubernetes", "Terraform", "CI/CD", "Git", "PyTorch",
            "TensorFlow", "Machine Learning", "Large Language Models", "LLMs", "NLP"
        ),
    },
    "logistics_and_transport": {
        "licenses": (
            "CDL Class A", "CDL Class B", "HGV Class 1", "HGV Class 2", "Forklift Certified",
            "Dangerous Goods", "ADR", "CPC Driver"
        ),
        "skills": (
            "Route Optimization", "Fleet Management", "Warehouse Management Systems", "WMS",
            "Inventory Auditing", "Freight Forwarding", "Customs Clearance", "Logistics Planning"
        ),
    },
}


def extract_skills_from_text(
    text: str,
    target_sector: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    Extract sector-aware skills and credentials from job text.
    Returns dictionary with categorized extracted entities.
    """
    if not text:
        return {"all_skills": [], "credentials": [], "technical_skills": []}

    text_clean = f" {text} "
    extracted_credentials: Set[str] = set()
    extracted_skills: Set[str] = set()

    sectors_to_scan = [target_sector] if target_sector and target_sector in SECTOR_SKILLS else list(SECTOR_SKILLS.keys())

    for sector in sectors_to_scan:
        categories = SECTOR_SKILLS.get(sector, {})
        for cat_name, skill_list in categories.items():
            for skill in skill_list:
                # Word boundary search matching case for short acronyms, case-insensitive for longer phrases
                if len(skill) <= 4 and skill.isupper():
                    pattern = r"\b" + re.escape(skill) + r"\b"
                    if re.search(pattern, text_clean):
                        if "credential" in cat_name or "license" in cat_name:
                            extracted_credentials.add(skill)
                        else:
                            extracted_skills.add(skill)
                else:
                    pattern = r"\b" + re.escape(skill) + r"\b"
                    if re.search(pattern, text_clean, re.IGNORECASE):
                        if "credential" in cat_name or "license" in cat_name:
                            extracted_credentials.add(skill)
                        else:
                            extracted_skills.add(skill)

    all_skills = sorted(list(extracted_credentials | extracted_skills))
    return {
        "all_skills": all_skills,
        "credentials": sorted(list(extracted_credentials)),
        "technical_skills": sorted(list(extracted_skills)),
    }

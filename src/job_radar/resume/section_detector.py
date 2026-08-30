"""Resume section boundary detector.

Detects and segments standard and unconventional resume sections across
multiple languages (English, German, French, Spanish, Portuguese, Italian, etc.).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Section header patterns across languages
SECTION_PATTERNS: Dict[str, list[str]] = {
    "summary": [
        r"\b(?:professional\s+)?summary\b",
        r"\bexecutive\s+summary\b",
        r"\bprofile\b",
        r"\babout\s+me\b",
        r"\bobjective\b",
        r"\bcareer\s+objective\b",
        r"\bprofil\b",
        r"\büber\s+mich\b",
        r"\bkurzprofil\b",
        r"\bresumen\b",
        r"\bperfil\s+profesional\b",
    ],
    "experience": [
        r"\b(?:work\s+)?experience\b",
        r"\bemployment(?:\s+history)?\b",
        r"\bwork\s+history\b",
        r"\bprofessional\s+experience\b",
        r"\bberufserfahrung\b",
        r"\bberuflicher\s+werdegang\b",
        r"\bexpérience(?:\s+professionnelle)?\b",
        r"\bexperiencia(?:\s+laboral|\s+profesional)?\b",
        r"\bexperiência\s+profissional\b",
        r"\besperienza\s+lavorativa\b",
    ],
    "education": [
        r"\beducation\b",
        r"\bacademics?\b",
        r"\bacademic\s+background\b",
        r"\bausbildung\b",
        r"\bstudium\b",
        r"\bformation(?:\s+académique)?\b",
        r"\beducación\b",
        r"\bformación\s+académica\b",
        r"\bformação\s+acadêmica\b",
        r"\bistruzione\b",
    ],
    "skills": [
        r"\b(?:technical\s+)?skills\b",
        r"\bcore\s+competencies\b",
        r"\btechnologies\b",
        r"\bproficiencies\b",
        r"\bkenntnisse\b",
        r"\bfähigkeiten\b",
        r"\bcompétences\b",
        r"\bhabilidades\b",
        r"\bcompetencias\b",
        r"\bcompetenze\b",
    ],
    "projects": [
        r"\bprojects\b",
        r"\bpersonal\s+projects\b",
        r"\bkey\s+projects\b",
        r"\bprojekte\b",
        r"\bprojets\b",
        r"\bproyectos\b",
        r"\bprojetos\b",
    ],
    "certifications": [
        r"\bcertifications?\b",
        r"\bcertificates?\b",
        r"\blicenses?\b",
        r"\bzertifikate\b",
        r"\bcertifications\b",
        r"\bcertificaciones\b",
        r"\bcertificações\b",
    ],
    "languages": [
        r"\blanguages?\b",
        r"\bsprachen\b",
        r"\blangues\b",
        r"\bidiomas\b",
        r"\blínguas\b",
        r"\blingue\b",
    ],
    "volunteer_work": [
        r"\bvolunteer(?:ing|\s+work|\s+experience)?\b",
        r"\bcommunity\s+service\b",
        r"\behrenamt\b",
        r"\bbénévolat\b",
        r"\bvoluntariado\b",
    ],
    "publications": [
        r"\bpublications?\b",
        r"\bpapers?\b",
        r"\bpublikationen\b",
        r"\bpublicaciones\b",
    ],
    "awards": [
        r"\bawards?(?:\s+and\s+honors?)?\b",
        r"\bhonors?\b",
        r"\bachievements?\b",
        r"\bauszeichnungen\b",
        r"\bprix\b",
        r"\bdistinciones\b",
        r"\bprêmios\b",
    ],
    "interests": [
        r"\binterests?\b",
        r"\bhobbies\b",
        r"\binteressen\b",
        r"\bcentres\s+d'intérêt\b",
        r"\bintereses\b",
        r"\binteresses\b",
    ],
    "references": [
        r"\breferences?\b",
        r"\breferenzen\b",
        r"\bréférences\b",
        r"\breferencias\b",
    ],
}


def _compile_patterns() -> list[tuple[re.Pattern, str]]:
    compiled = []
    for section_name, patterns in SECTION_PATTERNS.items():
        combined = "|".join(patterns)
        compiled.append((re.compile(rf"^(?:[#*•\-_\s]*)(?:{combined})[:\s]*$", re.IGNORECASE | re.MULTILINE), section_name))
    return compiled


_COMPILED_SECTION_PATTERNS = _compile_patterns()


def detect_sections_from_text(raw_text: str) -> List[str]:
    """Detect presence of sections by parsing line headings in raw text."""
    if not raw_text:
        return []

    detected: list[str] = []
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    for line in lines:
        if len(line) > 50:  # Headings are generally short
            continue
        for pattern, section_name in _COMPILED_SECTION_PATTERNS:
            if pattern.match(line) and section_name not in detected:
                detected.append(section_name)

    return detected


def detect_sections_from_parsed_data(parsed_data: Dict[str, Any]) -> List[str]:
    """Detect non-empty sections from structured resume JSON."""
    detected = []
    for section_name in SECTION_PATTERNS.keys():
        val = parsed_data.get(section_name)
        if val is None:
            continue
        if isinstance(val, list) and len(val) > 0:
            detected.append(section_name)
        elif isinstance(val, str) and val.strip():
            detected.append(section_name)
        elif isinstance(val, dict) and len(val) > 0:
            detected.append(section_name)
    return detected


def detect_all_sections(raw_text: str, parsed_data: Optional[Dict[str, Any]] = None) -> List[str]:
    """Union of text-detected and data-detected sections."""
    from_text = detect_sections_from_text(raw_text)
    from_data = detect_sections_from_parsed_data(parsed_data or {})
    # Preserve order
    seen = set()
    result = []
    for s in from_data + from_text:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result

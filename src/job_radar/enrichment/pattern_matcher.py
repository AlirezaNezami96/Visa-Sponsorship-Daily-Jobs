"""Corporate email pattern matcher.

Generates common corporate email syntax patterns based on a person's name and company domain.
All generated emails are strictly classified as 'pattern_guess' with low confidence.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List


def clean_name_token(token: str) -> str:
    return re.sub(r"[^a-zA-Z]", "", token.lower()).strip()


def generate_email_patterns(
    first_name: str,
    last_name: str,
    company_domain: str,
) -> List[Dict[str, Any]]:
    """Generate common corporate email permutations.

    Patterns:
      1. first.last@domain.com
      2. first@domain.com
      3. f.last@domain.com
      4. firstlast@domain.com
      5. flast@domain.com
      6. last.first@domain.com
    """
    fn = clean_name_token(first_name)
    ln = clean_name_token(last_name)
    domain = company_domain.lower().replace("http://", "").replace("https://", "").split("/")[0].strip()

    if not domain or (not fn and not ln):
        return []

    patterns: List[Dict[str, Any]] = []

    if fn and ln:
        patterns.append({
            "email": f"{fn}.{ln}@{domain}",
            "pattern": "first.last",
            "email_status": "pattern_guess",
            "confidence": 30,
        })
        patterns.append({
            "email": f"{fn[0]}.{ln}@{domain}",
            "pattern": "f.last",
            "email_status": "pattern_guess",
            "confidence": 25,
        })
        patterns.append({
            "email": f"{fn}{ln}@{domain}",
            "pattern": "firstlast",
            "email_status": "pattern_guess",
            "confidence": 20,
        })
        patterns.append({
            "email": f"{fn[0]}{ln}@{domain}",
            "pattern": "flast",
            "email_status": "pattern_guess",
            "confidence": 20,
        })
        patterns.append({
            "email": f"{fn}@{domain}",
            "pattern": "first",
            "email_status": "pattern_guess",
            "confidence": 15,
        })
    elif fn:
        patterns.append({
            "email": f"{fn}@{domain}",
            "pattern": "first",
            "email_status": "pattern_guess",
            "confidence": 15,
        })

    return patterns


def get_generic_company_emails(company_domain: str) -> List[str]:
    """Return standard corporate department mailboxes."""
    domain = company_domain.lower().replace("http://", "").replace("https://", "").split("/")[0].strip()
    if not domain:
        return []
    return [
        f"careers@{domain}",
        f"talent@{domain}",
        f"recruiting@{domain}",
        f"jobs@{domain}",
        f"hr@{domain}",
    ]

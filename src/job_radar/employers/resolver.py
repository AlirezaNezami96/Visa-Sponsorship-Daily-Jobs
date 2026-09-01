"""
src/job_radar/employers/resolver.py

High-precision Employer Identity Resolution Engine.
Resolves messy employer strings, variations, DBA names, and foreign subsidiaries into canonical Employer entities.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple

from job_radar.employers.model import Employer
from job_radar.visa.normalizer import normalize_company_name

logger = logging.getLogger(__name__)


class EmployerResolver:
    """In-memory + indexed resolver matching raw job postings to canonical Employer entities."""

    def __init__(self, employers: Optional[List[Employer]] = None) -> None:
        self.employers_by_id: Dict[str, Employer] = {}
        self.domain_index: Dict[str, str] = {}  # domain -> employer_id
        self.norm_name_index: Dict[str, str] = {}  # normalized_name -> employer_id
        self.token_index: Dict[str, Set[str]] = {}  # token -> set of employer_ids

        if employers:
            for emp in employers:
                self.register_employer(emp)

    def register_employer(self, employer: Employer) -> None:
        """Add an employer to all resolution indexes."""
        self.employers_by_id[employer.id] = employer

        # 1. Index domains
        for d in employer.domains:
            d_clean = d.lower().strip()
            if d_clean:
                self.domain_index[d_clean] = employer.id

        # 2. Index normalized primary name
        if employer.normalized_name:
            self.norm_name_index[employer.normalized_name] = employer.id

        # 3. Index aliases and legal names
        for alias in employer.aliases | employer.legal_names:
            norm_alias = normalize_company_name(alias)
            if norm_alias:
                self.norm_name_index[norm_alias] = employer.id

        # 4. Token index for candidate lookup
        tokens = set(employer.normalized_name.split())
        for alias in employer.aliases:
            tokens.update(normalize_company_name(alias).split())
        for token in tokens:
            if len(token) >= 3:
                self.token_index.setdefault(token, set()).add(employer.id)

    def resolve(
        self,
        name: str,
        domain: Optional[str] = None,
        country: Optional[str] = None,
        create_if_missing: bool = True,
    ) -> Tuple[Employer, float, str]:
        """
        Resolve raw name / domain / country to a canonical Employer entity.
        Returns (Employer, confidence_score, resolution_method).
        """
        if not name and not domain:
            raise ValueError("Must provide at least employer name or domain")

        # 1. Exact Domain Match (Highest Confidence: 1.0)
        if domain:
            d_clean = domain.lower().strip().replace("http://", "").replace("https://", "").split("/")[0]
            # Strip subdomains like careers., jobs., boards.
            d_root = re.sub(r"^(?:careers\.|jobs\.|boards\.|apply\.|www\.)", "", d_clean)
            if d_clean in self.domain_index:
                emp = self.employers_by_id[self.domain_index[d_clean]]
                return emp, 1.0, "exact_domain"
            if d_root in self.domain_index:
                emp = self.employers_by_id[self.domain_index[d_root]]
                return emp, 1.0, "root_domain"

        norm_name = normalize_company_name(name) if name else ""

        # 2. Exact Normalized Name Match (Confidence: 0.98)
        if norm_name and norm_name in self.norm_name_index:
            emp = self.employers_by_id[self.norm_name_index[norm_name]]
            return emp, 0.98, "exact_normalized_name"

        # 3. Token-Sharing Candidate Filter & Jaccard / Levenshtein Match
        tokens = [t for t in norm_name.split() if len(t) >= 3]
        candidate_ids: Set[str] = set()
        for t in tokens:
            if t in self.token_index:
                candidate_ids.update(self.token_index[t])

        best_candidate: Optional[Employer] = None
        best_score = 0.0

        for cand_id in candidate_ids:
            cand = self.employers_by_id[cand_id]
            # SequenceMatcher similarity against canonical and aliases
            sim = SequenceMatcher(None, norm_name, cand.normalized_name).ratio()
            for alias in cand.aliases:
                sim = max(sim, SequenceMatcher(None, norm_name, normalize_company_name(alias)).ratio())

            if sim > best_score:
                best_score = sim
                best_candidate = cand

        if best_candidate and best_score >= 0.92:
            return best_candidate, best_score, "fuzzy_name_match"

        # 4. Create new Employer if not found
        if create_if_missing:
            new_emp = Employer.create(name=name, domain=domain, hq_country=country)
            self.register_employer(new_emp)
            return new_emp, 1.0, "new_entity_created"

        raise KeyError(f"Could not resolve employer: {name}")

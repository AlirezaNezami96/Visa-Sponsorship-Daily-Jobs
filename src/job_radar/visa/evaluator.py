"""
src/job_radar/visa/evaluator.py

Evaluates visa sponsorship confidence and candidate work-authorization fit
for any job posting using official government registers and JD text analysis.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from job_radar.visa.db import load_all_aliases, load_all_sponsors, DEFAULT_DB_PATH
from job_radar.visa.models import AuthFit, SponsorRecord, VisaConfidence
from job_radar.visa.normalizer import build_token_index, match_company_to_sponsor, normalize_company_name

logger = logging.getLogger(__name__)

THRESHOLDS_PATH = Path(__file__).parent / "thresholds.yaml"

_known_sponsors_cache: Optional[Dict[str, Any]] = None


def load_known_sponsors() -> Dict[str, Any]:
    """Load known sponsors allowlist (cached)."""
    global _known_sponsors_cache
    if _known_sponsors_cache is None:
        search_paths = [
            Path(__file__).resolve().parent.parent.parent.parent / "data" / "known_sponsors.json",
            Path.cwd() / "data" / "known_sponsors.json",
            Path("/app/data/known_sponsors.json"),
        ]
        data = None
        for p in search_paths:
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    break
                except Exception as e:
                    logger.debug("Failed loading known sponsors from %s: %s", p, e)

        if data and isinstance(data, dict):
            cache: Dict[str, Any] = {}
            for sponsor in data.get("sponsors", []):
                name = sponsor.get("name", "")
                norm = normalize_company_name(name)
                if norm:
                    cache[norm] = sponsor
                for alias in sponsor.get("aliases", []):
                    alias_norm = normalize_company_name(alias)
                    if alias_norm:
                        cache[alias_norm] = sponsor
            _known_sponsors_cache = cache
        else:
            _known_sponsors_cache = {}
    return _known_sponsors_cache


def check_known_sponsor(company: str) -> Optional[Dict[str, Any]]:
    """Fast-path check: is this company a known visa sponsor?"""
    if not company:
        return None
    known = load_known_sponsors()
    norm = normalize_company_name(company)
    if not norm:
        return None

    # Exact normalized match
    if norm in known:
        return known[norm]

    # Substring / token match
    norm_words = set(norm.split())
    for key, sponsor in known.items():
        if key == norm:
            return sponsor
        if len(key) >= 3 and (key in norm_words or re.search(r"\b" + re.escape(key) + r"\b", norm)):
            return sponsor

    return None


EXPLICIT_NO_PATTERNS = [
    r"\bno\s+(visa\s+)?sponsorship\b",
    r"\bwill\s+not\s+(provide\s+)?sponsor(ship)?\b",
    r"\bunable\s+to\s+sponsor\b",
    r"\bcannot\s+sponsor\b",
    r"\bnot\s+offering\s+visa\s+sponsorship\b",
    r"\bmust\s+(already\s+)?have\s+(the\s+)?right\s+to\s+work\b",
    r"\bmust\s+be\s+legally\s+authorized\s+to\s+work\s+without\s+sponsorship\b",
    r"\bno\s+visa\s+(support|assistance)\b",
    r"\bcitizens\s+(or|and)\s+permanent\s+residents\s+only\b",
    r"\b(us|uk|eu)\s+citizenship\s+required\b",
    r"\bsecurity\s+clearance\s+required\b",
    r"\bno\s+c2c\b",
]

STATED_IN_JD_PATTERNS = [
    r"\bvisa\s+sponsorship\s+(is\s+)?(available|provided|offered|supported)\b",
    r"\bwe\s+(can\s+)?sponsor\s+(visas?|work\s+permits?)\b",
    r"\bwilling\s+to\s+sponsor\b",
    r"\brelocation\s+(assistance|package|support|allowance)\s+(is\s+)?(provided|available|offered)\b",
    r"\b(eu\s+blue\s+card|skilled\s+worker\s+visa)\s+(sponsorship|support|assistance)\b",
    r"\bglobal\s+talent\s+stream\b",
    r"\blmia\s+support\b",
    r"\bopen\s+to\s+relocation\b",
]

_EXPLICIT_NO_REGEX = re.compile("|".join(EXPLICIT_NO_PATTERNS), re.IGNORECASE)
_STATED_IN_JD_REGEX = re.compile("|".join(STATED_IN_JD_PATTERNS), re.IGNORECASE)


class VisaEvaluator:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._sponsors: Optional[Dict[str, SponsorRecord]] = None
        self._negative_sponsors: Optional[Dict[str, SponsorRecord]] = None
        self._aliases: Optional[Dict[str, str]] = None
        self._token_index: Optional[Dict[str, Any]] = None
        self._match_cache: Dict[str, Tuple[Any, str]] = {}
        self._thresholds: Dict[str, Any] = {}
        self._load_thresholds()

    def _load_thresholds(self) -> None:
        if THRESHOLDS_PATH.exists():
            try:
                with open(THRESHOLDS_PATH, "r", encoding="utf-8") as f:
                    self._thresholds = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning("Failed to load visa thresholds: %s", e)

    def _ensure_db_loaded(self) -> None:
        if self._sponsors is None:
            all_sponsors = load_all_sponsors(db_path=self.db_path)
            self._aliases = load_all_aliases(db_path=self.db_path)

            # Partition into positive and negative sponsors
            self._sponsors = {}
            self._negative_sponsors = {}
            for norm, record in all_sponsors.items():
                is_negative = (
                    record.rating == "NON_COMPLIANT"
                    or record.confidence_tier == "negative"
                    or record.extra.get("negative_signal") is True
                )
                if is_negative:
                    self._negative_sponsors[norm] = record
                else:
                    self._sponsors[norm] = record

            logger.info(
                "Loaded %d positive and %d negative sponsor records.",
                len(self._sponsors), len(self._negative_sponsors),
            )

            # Inverted token index over positive sponsor names only
            self._token_index = build_token_index(self._sponsors)
            self._match_cache = {}

    def _check_negative_signal(self, company_name: str, country: Optional[str] = None) -> Optional[SponsorRecord]:
        """Check if a company matches a negative/non-compliant sponsor record."""
        if not self._negative_sponsors:
            return None

        norm = normalize_company_name(company_name)
        if not norm:
            return None

        # Direct match
        if norm in self._negative_sponsors:
            record = self._negative_sponsors[norm]
            # If country is specified, only match same-country negative signals
            if country and record.country != country.upper():
                return None
            return record

        # Fuzzy match against negative sponsors
        neg_match, neg_method = match_company_to_sponsor(
            company_name=company_name,
            sponsors_by_norm=self._negative_sponsors,
            alias_map=self._aliases or {},
        )
        if neg_match:
            if country and neg_match.country != country.upper():
                return None
            return neg_match

        return None

    @staticmethod
    def _infer_country_from_location(location: str) -> Optional[str]:
        """Infer ISO-2 country code from a location string."""
        loc = location.lower()
        mappings = {
            "united kingdom": "UK", ", uk": "UK", "london": "UK", "england": "UK",
            "scotland": "UK", "wales": "UK", "manchester": "UK", "birmingham": "UK",
            "canada": "CA", "toronto": "CA", "vancouver": "CA", "montreal": "CA",
            "ottawa": "CA", "calgary": "CA",
            "united states": "US", ", us": "US", "usa": "US", "new york": "US",
            "san francisco": "US", "seattle": "US", "chicago": "US", "boston": "US",
            "germany": "DE", "berlin": "DE", "munich": "DE", "frankfurt": "DE",
            "netherlands": "NL", "amsterdam": "NL", "rotterdam": "NL", "hague": "NL",
            "ireland": "IE", "dublin": "IE", "cork": "IE",
            "denmark": "DK", "copenhagen": "DK", "aarhus": "DK",
            "finland": "FI", "helsinki": "FI",
            "australia": "AU", "sydney": "AU", "melbourne": "AU",
            "new zealand": "NZ", "auckland": "NZ", "wellington": "NZ",
            "france": "FR", "paris": "FR",
            "sweden": "SE", "stockholm": "SE",
            "switzerland": "CH", "zurich": "CH",
            "singapore": "SG",
            "poland": "PL", "warsaw": "PL", "krakow": "PL",
        }
        for key, code in mappings.items():
            if key in loc:
                return code
        return None

    def evaluate_job(
        self,
        job: Dict[str, Any],
        candidate_auth: Optional[Dict[str, Any]] = None,
    ) -> Tuple[VisaConfidence, AuthFit, Dict[str, Any]]:
        """
        Evaluate visa sponsorship confidence and candidate authorization fit.

        Returns:
            (visa_confidence, auth_fit, sponsor_meta)
        """
        self._ensure_db_loaded()

        company = job.get("company") or ""
        title = job.get("title") or ""
        location = job.get("location") or ""
        desc = job.get("description") or job.get("snippet") or ""
        remote_scope = (job.get("remote_scope") or "").lower()

        # Infer country from location for negative-signal matching
        inferred_country = self._infer_country_from_location(location)

        candidate_needs_sponsorship = True
        willing_countries = ["UK", "DE", "NL", "IE", "CA"]
        if candidate_auth:
            candidate_needs_sponsorship = candidate_auth.get("need_sponsorship", True)
            willing_countries = candidate_auth.get("willing_to_relocate", willing_countries)

        sponsor_meta: Dict[str, Any] = {
            "matched_sponsor": None,
            "match_type": "none",
            "country": None,
            "rating": None,
            "routes": [],
            "notes": "",
        }

        # 0. Check for NEGATIVE government signal (non-compliant employer list)
        neg_record = self._check_negative_signal(company, inferred_country)
        if neg_record:
            sponsor_meta["matched_sponsor"] = neg_record.legal_name
            sponsor_meta["match_type"] = "negative_government_list"
            sponsor_meta["country"] = neg_record.country
            sponsor_meta["rating"] = neg_record.rating
            sponsor_meta["notes"] = (
                f"Employer found on official {neg_record.country} non-compliant employer list "
                f"(source: {neg_record.source}). "
                f"{neg_record.extra.get('consequence', 'Compliance action taken.')}"
            )
            return VisaConfidence.EXPLICIT_NO, AuthFit.INELIGIBLE, sponsor_meta

        # 1. Check for EXPLICIT NO in JD text (highest priority)
        if _EXPLICIT_NO_REGEX.search(desc):
            # Check if remote worldwide exception applies
            if remote_scope == "worldwide":
                return VisaConfidence.EXPLICIT_NO, AuthFit.REMOTE_OK, {"notes": "JD disclaims local sponsorship, but worldwide remote is permitted"}
            return VisaConfidence.EXPLICIT_NO, AuthFit.INELIGIBLE, {"notes": "Explicit negative sponsorship disclaimer in job description"}

        # 2. FAST PATH: Check Known Sponsor Allowlist
        known = check_known_sponsor(company)
        if known:
            sponsor_meta["matched_sponsor"] = known.get("name")
            sponsor_meta["match_type"] = "known_sponsor_allowlist"
            sponsor_meta["sponsor_name"] = known.get("name")
            sponsor_meta["countries"] = known.get("countries", [])
            sponsor_meta["source"] = "known_sponsors_allowlist"
            sponsor_meta["notes"] = "Confirmed major visa sponsor with established international hiring program"
            return VisaConfidence.KNOWN_SPONSOR, AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE, sponsor_meta

        # 3. Check for POSITIVE sponsorship / relocation mentions in JD
        if _STATED_IN_JD_REGEX.search(desc):
            sponsor_meta["notes"] = "Explicit visa sponsorship or relocation offered in posting"
            return VisaConfidence.STATED_IN_JD, AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE, sponsor_meta

        # 3. Match company against official sponsor registers
        matched_sponsor, match_type = match_company_to_sponsor(
            company_name=company,
            sponsors_by_norm=self._sponsors or {},
            alias_map=self._aliases or {},
            token_index=self._token_index,
            match_cache=self._match_cache,
        )

        if matched_sponsor:
            sponsor_meta["matched_sponsor"] = matched_sponsor.legal_name
            sponsor_meta["match_type"] = match_type
            sponsor_meta["country"] = matched_sponsor.country
            sponsor_meta["rating"] = matched_sponsor.rating
            sponsor_meta["routes"] = matched_sponsor.routes
            sponsor_meta["extra"] = matched_sponsor.extra

            if matched_sponsor.source == "govuk_register":
                sponsor_meta["notes"] = f"Licensed UK Sponsor ({matched_sponsor.rating})"
                return VisaConfidence.ON_SPONSOR_LIST, AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE, sponsor_meta
            elif matched_sponsor.source == "inz_accredited_register":
                sponsor_meta["notes"] = f"Accredited New Zealand Sponsor (AEWV) - {matched_sponsor.rating}"
                return VisaConfidence.ON_SPONSOR_LIST, AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE, sponsor_meta
            elif matched_sponsor.source == "home_affairs_sponsors":
                sponsor_meta["notes"] = f"Approved Australian Standard Business Sponsor ({', '.join(matched_sponsor.routes)})"
                return VisaConfidence.ON_SPONSOR_LIST, AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE, sponsor_meta
            elif matched_sponsor.source in ("ind_recognised_register", "siri_fasttrack", "migri_certified", "enterprise_gov_ie_permits", "curated_official_registry"):
                sponsor_meta["notes"] = f"Official {matched_sponsor.country} Government Verified Sponsor ({matched_sponsor.rating})"
                return VisaConfidence.ON_SPONSOR_LIST, AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE, sponsor_meta
            elif matched_sponsor.source == "esdc_lmia":
                sponsor_meta["notes"] = f"Approved Canadian LMIA Employer ({matched_sponsor.extra.get('approved_positions', 1)} positions)"
                return VisaConfidence.ON_SPONSOR_LIST, AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE, sponsor_meta
            elif matched_sponsor.source == "dol_lca":
                lca_count = matched_sponsor.extra.get("lca_count_12m", 0)
                sponsor_meta["notes"] = f"US DOL LCA historical filings: {lca_count} certified in past 12m"
                return VisaConfidence.HISTORICAL_FILINGS, AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE, sponsor_meta
            else:
                sponsor_meta["notes"] = f"Registered Sponsor: {matched_sponsor.legal_name} ({matched_sponsor.rating})"
                return VisaConfidence.ON_SPONSOR_LIST, AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE, sponsor_meta

        # 4. Check salary floor threshold if country has a statutory floor (e.g. DE EU Blue Card, NL HSM)
        salary_min = job.get("salary_min")
        if salary_min:
            for country_code in ["DE", "NL", "IE", "UK"]:
                if country_code.lower() in location.lower():
                    floor_info = self._thresholds.get(country_code, {})
                    sponsor_meta["country"] = country_code
                    sponsor_meta["salary_floor_check"] = f"Salary evaluated against {country_code} floor"

        # 5. Remote Worldwide check
        if remote_scope == "worldwide" or "worldwide" in location.lower() or "anywhere" in location.lower():
            return VisaConfidence.UNKNOWN, AuthFit.REMOTE_OK, {"notes": "Worldwide remote role"}

        # 6. Default: Unknown
        auth_fit = AuthFit.SPONSOR_REQUIRED_AND_PLAUSIBLE if not candidate_needs_sponsorship else AuthFit.SPONSOR_UNKNOWN
        return VisaConfidence.UNKNOWN, auth_fit, sponsor_meta

    def score_visa_sponsorship(
        self,
        job: Dict[str, Any],
        llm_visa_mention: Optional[str] = None,
        llm_visa_quote: Optional[str] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> Tuple[str, float, List[str]]:
        """
        Computes weighted visa score (0.0 to 1.0), distinct visa_status, and evidence list.
        Statuses: 'sponsors' | 'likely' | 'opt_friendly' | 'unknown' | 'no'
        """
        self._ensure_db_loaded()

        company = str(job.get("company", "")).strip()
        desc = str(job.get("description", "") or job.get("description_text", "") or job.get("snippet", "") or "")
        title = str(job.get("title", "")).strip()

        evidence: List[str] = []

        # 1. Registry or Known Sponsor signal (0.0 or 1.0)
        known = check_known_sponsor(company)
        reg_val = 0.0
        if known:
            reg_val = 1.0
            evidence.append(f"Confirmed Major Visa Sponsor: {known.get('name')}")
        else:
            matched_sponsor, match_type = match_company_to_sponsor(
                company_name=company,
                sponsors_by_norm=self._sponsors or {},
                alias_map=self._aliases or {},
                token_index=self._token_index,
                match_cache=self._match_cache,
            )

            if matched_sponsor:
                reg_val = 1.0
                if matched_sponsor.source == "govuk_register":
                    routes_str = f" ({', '.join(matched_sponsor.routes)})" if matched_sponsor.routes else ""
                    evidence.append(f"UK Home Office Licensed Sponsor: {matched_sponsor.legal_name}{routes_str}")
                elif matched_sponsor.source == "dol_lca":
                    lca_count = matched_sponsor.extra.get("lca_count_12m", 0)
                    evidence.append(f"US DOL LCA Filings: {matched_sponsor.legal_name} ({lca_count} certified)")
                else:
                    evidence.append(f"Verified Sponsor Registry: {matched_sponsor.legal_name}")

        # 2. LLM JD Signal
        llm_mention_clean = (llm_visa_mention or "").lower().strip()
        if not llm_mention_clean:
            # Fallback to deterministic regex on JD if LLM not run
            if _EXPLICIT_NO_REGEX.search(desc):
                llm_mention_clean = "no"
                evidence.append("Explicit refusal in job description")
            elif _STATED_IN_JD_REGEX.search(desc):
                llm_mention_clean = "sponsors"
                evidence.append("Explicit sponsorship/relocation offered in job description")
            else:
                llm_mention_clean = "unspecified"

        if llm_mention_clean == "no":
            llm_val = 0.0
            if "Explicit refusal" not in str(evidence):
                evidence.append("Posting disclaims visa sponsorship")
        elif llm_mention_clean == "sponsors":
            llm_val = 1.0
            if llm_visa_quote:
                evidence.append(f"JD Quote: \"{llm_visa_quote}\"")
            elif "sponsorship/relocation offered" not in str(evidence):
                evidence.append("Posting offers visa sponsorship")
        elif llm_mention_clean == "opt_friendly":
            llm_val = 0.6
            evidence.append("OPT / STEM-OPT friendly position")
        else:
            llm_val = 0.4  # Unspecified

        # 3. Keyword Signal
        combined_text = f"{title} {desc}".lower()
        keyword_signal = any(k in combined_text for k in (
            "visa sponsorship", "sponsorship available", "relocation assistance",
            "work authorization", "opt friendly", "stem opt", "skilled worker visa"
        ))
        kw_val = 1.0 if keyword_signal else 0.0
        if keyword_signal and "keyword" not in str(evidence):
            evidence.append("Visa/relocation keywords matched in listing")

        # 4. Weighted Formula
        w_reg = weights.get("registry", 0.50) if weights else 0.50
        w_llm = weights.get("llm", 0.35) if weights else 0.35
        w_kw = weights.get("keyword", 0.15) if weights else 0.15

        raw_score = (w_reg * reg_val) + (w_llm * llm_val) + (w_kw * kw_val)
        visa_score = round(min(max(raw_score, 0.0), 1.0), 3)

        # 5. Status Mapping
        if llm_mention_clean == "no":
            visa_status = "no"
        elif llm_mention_clean == "opt_friendly":
            visa_status = "opt_friendly"
        elif visa_score >= 0.70 or (reg_val == 1.0 and llm_val == 1.0):
            visa_status = "sponsors"
        elif visa_score >= 0.50 or reg_val == 1.0:
            visa_status = "likely"
        else:
            visa_status = "unknown"

        return visa_status, visa_score, evidence


# Global singleton
_GLOBAL_EVALUATOR: Optional[VisaEvaluator] = None


def get_visa_evaluator(db_path: Path = DEFAULT_DB_PATH) -> VisaEvaluator:
    global _GLOBAL_EVALUATOR
    if _GLOBAL_EVALUATOR is None:
        _GLOBAL_EVALUATOR = VisaEvaluator(db_path=db_path)
    return _GLOBAL_EVALUATOR


def evaluate_job_visa(
    job: Dict[str, Any],
    candidate_auth: Optional[Dict[str, Any]] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[VisaConfidence, AuthFit, Dict[str, Any]]:
    return get_visa_evaluator(db_path=db_path).evaluate_job(job=job, candidate_auth=candidate_auth)


def score_job_visa(
    job: Dict[str, Any],
    llm_visa_mention: Optional[str] = None,
    llm_visa_quote: Optional[str] = None,
    weights: Optional[Dict[str, float]] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[str, float, List[str]]:
    return get_visa_evaluator(db_path=db_path).score_visa_sponsorship(
        job=job,
        llm_visa_mention=llm_visa_mention,
        llm_visa_quote=llm_visa_quote,
        weights=weights,
    )

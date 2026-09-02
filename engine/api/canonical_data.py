"""
Canonical country, visa-type, and locale reference data for VisaLane.
Provides normalized lookup mappings, aliases, and multilingual translation dictionaries.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TypedDict


class SupportedLocale(TypedDict):
    code: str
    label: str
    native_label: str
    is_rtl: bool
    default: bool


SUPPORTED_LOCALES: List[SupportedLocale] = [
    {
        "code": "en",
        "label": "English",
        "native_label": "English",
        "is_rtl": False,
        "default": True,
    },
    {
        "code": "es",
        "label": "Spanish",
        "native_label": "Español",
        "is_rtl": False,
        "default": False,
    },
    {
        "code": "pt",
        "label": "Portuguese",
        "native_label": "Português",
        "is_rtl": False,
        "default": False,
    },
    {
        "code": "ar",
        "label": "Arabic",
        "native_label": "العربية",
        "is_rtl": True,
        "default": False,
    },
]

_SUPPORTED_LOCALE_CODES = {l["code"] for l in SUPPORTED_LOCALES}


class CanonicalCountry(TypedDict):
    slug: str
    code: str
    name: str
    aliases: List[str]


CANONICAL_COUNTRIES: List[CanonicalCountry] = [
    {
        "slug": "germany",
        "code": "DE",
        "name": "Germany",
        "aliases": ["de", "deu", "deutschland", "allemagne", "alemania"],
    },
    {
        "slug": "united-kingdom",
        "code": "GB",
        "name": "United Kingdom",
        "aliases": ["gb", "uk", "gbr", "great britain", "england", "scotland", "wales"],
    },
    {
        "slug": "united-states",
        "code": "US",
        "name": "United States",
        "aliases": ["us", "usa", "united states of america", "america"],
    },
    {
        "slug": "netherlands",
        "code": "NL",
        "name": "Netherlands",
        "aliases": ["nl", "nld", "holland", "the netherlands"],
    },
    {
        "slug": "ireland",
        "code": "IE",
        "name": "Ireland",
        "aliases": ["ie", "irl", "republic of ireland"],
    },
    {
        "slug": "sweden",
        "code": "SE",
        "name": "Sweden",
        "aliases": ["se", "swe", "sverige"],
    },
    {
        "slug": "france",
        "code": "FR",
        "name": "France",
        "aliases": ["fr", "fra", "republique francaise"],
    },
    {
        "slug": "canada",
        "code": "CA",
        "name": "Canada",
        "aliases": ["ca", "can"],
    },
    {
        "slug": "australia",
        "code": "AU",
        "name": "Australia",
        "aliases": ["au", "aus"],
    },
    {
        "slug": "japan",
        "code": "JP",
        "name": "Japan",
        "aliases": ["jp", "jpn", "nippon", "nihon"],
    },
]


COUNTRY_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "germany": {
        "en": "Germany",
        "es": "Alemania",
        "pt": "Alemanha",
        "ar": "ألمانيا",
    },
    "united-kingdom": {
        "en": "United Kingdom",
        "es": "Reino Unido",
        "pt": "Reino Unido",
        "ar": "المملكة المتحدة",
    },
    "united-states": {
        "en": "United States",
        "es": "Estados Unidos",
        "pt": "Estados Unidos",
        "ar": "الولايات المتحدة",
    },
    "netherlands": {
        "en": "Netherlands",
        "es": "Países Bajos",
        "pt": "Países Baixos",
        "ar": "هولندا",
    },
    "ireland": {
        "en": "Ireland",
        "es": "Irlanda",
        "pt": "Irlanda",
        "ar": "أيرلندا",
    },
    "sweden": {
        "en": "Sweden",
        "es": "Suecia",
        "pt": "Suécia",
        "ar": "السويد",
    },
    "france": {
        "en": "France",
        "es": "Francia",
        "pt": "França",
        "ar": "فرنسا",
    },
    "canada": {
        "en": "Canada",
        "es": "Canadá",
        "pt": "Canadá",
        "ar": "كندا",
    },
    "australia": {
        "en": "Australia",
        "es": "Australia",
        "pt": "Austrália",
        "ar": "أستراليا",
    },
    "japan": {
        "en": "Japan",
        "es": "Japón",
        "pt": "Japão",
        "ar": "اليابان",
    },
}


class CanonicalVisaType(TypedDict):
    slug: str
    name: str
    country_code: str
    country_slug: str
    aliases: List[str]


CANONICAL_VISA_TYPES: List[CanonicalVisaType] = [
    {
        "slug": "eu-blue-card",
        "name": "EU Blue Card",
        "country_code": "DE",
        "country_slug": "germany",
        "aliases": ["blue card", "eu blue card", "blaue karte", "tarjeta azul"],
    },
    {
        "slug": "skilled-worker",
        "name": "Skilled Worker",
        "country_code": "GB",
        "country_slug": "united-kingdom",
        "aliases": ["skilled worker visa", "tier 2", "uk skilled worker", "tier 2 general"],
    },
    {
        "slug": "scale-up-worker",
        "name": "Scale-up Worker",
        "country_code": "GB",
        "country_slug": "united-kingdom",
        "aliases": ["scale-up", "scaleup", "scale up visa"],
    },
    {
        "slug": "global-talent",
        "name": "Global Talent",
        "country_code": "GB",
        "country_slug": "united-kingdom",
        "aliases": ["global talent visa", "tech nation", "tier 1 exceptional talent"],
    },
    {
        "slug": "h-1b",
        "name": "H-1B",
        "country_code": "US",
        "country_slug": "united-states",
        "aliases": ["h1b", "h-1b specialty occupation", "h-1b cap", "h1-b"],
    },
    {
        "slug": "o-1",
        "name": "O-1",
        "country_code": "US",
        "country_slug": "united-states",
        "aliases": ["o1", "o-1a", "o-1b", "extraordinary ability"],
    },
    {
        "slug": "l-1",
        "name": "L-1",
        "country_code": "US",
        "country_slug": "united-states",
        "aliases": ["l1", "l-1a", "l-1b", "intra-company transfer"],
    },
    {
        "slug": "tn-visa",
        "name": "TN Visa",
        "country_code": "US",
        "country_slug": "united-states",
        "aliases": ["tn", "nafta", "usmca professional"],
    },
    {
        "slug": "highly-skilled-migrant",
        "name": "Highly Skilled Migrant",
        "country_code": "NL",
        "country_slug": "netherlands",
        "aliases": ["kennismigrant", "hsm", "dutch highly skilled migrant", "ind sponsor"],
    },
    {
        "slug": "critical-skills-employment-permit",
        "name": "Critical Skills Employment Permit",
        "country_code": "IE",
        "country_slug": "ireland",
        "aliases": ["csep", "irish critical skills", "green card ireland", "critical skills permit"],
    },
    {
        "slug": "general-employment-permit",
        "name": "General Employment Permit",
        "country_code": "IE",
        "country_slug": "ireland",
        "aliases": ["gep", "irish work permit", "standard employment permit"],
    },
    {
        "slug": "swedish-work-permit",
        "name": "Swedish Work Permit",
        "country_code": "SE",
        "country_slug": "sweden",
        "aliases": ["arbetstillstand", "migrationsverket permit", "sweden work visa"],
    },
    {
        "slug": "passeport-talent",
        "name": "Passeport Talent",
        "country_code": "FR",
        "country_slug": "france",
        "aliases": ["talent passport", "french tech visa", "salarié qualifié"],
    },
    {
        "slug": "global-skills-strategy",
        "name": "Global Skills Strategy",
        "country_code": "CA",
        "country_slug": "canada",
        "aliases": ["gss", "global talent stream", "gts canada", "lmia exempt tech"],
    },
    {
        "slug": "subclass-482-tss",
        "name": "TSS 482 Visa",
        "country_code": "AU",
        "country_slug": "australia",
        "aliases": ["subclass 482", "temporary skill shortage", "482 visa", "tss visa"],
    },
    {
        "slug": "subclass-186-ens",
        "name": "ENS 186 Visa",
        "country_code": "AU",
        "country_slug": "australia",
        "aliases": ["subclass 186", "employer nomination scheme", "186 pr"],
    },
    {
        "slug": "highly-skilled-professional",
        "name": "Highly Skilled Professional",
        "country_code": "JP",
        "country_slug": "japan",
        "aliases": ["hsp visa", "points-based visa japan", "tokutei katsudo"],
    },
]


VISA_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "eu-blue-card": {
        "en": "EU Blue Card",
        "es": "Tarjeta Azul de la UE",
        "pt": "Cartão Azul da UE",
        "ar": "البطاقة الزرقاء للاتحاد الأوروبي",
    },
    "skilled-worker": {
        "en": "Skilled Worker",
        "es": "Trabajador Cualificado",
        "pt": "Trabalhador Qualificado",
        "ar": "تأشيرة العامل الماهر",
    },
    "scale-up-worker": {
        "en": "Scale-up Worker",
        "es": "Trabajador Scale-up",
        "pt": "Trabalhador Scale-up",
        "ar": "تأشيرة الشركات الصاعدة (Scale-up)",
    },
    "global-talent": {
        "en": "Global Talent",
        "es": "Talento Global",
        "pt": "Talento Global",
        "ar": "تأشيرة المواهب العالمية",
    },
    "h-1b": {
        "en": "H-1B",
        "es": "Visa H-1B",
        "pt": "Visto H-1B",
        "ar": "تأشيرة H-1B",
    },
    "o-1": {
        "en": "O-1",
        "es": "Visa O-1",
        "pt": "Visto O-1",
        "ar": "تأشيرة O-1 للمهارات الاستثنائية",
    },
    "l-1": {
        "en": "L-1",
        "es": "Visa L-1",
        "pt": "Visto L-1",
        "ar": "تأشيرة L-1 للنقل الداخلي",
    },
    "tn-visa": {
        "en": "TN Visa",
        "es": "Visa TN",
        "pt": "Visto TN",
        "ar": "تأشيرة TN المهنية",
    },
    "highly-skilled-migrant": {
        "en": "Highly Skilled Migrant",
        "es": "Migrante Altamente Cualificado",
        "pt": "Migrante Altamente Qualificado",
        "ar": "مهاجر عالي المهارة",
    },
    "critical-skills-employment-permit": {
        "en": "Critical Skills Employment Permit",
        "es": "Permiso de Empleo de Habilidades Críticas",
        "pt": "Autorização de Trabalho para Competências Críticas",
        "ar": "تصريح توظيف المهارات الحرجة",
    },
    "general-employment-permit": {
        "en": "General Employment Permit",
        "es": "Permiso General de Empleo",
        "pt": "Autorização Geral de Emprego",
        "ar": "تصريح العمل العام",
    },
    "swedish-work-permit": {
        "en": "Swedish Work Permit",
        "es": "Permiso de Trabajo Sueco",
        "pt": "Visto de Trabalho Sueco",
        "ar": "تصريح العمل السويدي",
    },
    "passeport-talent": {
        "en": "Passeport Talent",
        "es": "Pasaporte de Talento",
        "pt": "Passaporte de Talento",
        "ar": "جواز سفر المواهب الفرنسي",
    },
    "global-skills-strategy": {
        "en": "Global Skills Strategy",
        "es": "Estrategia de Habilidades Globales",
        "pt": "Estratégia de Competências Globais",
        "ar": "استراتيجية المهارات العالمية الكندية",
    },
    "subclass-482-tss": {
        "en": "TSS 482 Visa",
        "es": "Visa TSS 482",
        "pt": "Visto TSS 482",
        "ar": "تأشيرة TSS 482 الأسترالية",
    },
    "subclass-186-ens": {
        "en": "ENS 186 Visa",
        "es": "Visa ENS 186",
        "pt": "Visto ENS 186",
        "ar": "تأشيرة ENS 186 الدائمة",
    },
    "highly-skilled-professional": {
        "en": "Highly Skilled Professional",
        "es": "Profesional Altamente Cualificado",
        "pt": "Profissional Altamente Qualificado",
        "ar": "تأشيرة المهني عالي المهارة اليابانية",
    },
}


# Precompute lookup maps
_COUNTRY_ALIAS_MAP: Dict[str, CanonicalCountry] = {}
for c in CANONICAL_COUNTRIES:
    _COUNTRY_ALIAS_MAP[c["slug"].lower()] = c
    _COUNTRY_ALIAS_MAP[c["code"].lower()] = c
    _COUNTRY_ALIAS_MAP[c["name"].lower()] = c
    for alias in c["aliases"]:
        _COUNTRY_ALIAS_MAP[alias.lower()] = c

_VISA_ALIAS_MAP: Dict[str, CanonicalVisaType] = {}
for v in CANONICAL_VISA_TYPES:
    _VISA_ALIAS_MAP[v["slug"].lower()] = v
    _VISA_ALIAS_MAP[v["name"].lower()] = v
    for alias in v["aliases"]:
        _VISA_ALIAS_MAP[alias.lower()] = v


def get_supported_locales() -> List[SupportedLocale]:
    """Return all supported UI and content locales."""
    return SUPPORTED_LOCALES


def find_country(query: Optional[str]) -> Optional[CanonicalCountry]:
    """Resolve a country by slug, ISO code, or common name."""
    if not query:
        return None
    cleaned = query.strip().lower()
    return _COUNTRY_ALIAS_MAP.get(cleaned)


def find_visa_type(query: Optional[str]) -> Optional[CanonicalVisaType]:
    """Resolve a visa type by slug, name, or alias."""
    if not query:
        return None
    cleaned = query.strip().lower()
    return _VISA_ALIAS_MAP.get(cleaned)


def match_visa_type_from_string(text: Optional[str]) -> Optional[CanonicalVisaType]:
    """Check if a string contains or matches any canonical visa type."""
    if not text:
        return None
    cleaned = text.strip().lower()
    if cleaned in _VISA_ALIAS_MAP:
        return _VISA_ALIAS_MAP[cleaned]
    for alias, v in _VISA_ALIAS_MAP.items():
        if len(alias) >= 3 and alias in cleaned:
            return v
    return None


def get_localized_country_name(country_slug_or_code: str, locale: Optional[str] = "en") -> Tuple[str, bool]:
    """
    Returns (localized_name, is_fallback).
    If locale translation doesn't exist or is unsupported, falls back to English with is_fallback=True.
    """
    canon = find_country(country_slug_or_code)
    if not canon:
        return country_slug_or_code, True

    slug = canon["slug"]
    loc = (locale or "en").strip().lower()

    trans_map = COUNTRY_TRANSLATIONS.get(slug, {})
    if loc in trans_map:
        return trans_map[loc], False

    # English fallback
    return trans_map.get("en", canon["name"]), True


def get_localized_visa_name(visa_slug_or_name: str, locale: Optional[str] = "en") -> Tuple[str, bool]:
    """
    Returns (localized_name, is_fallback).
    If locale translation doesn't exist or is unsupported, falls back to English with is_fallback=True.
    """
    canon = find_visa_type(visa_slug_or_name)
    if not canon:
        return visa_slug_or_name, True

    slug = canon["slug"]
    loc = (locale or "en").strip().lower()

    trans_map = VISA_TRANSLATIONS.get(slug, {})
    if loc in trans_map:
        return trans_map[loc], False

    # English fallback
    return trans_map.get("en", canon["name"]), True

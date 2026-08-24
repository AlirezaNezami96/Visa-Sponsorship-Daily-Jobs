"""Tests for the overseas verified source registry (data/overseas_sources.json)."""
import json
from pathlib import Path

from job_radar.sources.overseas.registry import (
    ENABLED_CATEGORIES,
    KNOWN_CATEGORIES,
    get_enabled_sources,
    load_registry,
    registry_stats,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = REPO_ROOT / "data" / "overseas_sources.json"

# These domains are permanently blacklisted — they must never be fetchable.
BLACKLISTED_DOMAINS = [
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "monster.com",
    "careerbuilder.com",
    "simplyhired.com",
    "snagajob.com",
    "theladders.com",
    "ladders.com",
    "dice.com",
]


def _is_blacklisted(domain: str) -> bool:
    d = domain.lower()
    return any(d == b or d.endswith("." + b) for b in BLACKLISTED_DOMAINS)


def test_registry_file_parses_as_list():
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert len(raw) == 573


def test_registry_loads_with_expected_counts():
    sources = load_registry()
    assert len(sources) == 573
    enabled = [s for s in sources if s.enabled]
    assert len(enabled) >= 230
    assert len(enabled) == 248


def test_registry_domains_are_unique():
    sources = load_registry()
    domains = [s.domain for s in sources]
    assert len(domains) == len(set(domains))


def test_enabled_entries_have_start_urls_and_known_category():
    for s in load_registry():
        assert s.category in KNOWN_CATEGORIES
        if s.enabled:
            assert len(s.start_urls) >= 1
            assert s.category in ENABLED_CATEGORIES


def test_blacklisted_domains_are_never_enabled():
    for s in load_registry():
        assert not (_is_blacklisted(s.domain) and s.enabled), f"{s.domain} must not be enabled"


def test_blacklist_rejected_audit_trail_exists():
    rejected_path = REPO_ROOT / "docs" / "overseas_sources_rejected.json"
    data = json.loads(rejected_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 397
    tos = [d for d in data if d.get("reason") == "tos_blacklist"]
    tos_domains = {d["domain"].lower() for d in tos}
    # The big anti-bot boards must be present in the rejection audit trail.
    for required in ("linkedin.com", "indeed.com", "pk.indeed.com", "glassdoor.com", "dice.com"):
        assert required in tos_domains, f"{required} must appear as tos_blacklist"


def test_no_blacklisted_domain_is_fetchable():
    """The registry loader must never surface a blacklisted enabled source."""
    for s in get_enabled_sources():
        assert not _is_blacklisted(s.domain), f"{s.domain} must never be fetchable"


def test_registry_stats_and_category_filter():
    stats = registry_stats()
    assert stats["total"] == 573
    assert stats["enabled"] == 248
    assert stats["enabled"] + stats["disabled"] == stats["total"]
    gov = get_enabled_sources(categories={"government"})
    assert len(gov) == 66
    assert all(s.category == "government" for s in gov)
    all_enabled = get_enabled_sources()
    assert len(all_enabled) == 248

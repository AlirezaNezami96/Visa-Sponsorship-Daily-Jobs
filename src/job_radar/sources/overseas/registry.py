"""Loader for the overseas expansion source registry (data/overseas_sources.json).

The registry is a build-time-verified, hand-curated list of overseas job
sources (government portals, manpower agencies, niche boards, aggregators,
visa specialists). It is data, not generated: this module only loads and
validates it. Sources are never invented, swapped, or auto-discovered.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

REGISTRY_FILENAME = "overseas_sources.json"
REGISTRY_ENV_VAR = "OVERSEAS_REGISTRY_PATH"

# Categories that may be enabled (flag-gated via config.overseas_categories).
ENABLED_CATEGORIES: Set[str] = {
    "government",
    "manpower_agency",
    "aggregator",
    "remote_board",
    "visa_specialist",
    "unknown_board",
}

# Categories that exist in the registry but are intentionally disabled
# (anti-bot commercial boards, info portals, newspapers, covered sources).
DISABLED_ONLY_CATEGORIES: Set[str] = {
    "commercial_board",
    "gov_info",
    "info_or_low_value",
    "newspaper",
    "covered_existing",
}

KNOWN_CATEGORIES = ENABLED_CATEGORIES | DISABLED_ONLY_CATEGORIES


@dataclass(frozen=True)
class OverseasSource:
    """A single verified overseas source entry."""

    domain: str
    start_urls: Tuple[str, ...]
    category: str
    tier: str
    enabled: bool
    country: str
    rss_capable: bool
    sitemap_capable: bool
    wordpress: bool


def _find_repo_root() -> Path:
    """Walk up from this file to the first ancestor containing pyproject.toml."""
    current = Path(__file__).resolve()
    for candidate in [current.parent, *current.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError(
        "Could not locate repository root (no ancestor of "
        f"{__file__} contains pyproject.toml). Overseas registry requires the repo layout."
    )


def _registry_path() -> Path:
    """Resolve the registry file path, honoring OVERSEAS_REGISTRY_PATH (used by tooling/benchmarks)."""
    override = os.environ.get(REGISTRY_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return _find_repo_root() / "data" / REGISTRY_FILENAME


@lru_cache(maxsize=1)
def _load_registry_cached(path_str: str) -> Tuple[OverseasSource, ...]:
    path = Path(path_str)
    if not path.is_file():
        raise FileNotFoundError(
            f"Overseas registry file not found at {path}. "
            f"Expected data/{REGISTRY_FILENAME} at the repository root "
            f"(build it from the verified source list or set {REGISTRY_ENV_VAR})."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Overseas registry {path} is not valid JSON: {e}") from e

    if not isinstance(raw, list):
        raise ValueError(f"Overseas registry {path} must be a JSON list of source entries.")

    sources: List[OverseasSource] = []
    seen_domains: Set[str] = set()

    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Overseas registry entry #{idx} is not an object: {entry!r}")
        domain = str(entry.get("domain") or "").strip().lower()
        if not domain:
            raise ValueError(f"Overseas registry entry #{idx} has no domain.")
        if domain in seen_domains:
            raise ValueError(f"Overseas registry contains duplicate domain '{domain}' — data bug, aborting.")
        seen_domains.add(domain)

        category = str(entry.get("category") or "").strip()
        if category not in KNOWN_CATEGORIES:
            raise ValueError(f"Overseas registry entry '{domain}' has unknown category '{category}'.")

        start_urls = tuple(str(u) for u in (entry.get("start_urls") or []))
        enabled = bool(entry.get("enabled"))
        if enabled and not start_urls:
            raise ValueError(f"Overseas registry entry '{domain}' is enabled but has no start_urls.")

        capabilities = entry.get("capabilities") or {}
        sources.append(
            OverseasSource(
                domain=domain,
                start_urls=start_urls,
                category=category,
                tier=str(entry.get("tier") or "unknown"),
                enabled=enabled,
                country=str(entry.get("country") or "Unknown"),
                rss_capable=bool(capabilities.get("rss")),
                sitemap_capable=bool(capabilities.get("sitemap")),
                wordpress=bool(capabilities.get("wordpress")),
            )
        )

    logger.debug("Loaded overseas registry from %s: %d entries (%d enabled)", path, len(sources), sum(1 for s in sources if s.enabled))
    return tuple(sources)


def load_registry() -> List[OverseasSource]:
    """Load and validate the full overseas registry (cached)."""
    return list(_load_registry_cached(str(_registry_path())))


def get_enabled_sources(categories: Optional[Set[str]] = None) -> List[OverseasSource]:
    """Return enabled sources, optionally filtered to a set of categories."""
    return [
        s
        for s in load_registry()
        if s.enabled and (categories is None or s.category in categories)
    ]


def registry_stats() -> Dict[str, object]:
    """Aggregate counts by category/tier/enabled status for logging and diagnostics."""
    sources = load_registry()
    by_category: Dict[str, int] = {}
    by_tier: Dict[str, int] = {}
    enabled_count = 0
    enabled_by_category: Dict[str, int] = {}
    for s in sources:
        by_category[s.category] = by_category.get(s.category, 0) + 1
        by_tier[s.tier] = by_tier.get(s.tier, 0) + 1
        if s.enabled:
            enabled_count += 1
            enabled_by_category[s.category] = enabled_by_category.get(s.category, 0) + 1
    return {
        "total": len(sources),
        "enabled": enabled_count,
        "disabled": len(sources) - enabled_count,
        "by_category": by_category,
        "by_tier": by_tier,
        "enabled_by_category": enabled_by_category,
    }

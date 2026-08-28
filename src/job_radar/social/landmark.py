"""Landmark photo sourcing from Wikimedia Commons for brand cards.

Contract (no exceptions):
- Only licenses in the allowlist (Public Domain, CC0, CC BY, CC BY-SA) are
  ever used. NC/ND variants and anything unknown are rejected.
- Successful fetches are uploaded to Supabase Storage
  (media bucket: landmarks/{country}-{city}.jpg) and cached in `media_assets`
  for 30 days; a fresh cached asset is reused without any network call.
- Any failure (network, license, decode, storage) returns (None, None) and the
  card renderer falls back to its deterministic background. Never raise.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "VisaLane-JobRadar/1.0 (https://github.com/AlirezaNezami96/Visa-Sponsorship-Daily-Jobs)"
BUCKET_NAME = "media"
MIN_SOURCE_WIDTH = 2000
CACHE_MAX_AGE_DAYS = 30


def license_allowed(short_name: str | None) -> bool:
    """True only for Public Domain / CC0 / CC BY / CC BY-SA families.

    NC and ND variants are explicitly NOT allowed. Unknown or missing
    licenses are rejected — an unlicensed image is never used.
    """
    if not short_name:
        return False
    s = short_name.strip().lower()
    if not s:
        return False
    if "nc" in s or "nd" in s:
        return False
    if s.startswith("cc0") or s == "cc zero" or "public domain" in s or s in ("pd", "pd-us"):
        return True
    if s.startswith("cc by-sa"):
        return True
    return bool(s.startswith("cc by"))


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _slug(country: str, city: str) -> str:
    raw = f"{_norm(country)}-{_norm(city)}"
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or "unknown"


def _strip_html(value: str | None) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def _imageinfo_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
    pages = (data.get("query") or {}).get("pages") or {}
    infos: list[dict[str, Any]] = []
    for page in pages.values():
        infos.extend(page.get("imageinfo") or [])
    return infos


def _candidate_ok(info: dict[str, Any]) -> bool:
    license_short = ((info.get("extmetadata") or {}).get("LicenseShortName") or {}).get("value")
    if not license_allowed(license_short):
        return False
    width = int(info.get("width") or 0)
    thumb_width = int(info.get("thumbwidth") or 0)
    return width >= MIN_SOURCE_WIDTH or thumb_width >= MIN_SOURCE_WIDTH


def _candidate_meta(info: dict[str, Any], storage_path: str | None) -> dict[str, Any]:
    ext = info.get("extmetadata") or {}
    license_short = (ext.get("LicenseShortName") or {}).get("value")
    attribution = _strip_html((ext.get("Artist") or {}).get("value"))
    return {
        "source_url": info.get("descriptionurl") or info.get("url"),
        "license": license_short,
        "attribution": attribution,
        "storage_path": storage_path,
    }


def _cached_asset(client, city: str, country: str, max_age_days: int) -> dict[str, Any] | None:
    try:
        res = (
            client.table("media_assets")
            .select("*")
            .eq("asset_kind", "landmark")
            .eq("city", _norm(city))
            .eq("country", _norm(country))
            .execute()
        )
    except Exception as exc:
        logger.debug("media_assets lookup failed: %s", exc)
        return None
    rows = res.data or []
    row = rows[0] if isinstance(rows, list) and rows else (rows if isinstance(rows, dict) else None)
    if not row or not row.get("storage_path"):
        return None
    fetched_at = row.get("fetched_at")
    if fetched_at:
        try:
            age = datetime.datetime.now(datetime.UTC) - datetime.datetime.fromisoformat(str(fetched_at))
            if age > datetime.timedelta(days=max_age_days):
                return None
        except ValueError:
            return None
    return row


def _search_commons(session, city: str, country: str) -> dict[str, Any] | None:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"{city} {country} landmark",
        "gsrnamespace": "6",
        "gsrlimit": "10",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size",
        "iiurlwidth": str(MIN_SOURCE_WIDTH),
        "format": "json",
    }
    resp = session.get(WIKIMEDIA_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    if resp.status_code != 200:
        return None
    data = resp.json()
    for info in _imageinfo_candidates(data):
        if _candidate_ok(info):
            return info
    return None


def fetch_landmark_photo(
    client,
    city: str | None,
    country: str | None,
    *,
    storage=None,
    session=None,
    max_age_days: int = CACHE_MAX_AGE_DAYS,
) -> tuple[bytes | None, dict[str, Any] | None]:
    """Fetch (or reuse) a licensed landmark photo for (city, country).

    Returns (photo_bytes, metadata) or (None, None). Never raises.
    """
    city = (city or "").strip()
    country = (country or "").strip()
    if not city or not country:
        return None, None

    try:
        cached = _cached_asset(client, city, country, max_age_days)
        if cached and storage is not None:
            photo = storage.read_storage_bytes(BUCKET_NAME, cached["storage_path"])
            if photo:
                logger.debug("Landmark cache hit for %s/%s", city, country)
                meta = {
                    "source_url": cached.get("source_url"),
                    "license": cached.get("license"),
                    "attribution": cached.get("attribution"),
                    "storage_path": cached.get("storage_path"),
                }
                return photo, meta

        if session is None:
            import requests

            session = requests.Session()

        info = _search_commons(session, city, country)
        if not info:
            return None, None

        url = info.get("thumburl") or info.get("url")
        if not url:
            return None, None
        resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
        if resp.status_code != 200 or not resp.content:
            return None, None
        photo = resp.content

        storage_path: str | None = None
        if storage is not None:
            storage_path = f"landmarks/{_slug(country, city)}.jpg"
            try:
                storage.upload_storage_file(BUCKET_NAME, storage_path, photo, mime_type="image/jpeg")
            except Exception as exc:
                logger.warning("landmark upload failed (%s/%s): %s", city, country, exc)
                storage_path = None

        meta = _candidate_meta(info, storage_path)
        try:
            client.table("media_assets").upsert(
                {
                    "asset_kind": "landmark",
                    "city": _norm(city),
                    "country": _norm(country),
                    "source_url": meta["source_url"],
                    "license": meta["license"],
                    "attribution": meta["attribution"],
                    "storage_path": storage_path,
                    "width": info.get("width"),
                    "height": info.get("height"),
                },
                on_conflict="asset_kind,city,country",
            ).execute()
        except Exception as exc:
            logger.warning("media_assets upsert failed (%s/%s): %s", city, country, exc)

        return photo, meta
    except Exception as exc:
        logger.warning("landmark fetch failed for %s/%s: %s", city, country, exc)
        return None, None

"""Extraction ladder for overseas sources.

Per page, strategies are attempted in order and the first that yields
at least one job wins:

  A. RSS/Atom (feedparser)       -> RawOverseasJob(strategy="rss")
  B. JSON-LD JobPosting          -> RawOverseasJob(strategy="jsonld")
  C. DOM card heuristic          -> RawOverseasJob(strategy="dom_cards")

No network I/O happens here: functions operate on already-fetched content.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import feedparser
from selectolax.parser import HTMLParser

from job_radar.sources.overseas.geo import normalize_destination

logger = logging.getLogger(__name__)

STRATEGY_RSS = "rss"
STRATEGY_JSONLD = "jsonld"
STRATEGY_DOM = "dom_cards"

_ANCHOR_RE = re.compile(r"job|vacanc|career|position|apply|walk-?in", re.IGNORECASE)
_NAV_TEXT_RE = re.compile(r"\b(home|about|contact|login|sign\s*in|register|privacy|terms|faq|search)\b", re.IGNORECASE)
_COMPANY_RE = re.compile(r"(?:Company|Employer|Organization)\s*:\s*([^|;\n]{2,80})", re.IGNORECASE)
_CURRENCIES = r"AED|SAR|QAR|KWD|OMR|BHD|USD|EUR|GBP|PKR|INR|BDT"
_SALARY_RANGE_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(?:-|\u2013|to)\s*(\d[\d,]*(?:\.\d+)?)\s?(" + _CURRENCIES + r")\b"
)
_SALARY_SINGLE_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?(" + _CURRENCIES + r")\b")
_SALARY_CUR_FIRST_RE = re.compile(r"(" + _CURRENCIES + r")\s?(\d[\d,]*(?:\.\d+)?)")
_SALARY_CUR_FIRST_RANGE_RE = re.compile(
    r"(" + _CURRENCIES + r")\s?(\d[\d,]*(?:\.\d+)?)\s*(?:-|\u2013|to)\s*(\d[\d,]*(?:\.\d+)?)"
)
_DATE_ISO_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_DATE_DMY_RE = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{4})",
    re.IGNORECASE,
)
_DATE_REL_RE = re.compile(r"(\d+)\s+(day|week|month)s?\s+ago", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_FEED_DISCOVERY_RE = re.compile(
    r'<link[^>]+type=["\']application/(?:rss\+xml|atom\+xml)["\'][^>]*>',
    re.IGNORECASE,
)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

_GENERIC_AUTHOR_TOKENS = ("admin", "editor", "webmaster", "noreply", "no-reply", "postmaster", "author")


@dataclass(frozen=True)
class RawOverseasJob:
    """A raw job extracted from an overseas source, pre-canonicalization."""

    title: str
    apply_url: str
    company: Optional[str]
    location: Optional[str]
    description: str
    posted_at: Optional[datetime]
    salary_min: Optional[float]
    salary_max: Optional[float]
    salary_currency: Optional[str]
    salary_period: Optional[str]
    strategy: str
    detail_url: Optional[str]


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _html_to_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace via selectolax."""
    if not html:
        return ""
    try:
        tree = HTMLParser(html)
        for bad in tree.css("script,style"):
            bad.decompose()
        text = tree.text(separator=" ")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    return _collapse_ws(text)


def _parse_struct_time_utc(struct_time) -> Optional[datetime]:
    if not struct_time:
        return None
    try:
        return datetime(*struct_time[:6], tzinfo=timezone.utc)
    except Exception:
        return None


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        normalized = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_card_date(text: str) -> Optional[datetime]:
    """Parse dates out of card text: ISO, d Month yyyy, 'N days/weeks/months ago'."""
    if not text:
        return None
    m = _DATE_ISO_RE.search(text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    m = _DATE_DMY_RE.search(text)
    if m:
        try:
            day = int(m.group(1))
            month = _MONTHS.get(m.group(2).lower()[:3])
            year = int(m.group(3))
            if month and 1 <= day <= 31 and 2000 <= year <= 2100:
                return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            pass
    m = _DATE_REL_RE.search(text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        try:
            now_ts = datetime.now(timezone.utc).timestamp()
            factor = 1 if unit == "day" else (7 if unit == "week" else 30)
            return datetime.fromtimestamp(now_ts - amount * factor * 86400, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            pass
    return None


def _parse_salary_from_text(text: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Return (min, max, currency) parsed from free text.

    Handles both number-first ("2500 AED") and currency-first ("AED 2500")
    formats, with optional ranges.
    """
    if not text:
        return None, None, None
    m = _SALARY_CUR_FIRST_RANGE_RE.search(text)
    if m:
        try:
            return float(m.group(2).replace(",", "")), float(m.group(3).replace(",", "")), m.group(1).upper()
        except ValueError:
            pass
    m = _SALARY_RANGE_RE.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", "")), float(m.group(2).replace(",", "")), m.group(3).upper()
        except ValueError:
            pass
    m = _SALARY_CUR_FIRST_RE.search(text)
    if m:
        try:
            return float(m.group(2).replace(",", "")), None, m.group(1).upper()
        except ValueError:
            pass
    m = _SALARY_SINGLE_RE.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", "")), None, m.group(2).upper()
        except ValueError:
            pass
    return None, None, None


def discover_feed_urls(html: str, base_url: str) -> List[str]:
    """Auto-discover <link rel=alternate type=application/rss+xml|atom+xml> hrefs."""
    if not html:
        return []
    urls: List[str] = []
    head = html[:20000]
    for tag_match in _FEED_DISCOVERY_RE.finditer(head):
        href_match = _HREF_RE.search(tag_match.group(0))
        if href_match:
            urls.append(urljoin(base_url, href_match.group(1)))
    return urls


# ── Strategy A: RSS/Atom ──

def extract_rss(content: str, base_url: str) -> List[RawOverseasJob]:
    """Parse RSS/Atom feed content into raw jobs via feedparser."""
    jobs: List[RawOverseasJob] = []
    if not content:
        return jobs
    try:
        feed = feedparser.parse(content)
    except Exception as e:
        logger.debug("RSS parse failed for %s: %s", base_url, e)
        return jobs

    feed_title = _collapse_ws(feed.feed.get("title") or "") or None

    for entry in feed.entries:
        title = _collapse_ws(entry.get("title") or "")
        link = entry.get("link") or ""
        if link:
            link = urljoin(base_url, link)
        if not title and not link:
            continue

        summary_html = entry.get("summary") or entry.get("description") or ""
        description = _html_to_text(summary_html) or title

        posted_at = _parse_struct_time_utc(entry.get("published_parsed")) or _parse_struct_time_utc(
            entry.get("updated_parsed")
        )

        author = _collapse_ws(str(entry.get("author") or entry.get("dc_creator") or ""))
        company: Optional[str] = None
        if author:
            author_low = author.lower()
            looks_like_employer = (
                len(author) > 2
                and "@" not in author
                and not any(tok in author_low for tok in _GENERIC_AUTHOR_TOKENS)
            )
            if looks_like_employer:
                company = author
        if not company:
            company = feed_title

        raw_location = entry.get("location") if isinstance(entry.get("location"), str) else ""
        found_country = normalize_destination(f"{summary_html} {title} {raw_location}")
        location = _collapse_ws(raw_location) or found_country

        salary_min, salary_max, currency = _parse_salary_from_text(description)

        if not title:
            title = description[:120] or "Untitled"

        jobs.append(
            RawOverseasJob(
                title=title,
                apply_url=link,
                company=company,
                location=location,
                description=description,
                posted_at=posted_at,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_currency=currency,
                salary_period=None,
                strategy=STRATEGY_RSS,
                detail_url=link or None,
            )
        )
    return jobs


# ── Strategy B: JSON-LD ──

def _is_job_posting(obj: object) -> bool:
    if not isinstance(obj, dict):
        return False
    types = obj.get("@type")
    if isinstance(types, str):
        return types.lower() == "jobposting"
    if isinstance(types, list):
        return any(isinstance(t, str) and t.lower() == "jobposting" for t in types)
    return False


def _collect_jsonld_job_postings(node: object, out: List[dict], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(node, list):
        for item in node:
            _collect_jsonld_job_postings(item, out, depth + 1)
        return
    if not isinstance(node, dict):
        return
    if _is_job_posting(node):
        out.append(node)
    graph = node.get("@graph")
    if graph is not None:
        _collect_jsonld_job_postings(graph, out, depth + 1)
    node_type = node.get("@type")
    type_names = node_type if isinstance(node_type, list) else [node_type]
    if any(isinstance(t, str) and t.lower() == "itemlist" for t in type_names):
        _collect_jsonld_job_postings(node.get("itemListElement"), out, depth + 1)
    item = node.get("item")
    if isinstance(item, (dict, list)):
        _collect_jsonld_job_postings(item, out, depth + 1)


def _jsonld_location(obj: dict) -> str:
    locs = obj.get("jobLocation")
    if isinstance(locs, dict):
        loc_list = [locs]
    elif isinstance(locs, list):
        loc_list = locs
    else:
        return ""
    parts: List[str] = []
    for loc in loc_list:
        if isinstance(loc, str):
            parts.append(loc)
            continue
        if not isinstance(loc, dict):
            continue
        address = loc.get("address")
        if isinstance(address, str):
            parts.append(address)
        elif isinstance(address, dict):
            locality = address.get("addressLocality") or ""
            country = address.get("addressCountry")
            if isinstance(country, dict):
                country = country.get("name") or ""
            if locality:
                parts.append(str(locality))
            if country:
                parts.append(str(country))
        elif isinstance(loc.get("name"), str):
            parts.append(loc["name"])
    return _collapse_ws(", ".join(parts))


def _jsonld_url(url_val: object, base_url: str) -> str:
    if isinstance(url_val, str):
        return urljoin(base_url, url_val)
    if isinstance(url_val, dict):
        for key in ("url", "absoluteURL", "@id"):
            if isinstance(url_val.get(key), str):
                return urljoin(base_url, url_val[key])
    return ""


def _jsonld_salary(obj: dict) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    salary = obj.get("baseSalary")
    if not isinstance(salary, dict):
        return None, None, None, None
    currency = salary.get("currency") if isinstance(salary.get("currency"), str) else None
    unit = salary.get("unitText") if isinstance(salary.get("unitText"), str) else None
    period = unit.lower() if unit else None
    if period:
        if period.startswith("hour"):
            period = "hourly"
        elif period.startswith("day"):
            period = "daily"
        elif period.startswith("week"):
            period = "weekly"
        elif period.startswith("month"):
            period = "monthly"
        elif period.startswith("year") or period.startswith("annual"):
            period = "yearly"

    value = salary.get("value")
    vmin: Optional[float] = None
    vmax: Optional[float] = None

    def _num(raw: object) -> Optional[float]:
        try:
            return float(str(raw).replace(",", ""))
        except (ValueError, TypeError):
            return None

    if isinstance(value, dict):
        vmin = _num(value.get("minValue"))
        vmax = _num(value.get("maxValue"))
        if vmin is None and vmax is None:
            vmin = _num(value.get("value"))
    elif isinstance(value, list) and value:
        vmin = _num(value[0])
        if len(value) > 1:
            vmax = _num(value[1])
    else:
        vmin = _num(value)
    return vmin, vmax, currency, period


def extract_jsonld(content: str, base_url: str) -> List[RawOverseasJob]:
    """Extract JobPosting objects from all <script type=application/ld+json> blocks."""
    jobs: List[RawOverseasJob] = []
    if not content:
        return jobs
    try:
        tree = HTMLParser(content)
    except Exception:
        return jobs

    postings: List[dict] = []
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text()
        if not raw or not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        _collect_jsonld_job_postings(parsed, postings)

    for posting in postings:
        title = _collapse_ws(str(posting.get("title") or ""))
        if not title:
            continue

        org = posting.get("hiringOrganization")
        company: Optional[str] = None
        if isinstance(org, dict):
            company = _collapse_ws(str(org.get("name") or "")) or None
        elif isinstance(org, str):
            company = _collapse_ws(org) or None

        location = _jsonld_location(posting)
        country = normalize_destination(location or title)

        description = _html_to_text(str(posting.get("description") or "")) or title
        date_posted = posting.get("datePosted")
        posted_at = _parse_iso_datetime(date_posted if isinstance(date_posted, str) else None)
        salary_min, salary_max, currency, period = _jsonld_salary(posting)
        apply_url = _jsonld_url(posting.get("url"), base_url)

        jobs.append(
            RawOverseasJob(
                title=title,
                apply_url=apply_url,
                company=company,
                location=location or country,
                description=description,
                posted_at=posted_at,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_currency=currency,
                salary_period=period,
                strategy=STRATEGY_JSONLD,
                detail_url=apply_url or None,
            )
        )
    return jobs


# ── Strategy C: DOM card heuristic ──

def _ancestor_signature(node, level: int):
    """Return (tag, class) of the ancestor `level` hops up, or None."""
    cur = node
    for _ in range(level):
        if cur is None:
            return None
        cur = cur.parent
    if cur is None or cur.tag in ("body", "html", "[document]", "!doctype"):
        return None
    cls = (cur.attributes.get("class") or "").strip()
    return (cur.tag, cls)


def extract_dom_cards(html: str, base_url: str) -> List[RawOverseasJob]:
    """Heuristic extraction of job cards from repeating link clusters."""
    jobs: List[RawOverseasJob] = []
    if not html:
        return jobs
    try:
        tree = HTMLParser(html)
    except Exception:
        return jobs

    candidates: List[dict] = []
    for anchor in tree.css("a[href]"):
        href = (anchor.attributes.get("href") or "").strip()
        text = _collapse_ws(anchor.text() or "")
        if not href or not text:
            continue
        if href == "/" or href.startswith("#") or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        if not (8 < len(text) < 200):
            continue
        if _NAV_TEXT_RE.search(text):
            continue
        if _ANCHOR_RE.search(href) or _ANCHOR_RE.search(text):
            # record candidate + its ancestor (level, node) options
            options = []
            for level in (1, 2, 3):
                node = anchor
                for _ in range(level):
                    if node is None:
                        break
                    node = node.parent
                if node is None or node.tag in ("body", "html", "[document]", "!doctype"):
                    continue
                cls = (node.attributes.get("class") or "").strip()
                options.append((level, (node.tag, cls), node))
            candidates.append({"anchor": anchor, "href": href, "text": text, "options": options})

    if not candidates:
        return jobs

    # Count how many candidate anchors share each ancestor signature.
    sig_count: Dict[object, int] = {}
    for cand in candidates:
        for _level, sig, _node in cand["options"]:
            sig_count[sig] = sig_count.get(sig, 0) + 1

    # Assign each anchor to its best repeating ancestor: highest shared count,
    # tie-broken by nearest (smallest level).
    groups: Dict[object, List[dict]] = {}
    for cand in candidates:
        best_sig = None
        best_node = None
        best_count = 0
        best_level = 99
        for level, sig, node in cand["options"]:
            count = sig_count.get(sig, 0)
            if count < 3:
                continue
            if count > best_count or (count == best_count and level < best_level):
                best_count = count
                best_sig = sig
                best_node = node
                best_level = level
        if best_sig is not None:
            groups.setdefault(best_sig, []).append({
                "anchor": cand["anchor"],
                "href": cand["href"],
                "text": cand["text"],
                "node": best_node,
            })

    # Keep groups with 3..200 members; pick the largest.
    valid = {sig: members for sig, members in groups.items() if 3 <= len(members) <= 200}
    if not valid:
        return jobs

    chosen_sig = max(valid, key=lambda s: len(valid[s]))
    for member in valid[chosen_sig]:
        apply_url = urljoin(base_url, member["href"])
        node = member["node"]

        # Description = the card container's full text (always non-empty for SimHash).
        description = _collapse_ws(node.text() or "") if node is not None else ""
        if not description:
            description = member["text"]

        title = member["text"]
        if len(title) < 8:
            heading_texts: List[str] = []
            if node is not None:
                for sel in ("h2", "h3", "h4", "strong"):
                    for hnode in node.css(sel):
                        htext = _collapse_ws(hnode.text() or "")
                        if htext:
                            heading_texts.append(htext)
            if heading_texts:
                title = max(heading_texts, key=len)

        company: Optional[str] = None
        cm = _COMPANY_RE.search(description)
        if cm:
            company = _collapse_ws(cm.group(1))

        location = normalize_destination(description)
        salary_min, salary_max, currency = _parse_salary_from_text(description)
        posted_at = _parse_card_date(description)

        jobs.append(
            RawOverseasJob(
                title=title,
                apply_url=apply_url,
                company=company,
                location=location,
                description=description,
                posted_at=posted_at,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_currency=currency,
                salary_period=None,
                strategy=STRATEGY_DOM,
                detail_url=apply_url,
            )
        )
    return jobs


# ── Ladder ──

def extract_all(
    content: str,
    base_url: str,
    rss_capable: bool = False,
    content_type: str = "",
) -> Tuple[List[RawOverseasJob], Optional[str]]:
    """Run the extraction ladder; return (jobs, strategy_name_or_None).

    The first strategy yielding at least one job wins for this page.
    """
    if not content:
        return [], None

    ct = (content_type or "").lower()
    stripped = content.lstrip()[:200].lstrip().lower()
    looks_like_feed_content = ("xml" in ct) or stripped.startswith(("<rss", "<?xml", "<feed"))

    if rss_capable or looks_like_feed_content or discover_feed_urls(content, base_url):
        rss_jobs = extract_rss(content, base_url)
        if rss_jobs:
            return rss_jobs, STRATEGY_RSS
        if looks_like_feed_content:
            # Claimed to be a feed but parsed empty; don't DOM-scrape XML soup.
            return [], None

    jsonld_jobs = extract_jsonld(content, base_url)
    if jsonld_jobs:
        return jsonld_jobs, STRATEGY_JSONLD

    dom_jobs = extract_dom_cards(content, base_url)
    if dom_jobs:
        return dom_jobs, STRATEGY_DOM

    return [], None

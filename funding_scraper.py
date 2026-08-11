"""
Funding Scraper Module (Non-US, Non-India).
Scrapes newly fund-raised companies across global regions outside US & India:
  - Europe: Tech.eu, Sifted
  - LatAm: LatamList
  - Southeast Asia: e27
  - MENA: Wamda
  - Africa: Disrupt Africa

Primary Tool: feedparser (RSS/Atom feeds)
Fallback Tool: BeautifulSoup + requests (HTML scraping when RSS feed unavailable)
"""
import re
import time
import datetime
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import feedparser
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from filter import KEYWORDS_INCLUDE

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_thread_local = threading.local()
FUNDING_SIGNAL = re.compile(
    r"\b(?:raises?|raised|raising|secures?|secured|closes?|closed|bags?|lands?|"
    r"gets?|obtains?|collects?|receives?|attracts?)\b"
    r"(?:\W+\w+){0,6}?\W+(?:funding|funds|investment|financing|capital|"
    r"pre-seed|seed|series\s+[a-z]|round)\b"
    r"|\b(?:pre-seed|seed|series\s+[a-z])\s+(?:round|funding)\b",
    re.IGNORECASE,
)


def _http_session() -> requests.Session:
    """Use a per-thread retrying session for independent news sources."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(("GET",)),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=2, pool_maxsize=2)
        session = requests.Session()
        session.headers.update(HEADERS)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _thread_local.session = session
    return session


def _get(url: str) -> requests.Response:
    response = _http_session().get(url, timeout=15)
    response.raise_for_status()
    return response

# ------------------------------------------------------------------ #
#  Location Exclusion & Target Region Constants
# ------------------------------------------------------------------ #
EXCLUDED_LOCATIONS = {
    "united states", "usa", " u.s.", " u.s ", "us-based", "california", "san francisco",
    "new york", "texas", "austin", "seattle", "boston", "silicon valley", "los angeles",
    "chicago", "miami", "denver", "atlanta",
    "india", "indian", "bangalore", "bengaluru", "mumbai", "delhi", "gurgaon", "gurugram",
    "hyderabad", "pune", "noida", "chennai"
}

ALLOWED_REGIONS = {
    "europe", "uk", "united kingdom", "england", "london", "germany", "berlin",
    "france", "paris", "netherlands", "amsterdam", "sweden", "stockholm", "spain",
    "barcelona", "madrid", "portugal", "lisbon", "italy", "poland", "estonia", "finland",
    "norway", "denmark", "switzerland", "austria", "ireland", "dublin",
    "latam", "latin america", "colombia", "mexico", "brazil", "chile", "argentina", "peru",
    "southeast asia", "singapore", "indonesia", "jakarta", "vietnam", "malaysia", "thailand", "philippines",
    "mena", "middle east", "uae", "dubai", "abu dhabi", "saudi arabia", "riyadh", "egypt", "cairo", "qatar", "jordan", "turkey", "istanbul",
    "africa", "nigeria", "lagos", "kenya", "nairobi", "south africa", "cape town", "johannesburg", "ghana", "accra",
    "canada", "toronto", "vancouver", "montreal", "australia", "sydney", "melbourne", "new zealand"
}

# RSS / HTML Sources Configuration
SOURCES = [
    {
        "name": "Tech.eu",
        "region": "Europe",
        "type": "rss",
        "url": "https://tech.eu/feed/",
    },
    {
        "name": "Sifted",
        "region": "Europe",
        "type": "rss",
        "url": "https://sifted.eu/feed",
    },
    {
        "name": "LatamList",
        "region": "LatAm",
        "type": "rss",
        "url": "https://latamlist.com/feed/",
    },
    {
        "name": "e27",
        "region": "Southeast Asia",
        "type": "rss",
        "url": "https://e27.co/feed/",
    },
    {
        "name": "Disrupt Africa",
        "region": "Africa",
        "type": "rss",
        "url": "https://disrupt-africa.com/feed/",
    },
    {
        "name": "Wamda",
        "region": "MENA",
        "type": "html_fallback",
        "url": "https://www.wamda.com/news",
    },
]


# ------------------------------------------------------------------ #
#  Extractors & Filters
# ------------------------------------------------------------------ #
def is_excluded_location(text: str) -> bool:
    """Check if the text refers to US or India without allowed region context."""
    t = text.lower()
    for exc in EXCLUDED_LOCATIONS:
        if exc in t:
            # Check if there is an explicit allowed region mentioned alongside
            if any(allowed in t for allowed in ALLOWED_REGIONS):
                continue
            return True
    return False


def is_funding_announcement(text: str) -> bool:
    """Exclude general news so the digest contains funding events only."""
    return bool(FUNDING_SIGNAL.search(text))


def extract_funding_amount(text: str) -> str:
    """Extract funding amount (e.g. $60M, €5.5 million, £10 million)."""
    pattern = r"(\$[\d\.]+\s*(?:million|m|billion|b)?|€[\d\.]+\s*(?:million|m|billion|b)?|£[\d\.]+\s*(?:million|m|billion|b)?|\b\d+\.?\d*\s*million\s*(?:dollars|euros|pounds|USD|EUR|GBP)?|\b\d+\.?\d*\s*m\b)"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else "N/A"


def extract_round(text: str) -> str:
    """Extract funding stage / round (Pre-Seed, Seed, Series A, Series B, etc.)."""
    pattern = r"\b(pre-seed|seed|series\s+[a-z]|growth|bridge|grant)\b"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).title() if m else "Funding Round"


def extract_company_name(title: str) -> str:
    """Cleanly infer company name from article title."""
    # Common patterns: "Company raises...", "Company secures...", "How Company enables..."
    m = re.search(
        r"^([A-Z0-9\.\-\s]+?)\s+(?:raises|secures|bags|closes|gets|obtains|collects|receives|attracts)",
        title,
        re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip()
        name = re.sub(
            r"^(?:[A-Za-z]+\s+){0,2}(?:startup|scaleup|biotech|fintech|company)\s+",
            "",
            name,
            flags=re.IGNORECASE,
        )
        if len(name) > 2 and len(name) < 40 and not name.lower().startswith(("how", "why", "the")):
            return name

    # Fallback: first 3-4 words of title
    words = title.split()
    return " ".join(words[:3]) if words else title


def match_keywords(text: str) -> List[str]:
    """Check matching role/tech keywords from project's filter configuration."""
    t = text.lower()
    matched = []
    for kw in KEYWORDS_INCLUDE:
        if kw in t:
            matched.append(kw.title())
    return list(set(matched))


def is_fresh(entry_date_struct: Optional[time.struct_time], max_hours: int = 48) -> bool:
    """Check if entry was published within the last max_hours."""
    if not entry_date_struct:
        return True  # If no date is available, keep entry for review

    published_dt = datetime.datetime.fromtimestamp(time.mktime(entry_date_struct), tz=datetime.timezone.utc)
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    diff = now_dt - published_dt
    return diff.total_seconds() <= (max_hours * 3600)


# ------------------------------------------------------------------ #
#  Scraping Routines
# ------------------------------------------------------------------ #
def scrape_rss_feed(source: dict) -> List[Dict]:
    """Scrape RSS feed using feedparser with HTTP requests wrapper."""
    logger.info(f"Scraping RSS feed: {source['name']} ({source['url']})")
    results = []
    try:
        r = _get(source["url"])
        feed = feedparser.parse(r.text)

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = BeautifulSoup(entry.get("summary") or entry.get("description") or "", "html.parser").get_text(strip=True)
            link = entry.get("link", "").strip()

            combined_text = f"{title} {summary}"

            # The old implementation included every recent article from a
            # funding publication, including policy and opinion pieces.
            if not is_funding_announcement(combined_text):
                logger.debug(f"  [EXCLUDE Not funding] {title}")
                continue

            # 1. Location filter: Exclude US & India
            if is_excluded_location(combined_text):
                logger.debug(f"  [EXCLUDE US/India] {title}")
                continue

            # 2. Freshness filter
            date_struct = entry.get("published_parsed") or entry.get("updated_parsed")
            if not is_fresh(date_struct, max_hours=48):
                logger.debug(f"  [EXCLUDE Old] {title}")
                continue

            # 3. Extract funding details
            company = extract_company_name(title)
            amount = extract_funding_amount(combined_text)
            round_type = extract_round(combined_text)
            matched_kws = match_keywords(combined_text)

            results.append({
                "company": company,
                "title": title,
                "region": source["region"],
                "source": source["name"],
                "amount": amount,
                "round": round_type,
                "summary": summary[:280] + ("..." if len(summary) > 280 else ""),
                "url": link,
                "matched_keywords": matched_kws,
                "published": entry.get("published") or entry.get("updated") or "Recent",
            })

    except Exception as e:
        logger.warning(f"Error parsing RSS for {source['name']}: {e}")

    logger.info(f"  -> Found {len(results)} valid funding entries from {source['name']}")
    return results


def scrape_html_fallback(source: dict) -> List[Dict]:
    """Scrape HTML using BeautifulSoup when RSS feed is unavailable."""
    logger.info(f"Scraping HTML fallback: {source['name']} ({source['url']})")
    results = []
    try:
        r = _get(source["url"])
        soup = BeautifulSoup(r.text, "html.parser")

        # Find article links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)

            if len(title) < 15 or len(href) < 5:
                continue

            combined_text = title

            # Check if this article looks like a funding announcement
            if not is_funding_announcement(title):
                continue

            if is_excluded_location(combined_text):
                continue

            href = urljoin(source["url"], href)

            company = extract_company_name(title)
            amount = extract_funding_amount(combined_text)
            round_type = extract_round(combined_text)
            matched_kws = match_keywords(combined_text)

            results.append({
                "company": company,
                "title": title,
                "region": source["region"],
                "source": source["name"],
                "amount": amount,
                "round": round_type,
                "summary": title,
                "url": href,
                "matched_keywords": matched_kws,
                "published": "Recent",
            })

    except Exception as e:
        logger.warning(f"Error scraping HTML for {source['name']}: {e}")

    # Deduplicate HTML results by URL
    seen_urls = set()
    unique_results = []
    for r in results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique_results.append(r)

    logger.info(f"  -> Found {len(unique_results)} valid funding entries from {source['name']}")
    return unique_results


def fetch_all_funding_deals() -> List[Dict]:
    """Fetch independent funding sources concurrently and retain source order."""
    def fetch_source(source: dict) -> List[Dict]:
        if source["type"] == "rss":
            return scrape_rss_feed(source)
        return scrape_html_fallback(source)

    source_results: dict[int, List[Dict]] = {}
    with ThreadPoolExecutor(max_workers=min(6, len(SOURCES)), thread_name_prefix="funding-source") as executor:
        futures = {
            executor.submit(fetch_source, source): index
            for index, source in enumerate(SOURCES)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                source_results[index] = future.result()
            except Exception as exc:  # Individual sources must not block a digest.
                logger.warning("Unexpected funding source failure: %s", exc)
                source_results[index] = []

    all_deals = [deal for index in range(len(SOURCES)) for deal in source_results[index]]

    # Deduplicate deals by URL or Title across sources
    seen_keys = set()
    deduped = []
    for d in all_deals:
        key = d["url"] or d["title"].lower()
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(d)

    logger.info(f"Total unique funding deals fetched (Non-US, Non-India): {len(deduped)}")
    return deduped

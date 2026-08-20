"""Public, ToS-compliant, free job board APIs and feed integrations.

Fetches remote AI & Machine Learning postings from:
1. RemoteOK API (https://remoteok.com/api)
2. Remotive API (https://remotive.com/api/remote-jobs)
3. Arbeitnow API (https://arbeitnow.com/api/job-board-api)
4. Himalayas API (https://himalayas.app/jobs/api)
5. Hacker News 'Who is Hiring' (HN Algolia Search API)

Terms & Compliance:
- Direct job links are preserved (no intermediate redirects).
- Source attribution is maintained in job records.
- Standard polite User-Agent and timeouts are enforced.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; AIJobRadarBot/2.0; +https://github.com/AlirezaNezami96/Visa-Sponsorship-Daily-Jobs)"
DEFAULT_TIMEOUT = 15


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


# ------------------------------------------------------------------ #
#  1. RemoteOK API
# ------------------------------------------------------------------ #
def fetch_remoteok(tags: tuple = ("ai", "machine-learning", "intern", "junior")) -> List[dict]:
    """Fetch remote AI jobs from RemoteOK public API.
    
    Compliance: RemoteOK requires direct links and source credit.
    """
    url = "https://remoteok.com/api"
    jobs = []
    seen_ids = set()

    for tag in tags:
        try:
            r = _session().get(f"{url}?tag={tag}", timeout=DEFAULT_TIMEOUT)
            if r.status_code != 200:
                logger.warning("RemoteOK API returned HTTP %d for tag %s", r.status_code, tag)
                continue
            data = r.json()
            # First item in RemoteOK response is often metadata / legal notice
            for item in data:
                if not isinstance(item, dict) or "position" not in item:
                    continue
                job_id = str(item.get("id", item.get("slug", "")))
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = item.get("position", "").strip()
                company = item.get("company", "").strip()
                apply_url = item.get("apply_url") or item.get("url") or f"https://remoteok.com/remote-jobs/{job_id}"
                location = item.get("location") or "Remote (Worldwide)"
                raw_desc = item.get("description", "")
                snippet = BeautifulSoup(raw_desc, "html.parser").get_text(separator=" ", strip=True)[:300] if raw_desc else ""

                sal_min = item.get("salary_min")
                sal_max = item.get("salary_max")
                salary = f"${sal_min:,} - ${sal_max:,}" if sal_min and sal_max else None

                jobs.append({
                    "title": title,
                    "company": company,
                    "url": apply_url,
                    "location": location,
                    "department": "Engineering",
                    "salary": salary,
                    "date_posted": item.get("date"),
                    "remote": True,
                    "source": "RemoteOK",
                    "visa_sponsorship": None,
                    "snippet": snippet,
                })
        except Exception as exc:
            logger.warning("RemoteOK fetch error for tag %s: %s", tag, exc)
        time.sleep(0.3)

    return jobs


# ------------------------------------------------------------------ #
#  2. Remotive API
# ------------------------------------------------------------------ #
def fetch_remotive(queries: tuple = ("AI", "machine learning", "intern")) -> List[dict]:
    """Fetch remote AI jobs from Remotive API.
    
    Compliance: Remotive requires crediting Remotive and direct apply links.
    """
    base_url = "https://remotive.com/api/remote-jobs"
    jobs = []
    seen_ids = set()

    for q in queries:
        try:
            r = _session().get(f"{base_url}?category=software-development&search={q}", timeout=DEFAULT_TIMEOUT)
            if r.status_code != 200:
                logger.warning("Remotive API returned HTTP %d for query %s", r.status_code, q)
                continue
            data = r.json()
            for item in data.get("jobs", []):
                job_id = str(item.get("id", ""))
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = item.get("title", "").strip()
                company = item.get("company_name", "").strip()
                url = item.get("url", "").strip()
                loc = item.get("candidate_required_location") or "Remote (Worldwide)"
                raw_desc = item.get("description", "")
                snippet = BeautifulSoup(raw_desc, "html.parser").get_text(separator=" ", strip=True)[:300] if raw_desc else ""

                jobs.append({
                    "title": title,
                    "company": company,
                    "url": url,
                    "location": loc,
                    "department": item.get("category", "Software Development"),
                    "salary": item.get("salary"),
                    "date_posted": item.get("publication_date"),
                    "remote": True,
                    "source": "Remotive",
                    "visa_sponsorship": None,
                    "snippet": snippet,
                })
        except Exception as exc:
            logger.warning("Remotive fetch error for query %s: %s", q, exc)
        time.sleep(0.3)

    return jobs


# ------------------------------------------------------------------ #
#  3. Arbeitnow API
# ------------------------------------------------------------------ #
def fetch_arbeitnow() -> List[dict]:
    """Fetch jobs from Arbeitnow public job board API.
    
    Supports native visa_sponsorship and remote flags.
    """
    url = "https://arbeitnow.com/api/job-board-api"
    jobs = []

    try:
        r = _session().get(url, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            for item in data.get("data", []):
                title = item.get("title", "").strip()
                company = item.get("company_name", "").strip()
                url_link = item.get("url", "").strip()
                is_remote = bool(item.get("remote"))
                loc = item.get("location", "")
                if is_remote and not loc:
                    loc = "Remote"
                elif is_remote and "remote" not in loc.lower():
                    loc = f"Remote ({loc})"

                raw_desc = item.get("description", "")
                snippet = BeautifulSoup(raw_desc, "html.parser").get_text(separator=" ", strip=True)[:300] if raw_desc else ""

                # Arbeitnow flags
                tags = [t.lower() for t in item.get("tags", [])]
                visa_flag = "visa sponsorship" in tags or item.get("visa_sponsorship") is True

                jobs.append({
                    "title": title,
                    "company": company,
                    "url": url_link,
                    "location": loc,
                    "department": "Engineering",
                    "salary": None,
                    "date_posted": str(item.get("created_at")),
                    "remote": is_remote,
                    "source": "Arbeitnow",
                    "visa_sponsorship": visa_flag,
                    "snippet": snippet,
                })
    except Exception as exc:
        logger.warning("Arbeitnow fetch error: %s", exc)

    return jobs


# ------------------------------------------------------------------ #
#  4. Himalayas API
# ------------------------------------------------------------------ #
def fetch_himalayas() -> List[dict]:
    """Fetch remote AI/Engineering jobs from Himalayas public API."""
    url = "https://himalayas.app/jobs/api"
    jobs = []

    try:
        r = _session().get(url, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            for item in data.get("jobs", []):
                title = item.get("title", "").strip()
                company = item.get("companyName", "").strip()
                apply_url = item.get("applicationLink") or f"https://himalayas.app/companies/{item.get('companySlug')}/jobs/{item.get('guid')}"
                
                loc_restrictions = item.get("locationRestrictions", [])
                loc = ", ".join(loc_restrictions) if loc_restrictions else "Remote (Worldwide)"

                min_sal = item.get("minSalary")
                max_sal = item.get("maxSalary")
                curr = item.get("currency", "$")
                salary = f"{curr}{min_sal:,} - {curr}{max_sal:,}" if min_sal and max_sal else None

                raw_desc = item.get("description", "") or item.get("excerpt", "")
                snippet = BeautifulSoup(raw_desc, "html.parser").get_text(separator=" ", strip=True)[:300] if raw_desc else ""

                jobs.append({
                    "title": title,
                    "company": company,
                    "url": apply_url,
                    "location": loc,
                    "department": ", ".join(item.get("categories", [])),
                    "salary": salary,
                    "date_posted": str(item.get("pubDate")),
                    "remote": True,
                    "source": "Himalayas",
                    "visa_sponsorship": None,
                    "snippet": snippet,
                })
    except Exception as exc:
        logger.warning("Himalayas fetch error: %s", exc)

    return jobs


# ------------------------------------------------------------------ #
#  5. Hacker News 'Who is Hiring'
# ------------------------------------------------------------------ #
def fetch_hn_who_is_hiring() -> List[dict]:
    """Fetch latest Ask HN: Who is hiring? thread and parse remote AI postings via Algolia API."""
    jobs = []
    try:
        # Step 1: Find the latest "Ask HN: Who is hiring?" story
        story_url = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&query=Ask%20HN:%20Who%20is%20hiring&hitsPerPage=1"
        r_story = _session().get(story_url, timeout=DEFAULT_TIMEOUT)
        if r_story.status_code != 200:
            return []
        hits = r_story.json().get("hits", [])
        if not hits:
            return []

        story_id = hits[0]["objectID"]
        story_created = hits[0].get("created_at")

        # Step 2: Fetch comments on this story
        comments_url = f"https://hn.algolia.com/api/v1/search_by_date?tags=comment,story_{story_id}&hitsPerPage=150"
        r_comments = _session().get(comments_url, timeout=DEFAULT_TIMEOUT)
        if r_comments.status_code != 200:
            return []
        comments = r_comments.json().get("hits", [])

        # Step 3: Parse comments for Remote AI / ML roles
        for c in comments:
            raw_html = c.get("comment_text", "")
            if not raw_html:
                continue

            text = BeautifulSoup(raw_html, "html.parser").get_text(separator="\n", strip=True)
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if not lines:
                continue

            header_line = lines[0]
            # Must mention REMOTE in header or text
            if "remote" not in text.lower():
                continue

            # Parse standard HN hiring format: Company | Role/Title | Location | Salary
            parts = [p.strip() for p in header_line.split("|")]
            company = parts[0] if parts else "HN Startup"
            title_candidate = parts[1] if len(parts) > 1 else header_line
            loc_candidate = parts[2] if len(parts) > 2 else "Remote"

            # Look for apply URL or email in text
            urls = re.findall(r'https?://[^\s<>"\']+', raw_html)
            apply_url = urls[0] if urls else f"https://news.ycombinator.com/item?id={c.get('objectID')}"

            # Visa sponsorship check in HN text
            visa_flag = bool(re.search(r"\b(visa|sponsor|sponsorship|relocation)\b", text, re.IGNORECASE))

            jobs.append({
                "title": title_candidate[:120],
                "company": company[:60],
                "url": apply_url,
                "location": loc_candidate[:80],
                "department": "Engineering / AI",
                "salary": None,
                "date_posted": c.get("created_at", story_created),
                "remote": True,
                "source": "HackerNews",
                "visa_sponsorship": visa_flag,
                "snippet": text[:350],
            })
    except Exception as exc:
        logger.warning("HN Who is Hiring fetch error: %s", exc)

    return jobs


# ------------------------------------------------------------------ #
#  Master Public APIs Dispatcher
# ------------------------------------------------------------------ #
def fetch_all_public_apis(config_apis: Optional[Dict[str, bool]] = None) -> List[dict]:
    """Fetch all enabled public job APIs concurrently and return normalized jobs."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    api_flags = config_apis or {
        "remoteok": True,
        "remotive": True,
        "arbeitnow": True,
        "himalayas": True,
        "hn_hiring": True,
    }

    tasks = []
    if api_flags.get("remoteok", True):
        tasks.append(("RemoteOK", fetch_remoteok))
    if api_flags.get("remotive", True):
        tasks.append(("Remotive", fetch_remotive))
    if api_flags.get("arbeitnow", True):
        tasks.append(("Arbeitnow", fetch_arbeitnow))
    if api_flags.get("himalayas", True):
        tasks.append(("Himalayas", fetch_himalayas))
    if api_flags.get("hn_hiring", True):
        tasks.append(("HackerNews", fetch_hn_who_is_hiring))

    all_jobs = []
    logger.info("Fetching %d public job APIs concurrently...", len(tasks))

    with ThreadPoolExecutor(max_workers=len(tasks) or 1) as executor:
        futures = {executor.submit(fn): name for name, fn in tasks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                logger.info("Public API [%s] returned %d raw listings", name, len(result))
                all_jobs.extend(result)
            except Exception as exc:
                logger.warning("Public API [%s] failed: %s", name, exc)

    return all_jobs

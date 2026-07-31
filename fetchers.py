"""Fetchers for each ATS type with public JSON APIs.
No HTML scraping needed — these are clean JSON endpoints.
"""
import requests
import time


SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; JobScraper/1.0)"})


def _get(url, **kwargs):
    """Wraps requests.get with timeout and error handling."""
    kwargs.setdefault("timeout", 20)
    r = SESSION.get(url, **kwargs)
    r.raise_for_status()
    return r


def _post(url, **kwargs):
    """Wraps requests.post with timeout and error handling."""
    kwargs.setdefault("timeout", 20)
    r = SESSION.post(url, **kwargs)
    r.raise_for_status()
    return r


def fetch_greenhouse(slug):
    """Fetch jobs from Greenhouse ATS.
    API: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    r = _get(url)
    jobs = r.json().get("jobs", [])
    result = []
    for j in jobs:
        location = j.get("location", {})
        if isinstance(location, dict):
            loc_str = location.get("name", "")
        else:
            loc_str = str(location)
        result.append({
            "title": j["title"],
            "url": f"https://boards.greenhouse.io/{slug}/jobs/{j['id']}",
            "location": loc_str,
            "department": j.get("departments", [{}])[0].get("name", "") if j.get("departments") else "",
        })
    return result


def fetch_lever(slug):
    """Fetch jobs from Lever ATS.
    API: https://api.lever.co/v0/postings/{slug}?mode=json
    """
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = _get(url)
    result = []
    for p in r.json():
        categories = p.get("categories", {}) or {}
        result.append({
            "title": p["text"],
            "url": p["hostedUrl"],
            "location": categories.get("location", ""),
            "department": categories.get("team", ""),
        })
    return result


def fetch_ashby(slug):
    """Fetch jobs from Ashby ATS.
    API: https://api.ashbyhq.com/posting-api/job-board/{slug}
    Requires POST with empty JSON body.
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = _post(url, json={})
    data = r.json()
    result = []
    for p in data.get("jobPostings", []):
        location_info = p.get("location", {}) or {}
        loc_name = location_info.get("name", "") if isinstance(location_info, dict) else str(location_info)
        result.append({
            "title": p.get("title", ""),
            "url": p.get("externalUrl", "") or p.get("hostedUrl", ""),
            "location": loc_name,
            "department": (p.get("department", {}) or {}).get("name", ""),
        })
    return result


def fetch_smartrecruiters(slug):
    """Fetch jobs from SmartRecruiters ATS.
    API: https://api.smartrecruiters.com/v1/companies/{slug}/postings
    Paginated — fetches all pages.
    """
    base_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    all_jobs = []
    offset = 0
    limit = 100

    while True:
        r = _get(base_url, params={"offset": offset, "limit": limit})
        data = r.json()
        total = data.get("totalFound", 0)
        content = data.get("content", []) or []
        for c in content:
            location = c.get("location", {}) or {}
            all_jobs.append({
                "title": c.get("title", ""),
                "url": c.get("applyUrl", ""),
                "location": location.get("city", ""),
                "department": (c.get("department", {}) or {}).get("label", ""),
            })
        if len(all_jobs) >= total or not content:
            break
        offset += limit
        time.sleep(0.3)  # Be gentle

    return all_jobs


def fetch_personio(slug):
    """Fetch jobs from Personio ATS.
    API: https://{slug}.jobs.personio.de/xml (XML format)
    """
    url = f"https://{slug}.jobs.personio.de/xml"
    r = _get(url)
    # Parse XML
    import xml.etree.ElementTree as ET
    root = ET.fromstring(r.text)
    result = []
    for job in root.findall(".//position"):
        result.append({
            "title": job.findtext("name", ""),
            "url": job.findtext("url", ""),
            "location": job.findtext("office", ""),
            "department": job.findtext("department", ""),
        })
    return result


# Mapping of ATS type to fetcher function
FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "personio": fetch_personio,
    # workday and custom are handled by fetcher_custom.py
}

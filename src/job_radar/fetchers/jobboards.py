"""AI-Agentic and Fast Cached Fetcher for Job Boards (Indeed and future boards)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, parse_qsl, quote_plus, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_CONFIG_PATH = "jobboard_config.json"
DEFAULT_CACHE_PATH = "state/jobboard_cache.json"


@dataclass
class JobListing:
    title: str
    url: str
    company: str
    location: str
    department: str = ""
    salary: Optional[str] = None
    date_posted: Optional[str] = None
    remote: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "company": self.company,
            "location": self.location,
            "department": self.department,
            "salary": self.salary,
            "date_posted": self.date_posted,
            "remote": self.remote,
        }


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    candidates = [
        config_path,
        os.path.join("data", os.path.basename(config_path)),
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Failed to parse config %s: %s. Using defaults.", c, exc)

    return {
        "active_countries": ["USA", "UK", "Canada", "Germany", "Netherlands", "Ireland"],
        "search_queries": [
            "Junior AI Engineer",
            "Junior Machine Learning Engineer",
            "Entry Level AI Engineer",
            "Graduate Machine Learning",
        ],
        "max_results_per_query": 15,
        "request_delay_seconds": 2.0,
        "cache_file": DEFAULT_CACHE_PATH,
        "country_domains": {
            "usa": "www.indeed.com",
            "united states": "www.indeed.com",
            "uk": "uk.indeed.com",
            "united kingdom": "uk.indeed.com",
            "canada": "ca.indeed.com",
            "germany": "de.indeed.com",
            "netherlands": "nl.indeed.com",
            "ireland": "ie.indeed.com",
            "australia": "au.indeed.com",
            "france": "fr.indeed.com",
            "sweden": "se.indeed.com",
            "switzerland": "ch.indeed.com",
        },
    }


def load_cache(cache_path: str = DEFAULT_CACHE_PATH) -> dict:
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.debug("Failed to read cache %s: %s", cache_path, exc)
    return {}


def save_cache(cache: dict, cache_path: str = DEFAULT_CACHE_PATH) -> None:
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as exc:
        logger.warning("Failed to save cache to %s: %s", cache_path, exc)


def get_indeed_domain(country: str, config: Optional[dict] = None) -> str:
    cfg = config or load_config()
    domains = cfg.get("country_domains", {})
    normalized_key = country.strip().lower()
    if normalized_key in domains:
        return domains[normalized_key]

    clean_key = re.sub(r"[^a-z0-9]", "", normalized_key)
    for k, v in domains.items():
        if re.sub(r"[^a-z0-9]", "", k) == clean_key:
            return v

    logger.info("Unmapped country '%s'; defaulting to www.indeed.com", country)
    return "www.indeed.com"


def build_indeed_url(
    domain: str,
    query: str,
    location: str = "",
    start: int = 0,
) -> str:
    params = {"q": query}
    if location:
        params["l"] = location
    if start > 0:
        params["start"] = str(start)

    query_str = urlencode(params, quote_via=quote_plus)
    return f"https://{domain}/jobs?{query_str}"


def canonicalize_indeed_url(url: str, base_domain: str = "www.indeed.com") -> str:
    if not url:
        return ""

    full_url = urljoin(f"https://{base_domain}", url.strip())
    parsed = urlsplit(full_url)
    query_params = parse_qs(parsed.query)

    jk = query_params.get("jk", [None])[0]
    if not jk and "/rc/clk" in parsed.path:
        jk = query_params.get("jk", [None])[0]

    domain = parsed.netloc.lower() or base_domain

    if jk:
        return f"https://{domain}/viewjob?jk={jk}"

    kept_query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if not k.lower().startswith((
                "utm_", "ref", "source", "tk", "from", "vjs", "xkcb",
                "advn", "iacode", "mobidx", "vjsp", "ts"
            ))
        )
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower() or "https", domain, path, kept_query, ""))


def extract_jobs_from_indeed_html(html: str, base_domain: str = "www.indeed.com") -> List[JobListing]:
    soup = BeautifulSoup(html, "html.parser")
    listings: List[JobListing] = []
    seen_urls: set[str] = set()

    for script in soup.find_all("script", type="application/ld+json"):
        payload = script.string or script.get_text()
        if not payload:
            continue
        try:
            data = json.loads(payload)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("@type") in ("JobPosting", "ItemList"):
                    if item.get("@type") == "ItemList":
                        item_elements = item.get("itemListElement", [])
                    else:
                        item_elements = [item]

                    for elem in item_elements:
                        job_data = elem.get("item", elem) if isinstance(elem, dict) else {}
                        title = job_data.get("title", "")
                        raw_url = job_data.get("url", "")
                        company_info = job_data.get("hiringOrganization", {})
                        company = company_info.get("name", "") if isinstance(company_info, dict) else str(company_info)
                        loc_info = job_data.get("jobLocation", {})
                        if isinstance(loc_info, dict):
                            addr = loc_info.get("address", {})
                            location = (
                                addr.get("addressLocality")
                                or addr.get("addressRegion")
                                or addr.get("addressCountry")
                                or ""
                            ) if isinstance(addr, dict) else ""
                        else:
                            location = str(loc_info)

                        if title and raw_url:
                            canon_url = canonicalize_indeed_url(raw_url, base_domain)
                            if canon_url not in seen_urls:
                                seen_urls.add(canon_url)
                                is_remote = (
                                    "remote" in title.lower()
                                    or "remote" in location.lower()
                                    or job_data.get("jobLocationType") == "TELECOMMUTE"
                                )
                                listings.append(JobListing(
                                    title=title.strip(),
                                    url=canon_url,
                                    company=company.strip() or "Indeed",
                                    location=location.strip() or "Remote / Unspecified",
                                    salary=job_data.get("baseSalary", {}).get("value") if isinstance(job_data.get("baseSalary"), dict) else None,
                                    date_posted=job_data.get("datePosted"),
                                    remote=is_remote,
                                ))
        except Exception as exc:
            logger.debug("JSON-LD parse error: %s", exc)

    card_selector = (
        "div.job_seen_beacon, div.cardOutline, div[data-jk], li.css-5lfssm, "
        "div.result, div.slider_item, div.jobsearch-SerpJobCard"
    )
    cards = soup.select(card_selector)

    for card in cards:
        jk = card.get("data-jk")
        link = card.select_one("a.jcs-JobTitle, a[data-jk], h2.jobTitle a, a[id^='job_'], a[href*='viewjob'], a[href*='rc/clk']")
        raw_url = link.get("href", "") if link else ""
        if not jk and link:
            jk = link.get("data-jk") or link.get("data-mobtk")

        if not raw_url and jk:
            raw_url = f"/viewjob?jk={jk}"

        if not raw_url:
            continue

        canon_url = canonicalize_indeed_url(raw_url, base_domain)
        if not canon_url or canon_url in seen_urls:
            continue

        title = ""
        if link:
            title = link.get_text(" ", strip=True)
        if not title:
            title_elem = card.select_one("h2.jobTitle, .jobTitle, [class*='title']")
            title = title_elem.get_text(" ", strip=True) if title_elem else ""

        company_elem = card.select_one(
            "[data-testid='company-name'], span.css-63koeb, span.companyName, .company, span[class*='company']"
        )
        company = company_elem.get_text(" ", strip=True) if company_elem else "Indeed"

        loc_elem = card.select_one(
            "[data-testid='text-location'], div.css-1p0sjhy, div.companyLocation, .location, [class*='location']"
        )
        location = loc_elem.get_text(" ", strip=True) if loc_elem else ""

        salary_elem = card.select_one(
            "[data-testid='attribute_snippet_testid'], .salary-snippet-container, .metadata.salary-snippet-container, .salaryText, [class*='salary']"
        )
        salary = salary_elem.get_text(" ", strip=True) if salary_elem else None

        date_elem = card.select_one("span.date, [data-testid='myJobsStateDate'], [class*='date']")
        date_posted = date_elem.get_text(" ", strip=True) if date_elem else None

        card_text = card.get_text(" ", strip=True).lower()
        is_remote = "remote" in card_text or "hybrid" in card_text or "work from home" in card_text

        if title and canon_url:
            seen_urls.add(canon_url)
            listings.append(JobListing(
                title=title.strip(),
                url=canon_url,
                company=company.strip() or "Indeed",
                location=location.strip() or "Remote / Unspecified",
                salary=salary,
                date_posted=date_posted,
                remote=is_remote,
            ))

    return listings


async def _run_browser_use_agent(
    search_url: str,
    country: str,
    query: str,
    max_results: int = 15,
) -> List[JobListing]:
    try:
        from browser_use import Agent  # type: ignore
    except ImportError:
        logger.info("browser-use package not installed; bypassing agentic LLM path")
        return []

    llm = None
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if anthropic_key:
        try:
            from langchain_anthropic import ChatAnthropic  # type: ignore
            model_name = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
            llm = ChatAnthropic(model=model_name, anthropic_api_key=anthropic_key, temperature=0.0)
        except Exception as exc:
            logger.warning("Failed to initialize ChatAnthropic: %s", exc)

    if not llm and openai_key:
        try:
            from langchain_openai import ChatOpenAI  # type: ignore
            model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            llm = ChatOpenAI(model=model_name, openai_api_key=openai_key, temperature=0.0)
        except Exception as exc:
            logger.warning("Failed to initialize ChatOpenAI: %s", exc)

    if not llm and gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore
            model_name = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
            llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=gemini_key, temperature=0.0)
        except Exception as exc:
            logger.warning("Failed to initialize ChatGoogleGenerativeAI: %s", exc)

    if not llm:
        return []

    task_prompt = (
        f"Go to {search_url}. Look for job search postings for '{query}' in {country}. "
        f"Extract up to {max_results} distinct job postings shown on the page. "
        "For each job posting, collect:\n"
        "- title: exact job title\n"
        "- company: hiring company name\n"
        "- location: job location or Remote\n"
        "- url: job link or apply URL\n"
        "- salary: salary snippet if shown, else null\n"
        "- date_posted: date or 'X days ago' if shown, else null\n"
        "- remote: boolean true if remote, else false\n\n"
        "Return the output as a valid JSON array of objects with keys: title, company, location, url, salary, date_posted, remote."
    )

    try:
        agent = Agent(task=task_prompt, llm=llm)
        agent_result = await agent.run()
        text_output = str(agent_result)

        json_match = re.search(r"\[\s*\{.*\}\s*\]", text_output, re.DOTALL)
        if json_match:
            raw_items = json.loads(json_match.group(0))
            listings = []
            base_domain = get_indeed_domain(country)
            for item in raw_items:
                if isinstance(item, dict) and item.get("title") and item.get("url"):
                    canon_url = canonicalize_indeed_url(item["url"], base_domain)
                    listings.append(JobListing(
                        title=str(item["title"]).strip(),
                        url=canon_url,
                        company=str(item.get("company", "Indeed")).strip(),
                        location=str(item.get("location", "Remote")).strip(),
                        salary=item.get("salary"),
                        date_posted=item.get("date_posted"),
                        remote=bool(item.get("remote")),
                    ))
            if listings:
                return listings
    except Exception as exc:
        logger.warning("browser-use Agent execution failed: %s", exc)

    return []


async def _fetch_indeed_page_playwright(
    search_url: str,
    base_domain: str,
    timeout_ms: int = 25000,
) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright is not installed.")
        return ""

    proxy_server = os.environ.get("PROXY_URL") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    proxy_config = {"server": proxy_server} if proxy_server else None

    async with async_playwright() as pw:
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-web-security",
        ]
        browser = await pw.chromium.launch(
            headless=True,
            args=args,
            proxy=proxy_config,
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="UTC",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"macOS"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        )

        page = await context.new_page()
        html_content = ""
        try:
            async def intercept_route(route):
                if route.request.resource_type in {"image", "media", "font"}:
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", intercept_route)

            logger.debug("Navigating to %s", search_url)
            await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)

            try:
                await page.wait_for_selector(
                    "div.job_seen_beacon, div.cardOutline, #mosaic-provider-jobcards, div[data-jk]",
                    timeout=6000,
                )
            except Exception:
                await page.wait_for_timeout(1500)

            html_content = await page.content()

            if "cf-turnstile" in html_content.lower() or "challenge-running" in html_content.lower():
                logger.warning("Bot challenge detected on Indeed (%s)", base_domain)
                html_content = ""

        except Exception as exc:
            logger.warning("Playwright navigation error for %s: %s", search_url, exc)
        finally:
            await page.close()
            await context.close()
            await browser.close()

    return html_content


async def fetch_indeed_jobs_async(
    country: str,
    query: str,
    location: str = "",
    max_results: int = 15,
    config: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    cfg = config or load_config()
    domain = get_indeed_domain(country, cfg)
    search_url = build_indeed_url(domain, query, location)
    cache_path = cfg.get("cache_file", DEFAULT_CACHE_PATH)
    cache = load_cache(cache_path)

    cache_key = f"indeed_{country.lower()}"

    logger.info("Fetching Indeed [%s] for query '%s' -> %s", country, query, search_url)

    html = await _fetch_indeed_page_playwright(search_url, domain)
    listings: List[JobListing] = []

    if html:
        listings = extract_jobs_from_indeed_html(html, domain)

    if listings:
        logger.info("Extracted %d jobs from Indeed [%s] via deterministic engine", len(listings), country)
        cache[cache_key] = {
            "last_success": time.time(),
            "domain": domain,
            "strategy": "deterministic_html",
        }
        save_cache(cache, cache_path)
        return [item.to_dict() for item in listings[:max_results]]

    logger.info("Cached/deterministic path returned 0 results for %s. Triggering agentic reasoning...", country)
    agent_listings = await _run_browser_use_agent(search_url, country, query, max_results=max_results)
    if agent_listings:
        cache[cache_key] = {
            "last_success": time.time(),
            "domain": domain,
            "strategy": "browser_use_agent",
        }
        save_cache(cache, cache_path)
        return [item.to_dict() for item in agent_listings[:max_results]]

    logger.warning("No jobs extracted for Indeed [%s] (query: '%s'). Skipped cleanly.", country, query)
    return []


def fetch_indeed_jobs(
    country: str,
    query: str,
    location: str = "",
    max_results: int = 15,
    config: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(fetch_indeed_jobs_async(country, query, location, max_results, config))

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            asyncio.run,
            fetch_indeed_jobs_async(country, query, location, max_results, config),
        )
        return future.result()


def fetch_all_jobboard_jobs(
    countries: Optional[List[str]] = None,
    queries: Optional[List[str]] = None,
    config_path: str = DEFAULT_CONFIG_PATH,
    max_results_override: Optional[int] = None,
) -> List[Dict[str, Any]]:
    cfg = load_config(config_path)
    target_countries = countries or cfg.get("active_countries", ["USA", "UK", "Canada"])
    target_queries = queries or cfg.get("search_queries", ["Junior AI Engineer"])
    max_results = max_results_override or cfg.get("max_results_per_query", 15)
    delay = cfg.get("request_delay_seconds", 2.0)

    all_jobs: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    total_tasks = len(target_countries) * len(target_queries)
    completed = 0

    logger.info(
        "Starting Job-Board scan across %d countries (%s) and %d queries (%d total queries)",
        len(target_countries), ", ".join(target_countries), len(target_queries), total_tasks,
    )

    for country in target_countries:
        for query in target_queries:
            completed += 1
            logger.info("[%d/%d] Fetching '%s' in %s", completed, total_tasks, query, country)
            try:
                jobs = fetch_indeed_jobs(
                    country=country,
                    query=query,
                    max_results=max_results,
                    config=cfg,
                )
                for j in jobs:
                    url = j.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_jobs.append(j)
            except Exception as exc:
                logger.warning("Error fetching jobs for %s [%s]: %s", country, query, exc)

            if delay > 0 and completed < total_tasks:
                time.sleep(delay)

    logger.info("Job-Board scan complete. Collected %d total candidate jobs.", len(all_jobs))
    return all_jobs


JOBBOARD_FETCHERS = {
    "indeed": fetch_indeed_jobs,
}

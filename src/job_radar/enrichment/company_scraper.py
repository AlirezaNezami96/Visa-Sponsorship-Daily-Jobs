"""Company website scraper for public team, leadership, metadata, and contact discovery.

Inspired by company-from-website architecture:
  - JSON-LD Organization schema extraction (official name, logo, description, socials)
  - Social profiles extraction (LinkedIn company page, GitHub, Twitter/X)
  - Public team & leadership card parsing (/team, /about, /leadership, /contact)
  - Department and direct email extraction
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlsplit
import requests
from bs4 import BeautifulSoup

from .email_finder import extract_emails_from_text

logger = logging.getLogger(__name__)

SCRAPER_TIMEOUT = 5.0
SCRAPER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

COMMON_TEAM_PATHS = ["/about", "/team", "/leadership", "/contact", "/about-us", "/company"]

_PHONE_REGEX = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


class CompanyWebsiteScraper:
    """Scrapes public company pages for JSON-LD info, team members, social links, and contacts."""

    def __init__(self, timeout: float = SCRAPER_TIMEOUT):
        self.timeout = timeout

    def scrape_company_team(self, company_domain: str) -> Dict[str, Any]:
        """Attempt to fetch and parse company metadata and team information."""
        domain = company_domain.lower().replace("http://", "").replace("https://", "").split("/")[0].strip()
        if not domain:
            return {
                "name": None,
                "description": None,
                "logo_url": None,
                "linkedin_url": None,
                "socials": {},
                "contacts": [],
                "emails": [],
                "phones": [],
                "pages_checked": [],
            }

        base_url = f"https://{domain}"
        found_contacts: List[Dict[str, Any]] = []
        found_emails: List[Dict[str, Any]] = []
        found_phones: List[str] = []
        checked_pages: List[str] = []
        socials: Dict[str, str] = {}
        company_info: Dict[str, Any] = {
            "name": None,
            "description": None,
            "logo_url": None,
            "linkedin_url": None,
        }

        # Check homepage first for JSON-LD and meta tags
        homepage_url = f"{base_url}/"
        checked_pages.append(homepage_url)
        try:
            home_resp = requests.get(
                homepage_url,
                headers={"User-Agent": SCRAPER_USER_AGENT},
                timeout=self.timeout,
                allow_redirects=True,
            )
            if home_resp.status_code == 200 and "text/html" in home_resp.headers.get("Content-Type", ""):
                meta_info = self._extract_jsonld_and_metadata(home_resp.text, base_url)
                company_info.update({k: v for k, v in meta_info.items() if v})
                socials.update(meta_info.get("socials", {}))

                # Extract emails & phones from homepage
                for em in extract_emails_from_text(home_resp.text):
                    em["source_type"] = "company_homepage"
                    found_emails.append(em)
                for ph in _PHONE_REGEX.findall(home_resp.text):
                    if ph not in found_phones:
                        found_phones.append(ph)
        except Exception as exc:
            logger.debug("Homepage scrape error for %s: %s", homepage_url, exc)

        # Check subpages for team members
        for path in COMMON_TEAM_PATHS:
            target_url = f"{base_url}{path}"
            checked_pages.append(target_url)
            try:
                resp = requests.get(
                    target_url,
                    headers={"User-Agent": SCRAPER_USER_AGENT},
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
                    # Extract emails
                    emails = extract_emails_from_text(resp.text)
                    for em in emails:
                        em["source_type"] = f"company_website{path}"
                        if not any(e["email"] == em["email"] for e in found_emails):
                            found_emails.append(em)

                    # Extract phones
                    for ph in _PHONE_REGEX.findall(resp.text):
                        if ph not in found_phones:
                            found_phones.append(ph)

                    # Extract subpage socials
                    sub_meta = self._extract_jsonld_and_metadata(resp.text, base_url)
                    socials.update({k: v for k, v in sub_meta.get("socials", {}).items() if v and k not in socials})
                    if not company_info.get("linkedin_url") and sub_meta.get("linkedin_url"):
                        company_info["linkedin_url"] = sub_meta["linkedin_url"]

                    # Extract team members via HTML patterns
                    members = self._extract_members_from_html(resp.text)
                    found_contacts.extend(members)

                    # If we found team cards, stop scanning further pages
                    if members:
                        break
            except Exception as exc:
                logger.debug("Company scrape error for %s: %s", target_url, exc)

        if socials.get("linkedin") and not company_info.get("linkedin_url"):
            company_info["linkedin_url"] = socials["linkedin"]

        return {
            "name": company_info.get("name"),
            "description": company_info.get("description"),
            "logo_url": company_info.get("logo_url"),
            "linkedin_url": company_info.get("linkedin_url"),
            "socials": socials,
            "contacts": found_contacts[:10],
            "emails": found_emails[:10],
            "phones": found_phones[:5],
            "pages_checked": checked_pages,
        }

    def _extract_jsonld_and_metadata(self, html_text: str, base_url: str) -> Dict[str, Any]:
        """Extract JSON-LD Organization schema and OpenGraph metadata."""
        info: Dict[str, Any] = {
            "name": None,
            "description": None,
            "logo_url": None,
            "linkedin_url": None,
            "socials": {},
        }
        try:
            soup = BeautifulSoup(html_text, "html.parser")

            # 1. Parse JSON-LD scripts
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "{}")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        schema_type = str(item.get("@type", "")).lower()
                        if schema_type in ("organization", "corporation", "company"):
                            if item.get("name") and not info["name"]:
                                info["name"] = item["name"]
                            if item.get("description") and not info["description"]:
                                info["description"] = item["description"]
                            if item.get("logo") and not info["logo_url"]:
                                logo = item["logo"]
                                info["logo_url"] = logo.get("url") if isinstance(logo, dict) else str(logo)
                            same_as = item.get("sameAs") or []
                            if isinstance(same_as, str):
                                same_as = [same_as]
                            for url in same_as:
                                if "linkedin.com" in url:
                                    info["linkedin_url"] = url
                                    info["socials"]["linkedin"] = url
                                elif "twitter.com" in url or "x.com" in url:
                                    info["socials"]["twitter"] = url
                                elif "github.com" in url:
                                    info["socials"]["github"] = url
                except Exception:
                    continue

            # 2. Parse OpenGraph and Meta tags
            if not info["description"]:
                meta_desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
                if meta_desc and meta_desc.get("content"):
                    info["description"] = meta_desc["content"].strip()

            if not info["logo_url"]:
                og_img = soup.find("meta", property="og:image")
                if og_img and og_img.get("content"):
                    info["logo_url"] = urljoin(base_url, og_img["content"])

            # 3. Find Social Profile links in HTML
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "linkedin.com/company/" in href and not info.get("linkedin_url"):
                    info["linkedin_url"] = href
                    info["socials"]["linkedin"] = href
                elif ("twitter.com/" in href or "x.com/" in href) and "twitter" not in info["socials"]:
                    info["socials"]["twitter"] = href
                elif "github.com/" in href and "github" not in info["socials"]:
                    info["socials"]["github"] = href
        except Exception as exc:
            logger.debug("JSON-LD & metadata parsing failed: %s", exc)

        return info

    def _extract_members_from_html(self, html_text: str) -> List[Dict[str, Any]]:
        """Heuristically extract name + title pairs from leadership cards."""
        members: List[Dict[str, Any]] = []
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            cards = soup.find_all(
                lambda tag: any(
                    c in str(tag.get("class", "")).lower()
                    for c in ["team-member", "leader", "person", "bio", "speaker"]
                )
            )
            for card in cards[:10]:
                h_tag = card.find(["h2", "h3", "h4", "h5", "strong"])
                if not h_tag:
                    continue
                name = h_tag.get_text().strip()
                if not name or len(name) > 40 or len(name.split()) < 2:
                    continue

                # Find title
                p_tag = card.find(
                    ["p", "span", "div"],
                    class_=lambda c: c and any(k in str(c).lower() for k in ["title", "role", "position"]),
                )
                title = p_tag.get_text().strip() if p_tag else "Team Member"

                members.append({
                    "name": name,
                    "title": title[:60],
                    "source_method": "company_website_scraping",
                    "confidence_score": 60,
                })
        except Exception as exc:
            logger.debug("HTML parsing failed: %s", exc)

        return members

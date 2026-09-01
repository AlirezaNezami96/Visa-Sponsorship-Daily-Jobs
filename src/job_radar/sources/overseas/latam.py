"""
src/job_radar/sources/overseas/latam.py

Latin American Multi-Country Job Board Adapters:
  - Computrabajo: 19 countries (computrabajo.com.ar, computrabajo.com.co, computrabajo.com.mx, computrabajo.cl, etc.)
  - Bumeran: 7 countries (bumeran.com.ar, bumeran.com.pe, bumeran.com.mx, etc.)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from job_radar.models.job import Job

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

COMPUTRABAJO_DOMAINS: Dict[str, str] = {
    "AR": "https://ar.computrabajo.com",
    "CL": "https://cl.computrabajo.com",
    "CO": "https://co.computrabajo.com",
    "CR": "https://cr.computrabajo.com",
    "EC": "https://ec.computrabajo.com",
    "GT": "https://gt.computrabajo.com",
    "MX": "https://mx.computrabajo.com",
    "PA": "https://pa.computrabajo.com",
    "PE": "https://pe.computrabajo.com",
    "UY": "https://uy.computrabajo.com",
}

BUMERAN_DOMAINS: Dict[str, str] = {
    "AR": "https://www.bumeran.com.ar",
    "PE": "https://www.bumeran.com.pe",
    "EC": "https://www.multitrabajos.com",
    "PA": "https://www.konzerta.com",
    "MX": "https://www.bumeran.com.mx",
}


def fetch_computrabajo_jobs(
    country_code: str = "MX",
    query: str = "ingeniero",
    limit: int = 25,
) -> List[Job]:
    """Fetch jobs from country-specific Computrabajo portal."""
    c_code = country_code.upper().strip()
    base_url = COMPUTRABAJO_DOMAINS.get(c_code, "https://mx.computrabajo.com")
    search_url = f"{base_url}/trabajo-de-{query}"

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}
    jobs: List[Job] = []

    try:
        resp = requests.get(search_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.find_all("article", class_=lambda c: c and "box_offer" in c) or soup.find_all("div", class_="offer")

        for idx, art in enumerate(articles[:limit]):
            title_tag = art.find("a", class_=lambda c: c and "js-o-link" in c) or art.find("h2") or art.find("a")
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            link = title_tag.get("href", "")
            if link and not link.startswith("http"):
                link = f"{base_url}{link}"

            comp_tag = art.find("p", class_=lambda c: c and "it-blank" in c) or art.find("span", class_="company")
            comp_name = comp_tag.get_text(strip=True) if comp_tag else "Confidential LATAM"

            loc_tag = art.find("span", class_=lambda c: c and "location" in c) or art.find("p", class_="fs13")
            location = loc_tag.get_text(strip=True) if loc_tag else c_code

            snippet_tag = art.find("p", class_=lambda c: c and "fc_base" in c) or art.find("p")
            snippet = snippet_tag.get_text(separator=" ", strip=True) if snippet_tag else ""

            is_remote = "remoto" in location.lower() or "remoto" in title.lower() or "teletrabajo" in snippet.lower()

            jobs.append(
                Job(
                    id=f"computrabajo-{c_code.lower()}-{idx}-{abs(hash(link or title))}",
                    source="computrabajo",
                    country=c_code,
                    company=comp_name,
                    title=title,
                    location=f"{location}, {c_code}",
                    remote=is_remote,
                    apply_url=link or base_url,
                    job_url=link or base_url,
                    description=snippet or f"{title} en {comp_name} ({location})",
                    metadata={"overseas": True, "source_category": "commercial_board", "country": c_code},
                )
            )
    except Exception as exc:
        logger.debug("Computrabajo fetch error for %s: %s", c_code, exc)

    return jobs


def fetch_bumeran_jobs(
    country_code: str = "AR",
    query: str = "profesional",
    limit: int = 25,
) -> List[Job]:
    """Fetch jobs from country-specific Bumeran network portal."""
    c_code = country_code.upper().strip()
    base_url = BUMERAN_DOMAINS.get(c_code, "https://www.bumeran.com.ar")
    search_url = f"{base_url}/empleos-busqueda-{query}.html"

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"}
    jobs: List[Job] = []

    try:
        resp = requests.get(search_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("div", id=lambda i: i and "aviso" in i) or soup.find_all("article")

        for idx, card in enumerate(cards[:limit]):
            title_tag = card.find("h2") or card.find("h3") or card.find("a")
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            link_tag = card.find("a", href=True)
            link = link_tag["href"] if link_tag else ""
            if link and not link.startswith("http"):
                link = f"{base_url}{link}"

            comp_tag = card.find("h3") or card.find("span", class_=lambda c: c and "empresa" in c)
            comp_name = comp_tag.get_text(strip=True) if comp_tag else "Bumeran Employer"

            jobs.append(
                Job(
                    id=f"bumeran-{c_code.lower()}-{idx}-{abs(hash(link or title))}",
                    source="bumeran",
                    country=c_code,
                    company=comp_name,
                    title=title,
                    location=c_code,
                    remote="remoto" in title.lower(),
                    apply_url=link or base_url,
                    job_url=link or base_url,
                    description=f"{title} en {comp_name}",
                    metadata={"overseas": True, "source_category": "commercial_board", "country": c_code},
                )
            )
    except Exception as exc:
        logger.debug("Bumeran fetch error for %s: %s", c_code, exc)

    return jobs

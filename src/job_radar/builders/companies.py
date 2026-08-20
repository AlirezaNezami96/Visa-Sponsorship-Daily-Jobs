"""Build companies.json from curated lists and live repositories."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Dict, List, Tuple
import requests

from job_radar.fetchers.classify import classify as classify_ats

logger = logging.getLogger(__name__)

ALLOWED_KEYWORDS = {
    "united kingdom", "uk", "gb", "england", "scotland", "wales", "london", "manchester", "edinburgh", "cambridge",
    "germany", "de", "deutschland", "berlin", "munich", "hamburg", "frankfurt", "cologne", "stuttgart",
    "netherlands", "nl", "holland", "amsterdam", "rotterdam", "utrecht", "eindhoven", "the hague",
    "sweden", "se", "stockholm", "gothenburg", "malmo",
    "denmark", "dk", "copenhagen", "aarhus",
    "finland", "fi", "helsinki", "espoo",
    "norway", "no", "oslo", "bergen",
    "ireland", "ie", "dublin", "cork", "galway",
    "france", "fr", "paris", "lyon", "toulouse",
    "spain", "es", "barcelona", "madrid", "valencia",
    "portugal", "pt", "lisbon", "porto",
    "italy", "it", "milan", "rome", "turin",
    "belgium", "be", "brussels", "antwerp", "ghent",
    "austria", "at", "vienna", "linz",
    "switzerland", "ch", "zurich", "geneva", "lausanne", "basel",
    "poland", "pl", "warsaw", "krakow", "wroclaw",
    "czech republic", "cz", "czechia", "prague", "brno",
    "hungary", "hu", "budapest",
    "romania", "ro", "bucharest", "cluj",
    "estonia", "ee", "tallinn", "tartu",
    "latvia", "lv", "riga",
    "lithuania", "lt", "vilnius", "kaunas",
    "slovakia", "sk", "bratislava",
    "slovenia", "si", "ljubljana",
    "croatia", "hr", "zagreb",
    "bulgaria", "bg", "sofia",
    "greece", "gr", "athens",
    "luxembourg", "lu",
    "malta", "mt",
    "cyprus", "cy",
    "iceland", "is", "reykjavik",
    "turkey", "tr", "türkiye", "turkiye", "istanbul", "ankara", "izmir",
    "canada", "ca", "toronto", "vancouver", "montreal", "ottawa", "calgary", "waterloo",
    "australia", "au", "sydney", "melbourne", "brisbane", "perth", "adelaide",
    "new zealand", "nz", "auckland", "wellington", "christchurch",
    "europe", "eu", "european union", "nordics", "baltics"
}

EXCLUDED_KEYWORDS = {
    "united states", "usa", "us", "india", "china", "japan", "singapore",
    "brazil", "nigeria", "south africa", "egypt", "vietnam", "indonesia",
    "philippines", "hong kong", "taiwan", "korea", "malaysia", "thailand",
    "mexico", "colombia", "argentina", "chile", "pakistan", "bangladesh"
}


def is_allowed_region(text: str) -> bool:
    if not text:
        return True
    lower = text.lower()
    for exc in EXCLUDED_KEYWORDS:
        if exc in lower:
            if any(kw in lower for kw in ["uk", "canada", "australia", "germany", "netherlands", "europe", "turkey", "new zealand"]):
                continue
            return False
    return any(kw in lower for kw in ALLOWED_KEYWORDS)


def deduplicate(companies: list) -> list:
    priority = {
        "greenhouse": 5, "lever": 5, "ashby": 5,
        "smartrecruiters": 5, "personio": 5, "workable": 5,
        "workday": 2, "custom": 1, "unknown": 0,
    }
    seen = {}
    for co in companies:
        name_clean = co["name"].strip()
        key = name_clean.lower()
        if not key:
            continue
        if key not in seen:
            seen[key] = dict(co)
            seen[key]["name"] = name_clean
        else:
            existing = seen[key]
            if priority.get(existing.get("ats"), 0) < priority.get(co.get("ats"), 0):
                seen[key] = dict(co)
                seen[key]["name"] = name_clean
            elif not existing.get("careers_url") and co.get("careers_url"):
                existing["careers_url"] = co["careers_url"]
    return list(seen.values())


def build_companies(output_file: str = "companies.json") -> dict:
    from build_companies import CURATED, parse_amol_can_eu, parse_geshan_au, parse_komeilmehranfar, parse_shubheksha, parse_siaexplains
    all_companies = []

    for name, ats, slug, source in CURATED:
        if ats == "greenhouse":
            url = f"https://boards.greenhouse.io/{slug}"
        elif ats == "lever":
            url = f"https://jobs.lever.co/{slug}"
        elif ats == "ashby":
            url = f"https://{slug}.ashbyhq.com"
        elif ats == "smartrecruiters":
            url = f"https://careers.smartrecruiters.com/{slug}"
        else:
            url = ""
        all_companies.append({
            "name": name,
            "careers_url": url,
            "ats": ats,
            "slug": slug,
            "source": source,
        })

    all_companies.extend(parse_shubheksha())
    all_companies.extend(parse_geshan_au())
    all_companies.extend(parse_siaexplains())
    all_companies.extend(parse_komeilmehranfar())
    all_companies.extend(parse_amol_can_eu())

    all_companies = deduplicate(all_companies)

    API_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "personio", "workable"}
    scrapable = [c for c in all_companies if c.get("ats") in API_ATS]
    custom = [
        c for c in all_companies
        if c.get("ats") not in API_ATS and c.get("careers_url")
    ]
    scrapable_names = {c["name"].lower() for c in scrapable}
    custom = [c for c in custom if c["name"].lower() not in scrapable_names]

    output = {
        "scrapable": scrapable,
        "custom_ats": custom,
        "last_updated": time.strftime("%Y-%m-%d"),
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return output

"""Build remote_companies.json from remote community repos and curated lists."""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)


def build_remote_companies(output_file: str = "remote_companies.json") -> dict:
    from build_remote_companies import (
        CURATED_REMOTE,
        deduplicate,
        parse_adherb,
        parse_andrews1022,
        parse_flexbox,
        parse_hugo53,
        parse_lukasz_madon,
        parse_remoteintech,
        parse_sergey_shakhov,
        parse_yanirs,
    )

    all_companies = []
    for name, ats, slug in CURATED_REMOTE:
        if ats == "greenhouse":
            url = f"https://boards.greenhouse.io/{slug}"
        elif ats == "lever":
            url = f"https://jobs.lever.co/{slug}"
        elif ats == "ashby":
            url = f"https://{slug}.ashbyhq.com"
        elif ats == "smartrecruiters":
            url = f"https://careers.smartrecruiters.com/{slug}"
        elif ats == "workable":
            url = f"https://apply.workable.com/{slug}"
        else:
            url = ""
        all_companies.append({
            "name": name,
            "careers_url": url,
            "ats": ats,
            "slug": slug,
            "source": "curated_remote",
        })

    all_companies.extend(parse_yanirs())
    all_companies.extend(parse_remoteintech())
    all_companies.extend(parse_adherb())
    all_companies.extend(parse_lukasz_madon())
    all_companies.extend(parse_andrews1022())
    all_companies.extend(parse_sergey_shakhov())
    all_companies.extend(parse_flexbox())
    all_companies.extend(parse_hugo53())

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

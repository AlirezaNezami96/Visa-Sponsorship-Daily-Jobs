"""ATS Discovery (Root Compatibility Facade)."""
from __future__ import annotations

from job_radar.fetchers.discover import (
    HEADERS,
    KNOWN_SLUGS,
    try_discover_ats,
)

__all__ = [
    "HEADERS",
    "KNOWN_SLUGS",
    "try_discover_ats",
]

if __name__ == "__main__":
    import json
    import time
    with open("companies.json", "r") as f:
        data = json.load(f)

    all_companies = data.get("scrapable", []) + data.get("custom_ats", [])
    updated_scrapable = []
    updated_custom = []
    discovered = 0

    for co in all_companies:
        name = co["name"].lower()
        if name in KNOWN_SLUGS:
            ats, slug = KNOWN_SLUGS[name]
            if ats != "custom":
                co["ats"] = ats
                co["slug"] = slug
                if ats == "greenhouse":
                    co["careers_url"] = f"https://boards.greenhouse.io/{slug}"
                elif ats == "lever":
                    co["careers_url"] = f"https://jobs.lever.co/{slug}"
                elif ats == "ashby":
                    co["careers_url"] = f"https://{slug}.ashbyhq.com"
                updated_scrapable.append(co)
                discovered += 1
                print(f"  [KNOWN] {co['name']} -> {ats} ({slug})")
                continue

        if co["ats"] in ("custom", "unknown", "workday"):
            print(f"  [PROBE] {co['name']}...", end=" ", flush=True)
            ats, slug = try_discover_ats(co["name"], co.get("careers_url", ""))
            if ats:
                co["ats"] = ats
                co["slug"] = slug
                if ats == "greenhouse":
                    co["careers_url"] = f"https://boards.greenhouse.io/{slug}"
                elif ats == "lever":
                    co["careers_url"] = f"https://jobs.lever.co/{slug}"
                elif ats == "ashby":
                    co["careers_url"] = f"https://{slug}.ashbyhq.com"
                updated_scrapable.append(co)
                discovered += 1
                print(f"-> {ats} ({slug})")
            else:
                updated_custom.append(co)
                print("-> still custom")
            time.sleep(0.5)
        else:
            updated_scrapable.append(co)

    data["scrapable"] = updated_scrapable
    data["custom_ats"] = updated_custom
    data["last_updated"] = time.strftime("%Y-%m-%d")

    with open("companies.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nDiscovered {discovered} new ATS mappings")
    print(f"Scrapable (API): {len(updated_scrapable)}")
    print(f"Custom (Playwright): {len(updated_custom)}")

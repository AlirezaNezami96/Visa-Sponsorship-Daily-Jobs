r"""
ATS Discovery: For companies with generic careers URLs,
try common ATS URL patterns to find their actual job board.

Run: python discover_ats.py
This will update companies.json with discovered ATS info.
"""
import json
import requests
import time
from classify import classify
from urllib.parse import urlparse

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobScraper/1.0)"}

# Common company name -> known ATS slug mappings
# Add more as you discover them
KNOWN_SLUGS = {
    "stripe": ("greenhouse", "stripe"),
    "shopify": ("greenhouse", "shopify"),
    "spotify": ("greenhouse", "spotify"),
    "datadog": ("greenhouse", "datadog"),
    "revolut": ("lever", "revolut"),
    "intercom": ("lever", "intercom"),
    "monzo": ("greenhouse", "monzo"),
    "doordash": ("greenhouse", "doordash"),
    "coinbase": ("greenhouse", "coinbase"),
    "airbnb": ("greenhouse", "airbnb"),
    "notion": ("lever", "notion"),
    "vercel": ("lever", "vercel"),
    "linear": ("ashby", "linear"),
    "supabase": ("ashby", "supabase"),
    "cal": ("ashby", "cal"),
    "figma": ("greenhouse", "figma"),
    "plaid": ("greenhouse", "plaid"),
    "affirm": ("greenhouse", "affirm"),
    "chime": ("greenhouse", "chimefinancial"),
    "canva": ("greenhouse", "canva"),
    "atlassian": ("greenhouse", "atlassian"),
    "aiven": ("greenhouse", "aiven"),
    "squareup": ("greenhouse", "block"),
    "lendi": ("smartrecruiters", "LendiGroup1"),
    "isential": ("custom", None),  # workable
    "booking.com": ("custom", None),
    "adyen": ("greenhouse", "adyen"),
    "klarna": ("lever", "klarna"),
    "zalando": ("greenhouse", "zalando"),
    "hellofresh": ("greenhouse", "hellofresh"),
    "trivago": ("workday", None),
    "deliveroo": ("greenhouse", "deliveroo"),
    "wise": ("greenhouse", "wise"),
    "twilio": ("greenhouse", "twilio"),
    "hashicorp": ("greenhouse", "hashicorp"),
    "deputy": ("greenhouse", "deputy"),
    "redbubble": ("greenhouse", "redbubble"),
    "envato": ("lever", "envato"),
    "finder": ("greenhouse", "finder"),
    "rei group": ("lever", "realestate"),
    "linktree": ("ashby", "linktree"),
    "safetyculture": ("lever", "safetyculture"),
    "rokt": ("greenhouse", "rokt"),
    "optiver": ("greenhouse", "optiver"),
    "gocardless": ("greenhouse", "gocardless"),
    "skyscanner": ("greenhouse", "skyscanner"),
    "quantumblack": ("workday", None),
    "backbase": ("greenhouse", "backbase"),
    "celonis": ("greenhouse", "celonis"),
    "sap se": ("greenhouse", "sap"),
    "zendesk": ("greenhouse", "zendesk"),
    "expert360": ("greenhouse", "expert360"),
    "iress": ("workday", None),
    "orica": ("workday", None),
    "nine": ("workday", None),
    "tyro": ("greenhouse", "tyro"),
    "hipages": ("greenhouse", "hipages"),
    "propeller": ("greenhouse", "propelleraero"),
    "harrison.ai": ("lever", "harrisonai"),
    "healthengine": ("greenhouse", "healthengine"),
}


def try_discover_ats(name: str, current_url: str) -> tuple:
    """Try to discover a company's ATS by probing common URL patterns."""
    slug_variants = [
        name.lower().replace(" ", "").replace(".", "").replace("-", ""),
        name.lower().replace(" ", "-"),
        name.lower().replace(" ", ""),
    ]
    # Remove common suffixes
    for suffix in ["ag", "se", "gmbh", "ltd", "inc", "llc", "pty", "pty ltd"]:
        slug_base = name.lower().replace(" ", "").replace(".", "")
        if slug_base.endswith(suffix):
            slug_variants.append(slug_base[:-len(suffix)])

    # Remove duplicates while preserving order
    seen = set()
    unique_slugs = []
    for s in slug_variants:
        if s and s not in seen:
            seen.add(s)
            unique_slugs.append(s)

    # Try each ATS pattern
    tests = []
    for slug in unique_slugs:
        tests.append((f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", "greenhouse", slug))
        tests.append((f"https://api.lever.co/v0/postings/{slug}?mode=json", "lever", slug))
        tests.append((f"https://api.ashbyhq.com/posting-api/job-board/{slug}", "ashby", slug))

    for url, ats, slug in tests:
        try:
            r = requests.get(url, timeout=8, headers=HEADERS)
            if r.status_code == 200:
                data = r.json()
                # Verify it has jobs data
                if ats == "greenhouse" and data.get("jobs"):
                    return ats, slug
                elif ats == "lever" and isinstance(data, list):
                    return ats, slug
                elif ats == "ashby" and data.get("jobPostings"):
                    return ats, slug
        except Exception:
            pass

    return None, None


def main():
    with open("companies.json", "r") as f:
        data = json.load(f)

    all_companies = data.get("scrapable", []) + data.get("custom_ats", [])
    updated_scrapable = []
    updated_custom = []
    discovered = 0

    for co in all_companies:
        name = co["name"].lower()

        # Check known mappings first
        if name in KNOWN_SLUGS:
            ats, slug = KNOWN_SLUGS[name]
            if ats != "custom":
                # Update the company
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

        # For companies still on custom/unknown, try discovery
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
            time.sleep(0.5)  # Be polite
        else:
            updated_scrapable.append(co)

    data["scrapable"] = updated_scrapable
    data["custom_ats"] = updated_custom
    import time as t
    data["last_updated"] = t.strftime("%Y-%m-%d")

    with open("companies.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nDiscovered {discovered} new ATS mappings")
    print(f"Scrapable (API): {len(updated_scrapable)}")
    print(f"Custom (Playwright): {len(updated_custom)}")


if __name__ == "__main__":
    main()

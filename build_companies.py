"""
Build companies.json from the 4 GitHub repos + curated ATS-known companies.
Run locally or in GitHub Actions to refresh the company list.
"""
import re
import json
import time
import requests
from urllib.parse import urljoin

# === REPOS ===
REPOS = {
    "shubheksha": "https://raw.githubusercontent.com/shubheksha/companies-sponsoring-visas/master/README.md",
    "geshan": "https://raw.githubusercontent.com/geshan/au-companies-providing-work-visa-sponsorship/master/README.md",
}

ATS_PATTERNS = {
    "greenhouse":      r"boards\.greenhouse\.io/([\w\-]+)/?",
    "lever":           r"jobs\.lever\.co/([\w\-]+)/?",
    "ashby":           r"ashbyhq\.com/([\w\-]+)/?",
    "smartrecruiters": r"careers\.smartrecruiters\.com/([\w\-]+)/?",
    "personio":        r"([\w\-]+)\.jobs\.personio\.de",
    "workday":         r"mywd\.jobs|wd\d?\.myworkdaysite|workday\.com",
}

# === CURATED: Companies known to use specific ATS ===
# Format: (name, ats, slug, source)
CURATED = [
    # From shubheksha repo - manually verified ATS
    ("Stripe", "greenhouse", "stripe", "shubheksha"),
    ("Shopify", "greenhouse", "shopify", "shubheksha"),
    ("Spotify", "greenhouse", "spotify", "shubheksha"),
    ("Klarna", "lever", "klarna", "shubheksha"),
    ("Zalando", "greenhouse", "zalando", "shubheksha"),
    ("Delivery Hero", "greenhouse", "deliveryhero", "shubheksha"),
    ("Datadog", "greenhouse", "datadog", "shubheksha"),
    ("Revolut", "lever", "revolut", "shubheksha"),
    ("Intercom", "lever", "intercom", "shubheksha"),
    ("HelloFresh", "greenhouse", "hellofresh", "shubheksha"),
    ("Hashicorp", "greenhouse", "hashicorp", "shubheksha"),
    ("Monzo", "greenhouse", "monzo", "shubheksha"),
    ("Deliveroo", "greenhouse", "deliveroo", "shubheksha"),
    ("GoCardless", "greenhouse", "gocardless", "shubheksha"),
    ("Adyen", "greenhouse", "adyen", "shubheksha"),
    ("Twilio", "greenhouse", "twilio", "shubheksha"),
    ("Attest", "lever", "attest", "shubheksha"),
    # Australian companies from geshan repo
    ("Canva", "greenhouse", "canva", "geshan"),
    ("Atlassian", "greenhouse", "atlassian", "geshan"),
    ("Aiven", "greenhouse", "aiven", "geshan"),
    ("Lendi", "smartrecruiters", "LendiGroup1", "geshan"),
    ("RedBubble", "greenhouse", "redbubble", "geshan"),
    ("Envato", "lever", "envato", "geshan"),
    ("SafetyCulture", "lever", "safetyculture", "geshan"),
    ("Rokt", "greenhouse", "rokt", "geshan"),
    ("Optiver", "greenhouse", "optiver", "geshan"),
    ("Propeller", "greenhouse", "propelleraero", "geshan"),
    ("Harrison.Ai", "lever", "harrisonai", "geshan"),
    ("HealthEngine", "greenhouse", "healthengine", "geshan"),
    ("Tyro", "greenhouse", "tyro", "geshan"),
    ("Deputy", "greenhouse", "deputy", "geshan"),
    ("Expert360", "greenhouse", "expert360", "geshan"),
    ("Linktree", "ashby", "linktree", "geshan"),
    ("SquareUp", "greenhouse", "block", "geshan"),
    ("Zendesk", "greenhouse", "zendesk", "geshan"),
    ("Qwilr", "lever", "qwilr", "geshan"),
    ("Finder", "greenhouse", "finder", "geshan"),
    ("REA Group", "lever", "reagroup", "geshan"),
    ("Brighte", "lever", "brighte", "geshan"),
    ("Celonis", "greenhouse", "celonis", "komeilmehranfar"),
    ("SAP SE", "greenhouse", "sap", "komeilmehranfar"),
    ("Backbase", "greenhouse", "backbase", "komeilmehranfar"),
    ("ING", "greenhouse", "ing", "komeilmehranfar"),
    # Additional well-known visa sponsors with known ATS
    ("Coinbase", "greenhouse", "coinbase", "curated"),
    ("Airbnb", "greenhouse", "airbnb", "curated"),
    ("Plaid", "greenhouse", "plaid", "curated"),
    ("Figma", "greenhouse", "figma", "curated"),
    ("Notion", "lever", "notion", "curated"),
    ("Vercel", "lever", "vercel", "curated"),
    ("Linear", "ashby", "linear", "curated"),
    ("Supabase", "ashby", "supabase", "curated"),
    ("Affirm", "greenhouse", "affirm", "curated"),
    ("DoorDash", "greenhouse", "doordash", "curated"),
    ("Wise", "greenhouse", "wise", "curated"),
    ("GitLab", "greenhouse", "gitlab", "curated"),
    ("CircleCI", "greenhouse", "circleci", "curated"),
    ("Palo Alto Networks", "greenhouse", "paloaltonetworks", "curated"),
    ("Cloudflare", "greenhouse", "cloudflare", "curated"),
    ("GitHub", "greenhouse", "github", "curated"),
    ("Shopify", "greenhouse", "shopify", "curated"),
    ("Databricks", "greenhouse", "databricks", "curated"),
    ("Snowflake", "greenhouse", "snowflake", "curated"),
    ("Confluent", "greenhouse", "confluent", "curated"),
    ("MongoDB", "greenhouse", "mongodb", "curated"),
    ("Elastic", "greenhouse", "elastic", "curated"),
    ("Grafana Labs", "greenhouse", "grafanalabs", "curated"),
    ("HashiCorp", "greenhouse", "hashicorp", "curated"),
    ("PagerDuty", "greenhouse", "pagerduty", "curated"),
    ("Twilio", "greenhouse", "twilio", "curated"),
    ("HubSpot", "greenhouse", "hubspot", "curated"),
    ("Toast", "greenhouse", "toasttab", "curated"),
    ("Block", "greenhouse", "block", "curated"),
    ("Discord", "greenhouse", "discord", "curated"),
    ("Reddit", "greenhouse", "reddit", "curated"),
    ("Pinterest", "greenhouse", "pinterest", "curated"),
    ("Roblox", "greenhouse", "roblox", "curated"),
    ("Riot Games", "greenhouse", "riotgames", "curated"),
    ("Epic Games", "greenhouse", "epicgames", "curated"),
    ("Unity", "greenhouse", "unity", "curated"),
    ("Cruise", "greenhouse", "cruise", "curated"),
    ("Rippling", "lever", "rippling", "curated"),
    ("Deel", "lever", "deel", "curated"),
    ("Remote", "lever", "remote", "curated"),
    ("Oyster", "lever", "oysterhr", "curated"),
    ("Multiverse", "lever", "multiverse", "curated"),
    ("Snyk", "lever", "snyk", "curated"),
    ("Mezmo", "lever", "mezmo", "curated"),
    ("PostHog", "lever", "posthog", "curated"),
    ("Cal.com", "ashby", "cal", "curated"),
    ("Dub", "ashby", "dub", "curated"),
    ("Metabase", "greenhouse", "metabase", "curated"),
    ("Postman", "greenhouse", "postman", "curated"),
    ("Sourcegraph", "greenhouse", "sourcegraph", "curated"),
    ("PlanetScale", "greenhouse", "planetscale", "curated"),
    ("Temporal", "greenhouse", "temporal", "curated"),
    ("Cockroach Labs", "greenhouse", "cockroach-labs", "curated"),
    ("Hasura", "greenhouse", "hasura", "curated"),
    ("Appsmith", "greenhouse", "appsmith", "curated"),
    ("Baseten", "lever", "baseten", "curated"),
    ("Anyscale", "greenhouse", "anyscale", "curated"),
    ("Modal", "greenhouse", "modal-labs", "curated"),
    ("Weights & Biases", "greenhouse", "wandb", "curated"),
    ("Hugging Face", "greenhouse", "huggingface", "curated"),
    ("Stability AI", "lever", "stabilityai", "curated"),
    ("Together AI", "greenhouse", "togetherai", "curated"),
    ("Mistral AI", "greenhouse", "mistralai", "curated"),
    ("Anthropic", "greenhouse", "anthropic", "curated"),
    ("Replit", "lever", "replit", "curated"),
    ("Vercel", "lever", "vercel", "curated"),
    ("LlamaIndex", "ashby", "llamaindex", "curated"),
    ("LangChain", "ashby", "langchain", "curated"),
    ("Pinecone", "greenhouse", "pinecone", "curated"),
    ("Weaviate", "greenhouse", "weaviate", "curated"),
    ("Qdrant", "lever", "qdrant", "curated"),
    ("Chroma", "greenhouse", "chroma", "curated"),
    ("Nomic AI", "greenhouse", "nomic", "curated"),
]


def classify_ats(url):
    if not url:
        return "unknown", None
    for ats, pattern in ATS_PATTERNS.items():
        m = re.search(pattern, url, re.IGNORECASE)
        if m:
            slug = m.group(1) if ats != "workday" else None
            return ats, slug
    return "custom", None


def parse_shubheksha():
    print("Fetching shubheksha repo...")
    try:
        r = requests.get(REPOS["shubheksha"], timeout=30)
    except Exception as e:
        print(f"  Error: {e}")
        return []
    companies = []
    for line in r.text.split("\n"):
        if not line.strip().startswith("|") or line.strip().startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 4:
            continue
        name = parts[0].strip()
        careers = parts[3].strip()
        if not name or name.lower().startswith("name"):
            continue
        m = re.search(r"\[.*?\]\((https?://[^)]+)\)", careers)
        if m:
            careers = m.group(1)
        elif not careers.startswith("http"):
            continue
        ats, slug = classify_ats(careers)
        companies.append({
            "name": name,
            "careers_url": careers,
            "ats": ats,
            "slug": slug,
            "source": "shubheksha",
        })
    print(f"  Found {len(companies)} companies")
    return companies


def parse_geshan():
    print("Fetching geshan AU repo...")
    try:
        r = requests.get(REPOS["geshan"], timeout=30)
    except Exception as e:
        print(f"  Error: {e}")
        return []
    companies = []
    for line in r.text.split("\n"):
        m = re.match(r"^-\s+\[([^\]]+)\]\((https?://[^)]+)\)", line)
        if m:
            name, url = m.group(1), m.group(2)
            ats, slug = classify_ats(url)
            companies.append({
                "name": name,
                "careers_url": url,
                "ats": ats,
                "slug": slug,
                "source": "geshan",
            })
    print(f"  Found {len(companies)} companies")
    return companies


def deduplicate(companies):
    seen = {}
    result = []
    for co in companies:
        key = co["name"].lower().strip()
        if key in seen:
            existing = seen[key]
            # Prefer API-scrapable over custom
            priority = {"greenhouse": 5, "lever": 5, "ashby": 5, "smartrecruiters": 5, "personio": 5, "workday": 2, "custom": 1, "unknown": 0}
            if priority.get(existing["ats"], 0) < priority.get(co["ats"], 0):
                seen[key] = co
            continue
        seen[key] = co
        result.append(co)
    return result


def main():
    all_companies = []

    # 1. Add curated companies (highest priority, known ATS)
    print("Adding curated companies...")
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
    print(f"  Added {len(CURATED)} curated companies")

    # 2. Fetch from repos
    time.sleep(0.5)
    repo_companies = parse_shubheksha()
    time.sleep(0.5)
    repo_companies.extend(parse_geshan())

    # Merge (curated takes priority, repo data fills gaps)
    all_companies.extend(repo_companies)
    all_companies = deduplicate(all_companies)

    # 3. Split by ATS type
    API_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "personio"}
    scrapable = [c for c in all_companies if c["ats"] in API_ATS]
    custom = [c for c in all_companies if c["ats"] not in API_ATS and c.get("careers_url")]

    # Remove curated from custom if they're already in scrapable
    scrapable_names = {c["name"].lower() for c in scrapable}
    custom = [c for c in custom if c["name"].lower() not in scrapable_names]

    # Stats
    print(f"\n{'='*50}")
    print(f"Total unique companies: {len(all_companies)}")
    print(f"API-scrapable (Greenhouse/Lever/Ashby/etc): {len(scrapable)}")
    print(f"Custom ATS (Playwright): {len(custom)}")

    ats_counts = {}
    for c in scrapable:
        ats_counts[c["ats"]] = ats_counts.get(c["ats"], 0) + 1
    print(f"\nAPI ATS distribution:")
    for ats, count in sorted(ats_counts.items(), key=lambda x: -x[1]):
        print(f"  {ats}: {count}")

    output = {
        "scrapable": scrapable,
        "custom_ats": custom,
        "last_updated": time.strftime("%Y-%m-%d"),
    }

    with open("companies.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved companies.json")


if __name__ == "__main__":
    main()

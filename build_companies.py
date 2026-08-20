"""
Build companies.json from curated lists + multiple live GitHub repositories and scrapers.
Run locally or in GitHub Actions to refresh the company list.

Sources:
- Curated list: verified Europe, Turkey, Canada, Australia & New Zealand tech companies with visa sponsorship history
- shubheksha: https://github.com/shubheksha/companies-sponsoring-visas
- geshan: https://github.com/geshan/au-companies-providing-work-visa-sponsorship (Australia)
- SiaExplains: https://github.com/SiaExplains/visa-sponsorship-companies (Global/EU/Turkey/NZ)
- komeilmehranfar: https://github.com/komeilmehranfar/visa-sponsors-companies-for-iranians (Verified visa sponsors for Iranian candidates in DE, NL, UK, SE, TR, NZ, FR, ES, AT, IT, EE...)
- amol-can: https://github.com/amol-can/eu-visa-sponsoring-companies
- sponsorstats: https://www.sponsorstats.com — scraped when online (filtered for allowed regions)

RULES:
- ONLY Europe, Turkey, Canada, Australia, and New Zealand companies.
- EXCLUDE US-only, Asian (except Turkey), African, South American companies.
"""
import re
import json
import time
import requests

# ------------------------------------------------------------------ #
#  Allowed Regions & Country Keywords
# ------------------------------------------------------------------ #
ALLOWED_KEYWORDS = {
    # Europe
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
    # Turkey
    "turkey", "tr", "türkiye", "turkiye", "istanbul", "ankara", "izmir",
    # Canada
    "canada", "ca", "toronto", "vancouver", "montreal", "ottawa", "calgary", "waterloo",
    # Australia
    "australia", "au", "sydney", "melbourne", "brisbane", "perth", "adelaide",
    # New Zealand
    "new zealand", "nz", "auckland", "wellington", "christchurch",
    # Generic Europe
    "europe", "eu", "european union", "nordics", "baltics"
}

EXCLUDED_KEYWORDS = {
    "united states", "usa", "us", "india", "china", "japan", "singapore",
    "brazil", "nigeria", "south africa", "egypt", "vietnam", "indonesia",
    "philippines", "hong kong", "taiwan", "korea", "malaysia", "thailand",
    "mexico", "colombia", "argentina", "chile", "pakistan", "bangladesh"
}

def is_allowed_region(text: str) -> bool:
    """All regions allowed — country filter removed per 2025-08 update.

    Previously restricted to Europe, Turkey, Canada, Australia, and New Zealand.
    Now returns True for all regions to maximize job discovery. Use the
    freshness filter and Gemini classifier for quality control instead.
    """
    return True


# ------------------------------------------------------------------ #
#  ATS URL patterns
# ------------------------------------------------------------------ #
ATS_PATTERNS = {
    "greenhouse":      r"boards\.greenhouse\.io/([\w\-]+)",
    "lever":           r"jobs\.lever\.co/([\w\-]+)",
    "ashby":           r"(?:jobs\.)?ashbyhq\.com/([\w\-]+)",
    "smartrecruiters": r"careers\.smartrecruiters\.com/([\w\-]+)",
    "personio":        r"([\w\-]+)\.(?:jobs\.)?personio\.de",
    "workable":        r"(?:apply\.)?workable\.com/([\w\-]+)|([\w\-]+)\.workable\.com",
    "workday":         r"mywd\.jobs|wd\d?\.myworkdaysite|workday\.com",
}

BLACKLISTED_DOMAINS = {
    "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
    "jooble.org", "monster.com", "talent.com", "dice.com", "simplyhired.com",
    "remotive.com", "weworkremotely.com", "wellfound.com", "angel.co",
    "jobrapido.com", "neuvoo.com", "careerbuilder.com", "stepstone.de",
    "totaljobs.com", "reed.co.uk", "cv-library.co.uk", "adzuna.com",
}

def classify_ats(url: str):
    if not url:
        return "unknown", None
    for ats, pattern in ATS_PATTERNS.items():
        m = re.search(pattern, url, re.IGNORECASE)
        if m:
            groups = [g for g in m.groups() if g]
            slug = groups[0] if groups and ats != "workday" else None
            return ats, slug
    # If URL is from a blacklisted domain, do not treat as custom career page
    u_lower = url.lower()
    for b in BLACKLISTED_DOMAINS:
        if b in u_lower:
            return "unknown", None
    return "custom", None


# ------------------------------------------------------------------ #
#  CURATED: verified companies in allowed regions — (name, ats, slug, source)
# ------------------------------------------------------------------ #
CURATED = [
    # ================================================================
    # GLOBAL TECH — strong EU/CA/AU/NZ presence & visa sponsorship
    # ================================================================
    ("Stripe",           "greenhouse", "stripe",       "global_tech"),
    ("Shopify",          "greenhouse", "shopify",      "global_tech"),
    ("Spotify",          "greenhouse", "spotify",      "global_tech"),
    ("Klarna",           "lever",      "klarna",       "global_tech"),
    ("Zalando",          "greenhouse", "zalando",      "global_tech"),
    ("Delivery Hero",    "greenhouse", "deliveryhero", "global_tech"),
    ("Datadog",          "greenhouse", "datadog",      "global_tech"),
    ("Revolut",          "lever",      "revolut",      "global_tech"),
    ("Intercom",         "lever",      "intercom",     "global_tech"),
    ("HelloFresh",       "greenhouse", "hellofresh",   "global_tech"),
    ("Monzo",            "greenhouse", "monzo",        "global_tech"),
    ("Deliveroo",        "greenhouse", "deliveroo",    "global_tech"),
    ("GoCardless",       "greenhouse", "gocardless",   "global_tech"),
    ("Adyen",            "greenhouse", "adyen",        "global_tech"),
    ("Wise",             "greenhouse", "wise",         "global_tech"),
    ("GitLab",           "greenhouse", "gitlab",       "global_tech"),
    ("Cloudflare",       "greenhouse", "cloudflare",   "global_tech"),
    ("Databricks",       "greenhouse", "databricks",   "global_tech"),
    ("Elastic",          "greenhouse", "elastic",      "global_tech"),
    ("Grafana Labs",     "greenhouse", "grafanalabs",  "global_tech"),
    ("HashiCorp",        "greenhouse", "hashicorp",    "global_tech"),
    ("Weights & Biases", "greenhouse", "wandb",        "global_tech"),
    ("Hugging Face",     "greenhouse", "huggingface",  "global_tech"),
    ("Mistral AI",       "greenhouse", "mistralai",    "global_tech"),
    ("Snyk",             "lever",      "snyk",         "global_tech"),
    ("PostHog",          "lever",      "posthog",      "global_tech"),
    ("Celonis",          "greenhouse", "celonis",      "global_tech"),
    ("SAP SE",           "greenhouse", "sap",          "global_tech"),
    ("Backbase",         "greenhouse", "backbase",     "global_tech"),
    ("ING",              "greenhouse", "ing",          "global_tech"),
    ("MongoDB",          "greenhouse", "mongodb",      "global_tech"),
    ("GitHub",           "greenhouse", "github",       "global_tech"),
    ("Unity",            "greenhouse", "unity",        "global_tech"),
    ("Automattic",       "greenhouse", "automattic",   "global_tech"),
    ("Canonical",        "greenhouse", "canonical",    "global_tech"),
    ("Fastly",           "greenhouse", "fastly",       "global_tech"),
    ("Zendesk",          "greenhouse", "zendesk",      "global_tech"),
    ("PagerDuty",        "greenhouse", "pagerduty",    "global_tech"),

    # ================================================================
    # UNITED KINGDOM
    # ================================================================
    ("Checkout.com",      "greenhouse", "checkoutcom",     "europe_uk"),
    ("Multiverse",        "lever",      "multiverse",      "europe_uk"),
    ("Thought Machine",   "greenhouse", "thoughtmachine",  "europe_uk"),
    ("Marshmallow",       "greenhouse", "marshmallow",     "europe_uk"),
    ("Skyscanner",        "greenhouse", "skyscanner",      "europe_uk"),
    ("Tractable",         "lever",      "tractable",       "europe_uk"),
    ("Onfido",            "lever",      "onfido",          "europe_uk"),
    ("ComplyAdvantage",   "greenhouse", "complyadvantage", "europe_uk"),
    ("Cleo",              "greenhouse", "cleomoney",       "europe_uk"),
    ("Funding Circle",    "greenhouse", "fundingcircle",   "europe_uk"),
    ("OakNorth",          "greenhouse", "oaknorth",        "europe_uk"),
    ("Starling Bank",     "greenhouse", "starlingbank",    "europe_uk"),
    ("Paysafe",           "greenhouse", "paysafe",         "europe_uk"),
    ("Zopa",              "greenhouse", "zopa",            "europe_uk"),
    ("Truelayer",         "lever",      "truelayer",       "europe_uk"),
    ("Paddle",            "lever",      "paddle",          "europe_uk"),
    ("Featurespace",      "greenhouse", "featurespace",    "europe_uk"),
    ("Faculty",           "lever",      "faculty",         "europe_uk"),
    ("Improbable",        "greenhouse", "improbable",      "europe_uk"),
    ("Tessian",           "greenhouse", "tessian",         "europe_uk"),
    ("Motorway",          "greenhouse", "motorway",        "europe_uk"),
    ("Depop",             "greenhouse", "depop",           "europe_uk"),
    ("Wayve",             "greenhouse", "wayve",           "europe_uk"),
    ("Griffin",           "lever",      "griffin",         "europe_uk"),
    ("Kroo Bank",         "lever",      "kroo",            "europe_uk"),
    ("Attest",            "lever",      "attest",          "europe_uk"),
    ("Permutive",         "greenhouse", "permutive",       "europe_uk"),
    ("Elvie",             "greenhouse", "elvie",           "europe_uk"),
    ("Dojo",              "greenhouse", "dojo",            "europe_uk"),
    ("Cazoo",             "greenhouse", "cazoo",           "europe_uk"),

    # ================================================================
    # GERMANY
    # ================================================================
    ("N26",              "greenhouse", "n26",             "europe_de"),
    ("Personio",         "greenhouse", "personio",        "europe_de"),
    ("Auto1 Group",      "greenhouse", "auto1group",      "europe_de"),
    ("About You",        "greenhouse", "aboutyou",        "europe_de"),
    ("FlixBus",          "greenhouse", "flixbus",         "europe_de"),
    ("Adjust",           "greenhouse", "adjust",          "europe_de"),
    ("SumUp",            "greenhouse", "sumup",           "europe_de"),
    ("Trade Republic",   "greenhouse", "traderepublic",   "europe_de"),
    ("Scalable Capital", "greenhouse", "scalablecapital", "europe_de"),
    ("Taxdoo",           "greenhouse", "taxdoo",          "europe_de"),
    ("Contentful",       "greenhouse", "contentful",      "europe_de"),
    ("GetYourGuide",     "greenhouse", "getyourguide",    "europe_de"),
    ("Wefox",            "greenhouse", "wefox",           "europe_de"),
    ("HomeToGo",         "lever",      "hometogo",        "europe_de"),
    ("Spryker",          "lever",      "spryker",         "europe_de"),
    ("Chrono24",         "greenhouse", "chrono24",        "europe_de"),
    ("Ecosia",           "greenhouse", "ecosia",          "europe_de"),
    ("Mambu",            "greenhouse", "mambu",           "europe_de"),
    ("Quantco",          "lever",      "quantco",         "europe_de"),
    ("Riskified",        "greenhouse", "riskified",       "europe_de"),
    ("Solarisbank",      "greenhouse", "solarisbank",     "europe_de"),
    ("Statista",         "greenhouse", "statista",        "europe_de"),
    ("Vay",              "greenhouse", "vay",             "europe_de"),
    ("Zenjob",           "greenhouse", "zenjob",          "europe_de"),
    ("Finleap",          "greenhouse", "finleap",         "europe_de"),
    ("Idealo",           "greenhouse", "idealointernet",  "europe_de"),
    ("Scout24",          "greenhouse", "scout24",         "europe_de"),
    ("Tourlane",         "lever",      "tourlane",        "europe_de"),

    # ================================================================
    # NETHERLANDS
    # ================================================================
    ("Booking.com",         "greenhouse", "bookingcom",     "europe_nl"),
    ("ASML",                "greenhouse", "asml",           "europe_nl"),
    ("Mollie",              "greenhouse", "mollie",         "europe_nl"),
    ("Catawiki",            "greenhouse", "catawiki",       "europe_nl"),
    ("TomTom",              "greenhouse", "tomtom",         "europe_nl"),
    ("Sendcloud",           "greenhouse", "sendcloud",      "europe_nl"),
    ("Picnic Technologies", "greenhouse", "picnic",         "europe_nl"),
    ("WeTransfer",          "greenhouse", "wetransfer",     "europe_nl"),
    ("Coolblue",            "greenhouse", "coolblue",       "europe_nl"),
    ("Framer",              "greenhouse", "framer",         "europe_nl"),
    ("Productboard",        "greenhouse", "productboard",   "europe_nl"),
    ("Templafy",            "greenhouse", "templafy",       "europe_nl"),
    ("Paysend",             "greenhouse", "paysend",        "europe_nl"),
    ("Swapfiets",           "lever",      "swapfiets",      "europe_nl"),
    ("Lightyear",           "lever",      "lightyear",      "europe_nl"),

    # ================================================================
    # SWEDEN & NORDICS
    # ================================================================
    ("King",             "greenhouse", "king",            "europe_se"),
    ("Truecaller",       "greenhouse", "truecaller",      "europe_se"),
    ("Epidemic Sound",   "greenhouse", "epidemicsound",   "europe_se"),
    ("EasyPark",         "greenhouse", "easypark",        "europe_se"),
    ("Voi Technology",   "greenhouse", "voi",             "europe_se"),
    ("Sinch",            "greenhouse", "sinch",           "europe_se"),
    ("Tink",             "greenhouse", "tink",            "europe_se"),
    ("DICE",             "greenhouse", "dice",            "europe_se"),
    ("Wolt",             "greenhouse", "wolt",            "europe_nordics"),
    ("Aiven",            "greenhouse", "aiven",           "europe_nordics"),
    ("Supermetrics",     "greenhouse", "supermetrics",    "europe_nordics"),
    ("Smartly.io",       "greenhouse", "smartly",         "europe_nordics"),
    ("Visma",            "greenhouse", "visma",           "europe_nordics"),

    # ================================================================
    # TURKEY
    # ================================================================
    ("Trendyol",         "greenhouse", "trendyol",        "turkey"),
    ("Insider",          "greenhouse", "useinsider",      "turkey"),
    ("Getir",            "greenhouse", "getir",           "turkey"),
    ("Peak Games",       "greenhouse", "peakgames",       "turkey"),
    ("Dream Games",      "greenhouse", "dreamgames",      "turkey"),
    ("Papara",           "greenhouse", "papara",          "turkey"),
    ("iyzico",           "greenhouse", "iyzico",          "turkey"),
    ("Hepsiburada",      "greenhouse", "hepsiburada",     "turkey"),
    ("Enuygun",          "greenhouse", "enuygun",         "turkey"),

    # ================================================================
    # CANADA
    # ================================================================
    ("Wealthsimple",    "greenhouse", "wealthsimple",    "canada"),
    ("Cohere",          "greenhouse", "cohere",          "canada"),
    ("1Password",       "lever",      "1password",       "canada"),
    ("Hootsuite",       "greenhouse", "hootsuite",       "canada"),
    ("Clio",            "greenhouse", "clio",            "canada"),
    ("Wave",            "greenhouse", "wave",            "canada"),
    ("Unbounce",        "greenhouse", "unbounce",        "canada"),
    ("Bench",           "greenhouse", "bench",           "canada"),
    ("Coveo",           "greenhouse", "coveo",           "canada"),
    ("D2L",             "greenhouse", "d2l",             "canada"),
    ("FreshBooks",      "greenhouse", "freshbooks",      "canada"),
    ("League",          "greenhouse", "league",          "canada"),
    ("Lightspeed",      "greenhouse", "lightspeedpos",   "canada"),
    ("Mattermost",      "lever",      "mattermost",      "canada"),
    ("Nuvei",           "greenhouse", "nuvei",           "canada"),
    ("Procore",         "greenhouse", "procore",         "canada"),
    ("Relay Financial", "greenhouse", "relayfinancial",  "canada"),
    ("Ritual",          "greenhouse", "ritual",          "canada"),
    ("Snapcommerce",    "greenhouse", "snapcommerce",    "canada"),
    ("Top Hat",         "greenhouse", "tophat",          "canada"),
    ("Tulip Retail",    "greenhouse", "tulip",           "canada"),
    ("Vendasta",        "greenhouse", "vendasta",        "canada"),
    ("Vidyard",         "greenhouse", "vidyard",         "canada"),
    ("Vena Solutions",  "greenhouse", "venasolutions",   "canada"),
    ("Versapay",        "greenhouse", "versapay",        "canada"),
    ("Xanadu",          "lever",      "xanadu",          "canada"),
    ("SSENSE",          "greenhouse", "ssense",          "canada"),
    ("Trulioo",         "greenhouse", "trulioo",         "canada"),
    ("Jobber",          "greenhouse", "jobber",          "canada"),
    ("Klue",            "greenhouse", "klue",            "canada"),
    ("Procurify",       "greenhouse", "procurify",       "canada"),

    # ================================================================
    # AUSTRALIA & NEW ZEALAND
    # ================================================================
    ("Canva",           "greenhouse", "canva",           "australia"),
    ("Atlassian",       "greenhouse", "atlassian",       "australia"),
    ("AirTasker",       "greenhouse", "airtasker",       "australia"),
    ("BigCommerce",     "greenhouse", "bigcommerce",     "australia"),
    ("Brighte",         "lever",      "brighte",         "australia"),
    ("ClipChamp",       "greenhouse", "clipchamp",       "australia"),
    ("Deputy",          "greenhouse", "deputy",          "australia"),
    ("Domain Group",    "greenhouse", "domaingroup",     "australia"),
    ("Lendi",           "smartrecruiters", "LendiGroup1", "australia"),
    ("SafetyCulture",   "lever",      "safetyculture",   "australia"),
    ("Rokt",            "greenhouse", "rokt",            "australia"),
    ("Optiver",         "greenhouse", "optiver",         "australia"),
    ("Propeller",       "greenhouse", "propelleraero",   "australia"),
    ("Harrison.Ai",     "lever",      "harrisonai",      "australia"),
    ("HealthEngine",    "greenhouse", "healthengine",    "australia"),
    ("Tyro",            "greenhouse", "tyro",            "australia"),
    ("Expert360",       "greenhouse", "expert360",       "australia"),
    ("Linktree",        "ashby",      "linktree",        "australia"),
    ("SquareUp AU",     "greenhouse", "block",           "australia"),
    ("Qwilr",           "lever",      "qwilr",           "australia"),
    ("Finder",          "greenhouse", "finder",          "australia"),
    ("REA Group",       "lever",      "reagroup",        "australia"),
    ("Xero",            "greenhouse", "xero",            "new_zealand"),
    ("Pushpay",         "greenhouse", "pushpay",         "new_zealand"),
    ("Rocket Lab",      "lever",      "rocketlab",       "new_zealand"),
    ("Trade Me",        "greenhouse", "trademe",         "new_zealand"),
]


# ------------------------------------------------------------------ #
#  Parsers for Live GitHub Repos
# ------------------------------------------------------------------ #
def parse_shubheksha():
    print("Fetching shubheksha repo...")
    url = "https://raw.githubusercontent.com/shubheksha/companies-sponsoring-visas/master/README.md"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
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
        location = parts[1].strip() if len(parts) > 1 else ""
        careers = parts[3].strip() if len(parts) > 3 else ""
        if not name or name.lower().startswith("name"):
            continue
        if not is_allowed_region(location):
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
    print(f"  Found {len(companies)} matching companies in shubheksha")
    return companies


def parse_geshan_au():
    print("Fetching geshan AU repo...")
    url = "https://raw.githubusercontent.com/geshan/au-companies-providing-work-visa-sponsorship/master/README.md"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  Error: {e}")
        return []

    companies = []
    for line in r.text.splitlines():
        m = re.match(r"^\s*-\s*\[([^\]]+)\]\((https?://[^\)]+)\)", line)
        if m:
            name, url = m.group(1), m.group(2)
            ats, slug = classify_ats(url)
            companies.append({
                "name": name,
                "careers_url": url,
                "ats": ats,
                "slug": slug,
                "source": "geshan_au",
            })
    print(f"  Found {len(companies)} companies in geshan_au")
    return companies


def parse_siaexplains():
    print("Fetching SiaExplains repo countries...")
    sia_countries = [
        "Denmark.json", "austria.json", "belgium.json", "england.json", "finland.json",
        "france.json", "germany.json", "ireland.json", "italy.json", "netherlands.json",
        "new-zealand.json", "norway.json", "spain.json", "sweden.json", "turkey.json"
    ]
    sia_base = "https://raw.githubusercontent.com/SiaExplains/visa-sponsorship-companies/main/countries/"
    companies = []
    for c_file in sia_countries:
        try:
            r = requests.get(sia_base + c_file, timeout=10)
            if r.status_code == 200:
                for item in r.json():
                    name = item.get("name")
                    url = item.get("careers") or item.get("linkedin") or item.get("website") or ""
                    loc = item.get("city", "") + " " + item.get("country", "")
                    if name and is_allowed_region(loc):
                        ats, slug = classify_ats(url)
                        companies.append({
                            "name": name,
                            "careers_url": url,
                            "ats": ats,
                            "slug": slug,
                            "source": "siaexplains",
                        })
        except Exception as e:
            print(f"  Error fetching {c_file}: {e}")
    print(f"  Found {len(companies)} companies in SiaExplains")
    return companies


def parse_komeilmehranfar():
    print("Fetching komeilmehranfar repo (visa sponsors for Iranian candidates)...")
    url = "https://raw.githubusercontent.com/komeilmehranfar/visa-sponsors-companies-for-iranians/main/data/companies.json"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json().get("companies", {})
    except Exception as e:
        print(f"  Error: {e}")
        return []

    companies = []
    for country, items in data.items():
        if is_allowed_region(country):
            for item in items:
                name = item.get("name")
                url = item.get("website") or item.get("linkedin") or ""
                if name:
                    ats, slug = classify_ats(url)
                    companies.append({
                        "name": name,
                        "careers_url": url,
                        "ats": ats,
                        "slug": slug,
                        "source": "komeilmehranfar",
                    })
    print(f"  Found {len(companies)} companies in komeilmehranfar")
    return companies


def parse_amol_can_eu():
    print("Fetching amol-can EU repo...")
    url = "https://raw.githubusercontent.com/amol-can/eu-visa-sponsoring-companies/main/README.md"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  Error: {e}")
        return []

    companies = []
    for line in r.text.splitlines():
        if line.startswith("|") and not line.startswith("|---") and not "Careers page" in line:
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 5:
                name = parts[0]
                loc = parts[1]
                url_cell = parts[4]
                m = re.search(r"\[.*?\]\((https?://[^\)]+)\)", url_cell)
                url = m.group(1) if m else url_cell
                if name and name.lower() != "name" and is_allowed_region(loc):
                    ats, slug = classify_ats(url)
                    companies.append({
                        "name": name,
                        "careers_url": url,
                        "ats": ats,
                        "slug": slug,
                        "source": "amol_can",
                    })
    print(f"  Found {len(companies)} companies in amol_can")
    return companies


# ------------------------------------------------------------------ #
#  Deduplication
# ------------------------------------------------------------------ #
def deduplicate(companies: list) -> list:
    priority = {
        "greenhouse": 5, "lever": 5, "ashby": 5,
        "smartrecruiters": 5, "personio": 5,
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


# ------------------------------------------------------------------ #
#  Main Execution
# ------------------------------------------------------------------ #
def main():
    all_companies = []

    # 1. Curated List
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

    # 2. Fetch live remote sources
    time.sleep(0.2)
    all_companies.extend(parse_shubheksha())
    time.sleep(0.2)
    all_companies.extend(parse_geshan_au())
    time.sleep(0.2)
    all_companies.extend(parse_siaexplains())
    time.sleep(0.2)
    all_companies.extend(parse_komeilmehranfar())
    time.sleep(0.2)
    all_companies.extend(parse_amol_can_eu())

    # 3. Deduplicate
    all_companies = deduplicate(all_companies)

    # 4. Split by scrapable API ATS vs Custom ATS
    API_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "personio"}
    scrapable = [c for c in all_companies if c.get("ats") in API_ATS]
    custom = [
        c for c in all_companies
        if c.get("ats") not in API_ATS and c.get("careers_url")
        and not any(b in c.get("careers_url", "").lower() for b in BLACKLISTED_DOMAINS)
    ]
    scrapable_names = {c["name"].lower() for c in scrapable}
    custom = [c for c in custom if c["name"].lower() not in scrapable_names]

    print(f"\n{'='*60}")
    print(f"Total unique companies (EU/CA/AU/NZ/TR): {len(all_companies)}")
    print(f"API-scrapable (Greenhouse/Lever/Ashby/etc): {len(scrapable)}")
    print(f"Custom ATS (needs Playwright / direct fetch): {len(custom)}")
    
    ats_counts: dict[str, int] = {}
    for c in scrapable:
        ats_counts[c["ats"]] = ats_counts.get(c["ats"], 0) + 1
    print("\nAPI ATS breakdown:")
    for ats, count in sorted(ats_counts.items(), key=lambda x: -x[1]):
        print(f"  {ats}: {count}")

    output = {
        "scrapable": scrapable,
        "custom_ats": custom,
        "last_updated": time.strftime("%Y-%m-%d"),
    }
    with open("companies.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved companies.json ✓")


if __name__ == "__main__":
    main()

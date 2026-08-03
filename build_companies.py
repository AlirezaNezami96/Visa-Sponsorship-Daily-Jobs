"""
Build companies.json from curated lists + GitHub repos.
Run locally or in GitHub Actions to refresh the company list.

Sources:
- Curated list: manually verified EU/Canada companies that sponsor work visas
- shubheksha: https://github.com/shubheksha/companies-sponsoring-visas (EU/UK entries)
- sponsorstats: https://www.sponsorstats.com — scraped when online, EU/Canada filtered

RULES: Only Europe and Canada companies. No US-only, no Australia.
"""
import re
import json
import time
import requests

# ------------------------------------------------------------------ #
#  Remote repos to pull from
# ------------------------------------------------------------------ #
REPOS = {
    "shubheksha": "https://raw.githubusercontent.com/shubheksha/companies-sponsoring-visas/master/README.md",
}

# sponsorstats.com — iterate all 100 pages when the site is reachable
SPONSORSTATS_BASE = (
    "https://www.sponsorstats.com/sponsorlist/"
    "?soc=Software%20Developers&experience=senior&page={page}"
)
SPONSORSTATS_TOTAL_PAGES = 100

# Country keywords we accept when filtering sponsorstats / generic repos
EU_CANADA_COUNTRIES = {
    "united kingdom", "uk", "gb", "england", "scotland", "wales",
    "germany", "de", "deutschland",
    "netherlands", "nl", "holland",
    "sweden", "se",
    "denmark", "dk",
    "finland", "fi",
    "norway", "no",
    "ireland", "ie",
    "france", "fr",
    "spain", "es",
    "portugal", "pt",
    "italy", "it",
    "belgium", "be",
    "austria", "at",
    "switzerland", "ch",
    "poland", "pl",
    "czech republic", "cz", "czechia",
    "hungary", "hu",
    "romania", "ro",
    "estonia", "ee",
    "latvia", "lv",
    "lithuania", "lt",
    "slovakia", "sk",
    "slovenia", "si",
    "croatia", "hr",
    "bulgaria", "bg",
    "greece", "gr",
    "luxembourg", "lu",
    "malta", "mt",
    "cyprus", "cy",
    "canada", "ca",
    "europe", "eu", "european union",
}

# ------------------------------------------------------------------ #
#  ATS URL patterns
# ------------------------------------------------------------------ #
ATS_PATTERNS = {
    "greenhouse":      r"boards\.greenhouse\.io/([\w\-]+)/?",
    "lever":           r"jobs\.lever\.co/([\w\-]+)/?",
    "ashby":           r"ashbyhq\.com/([\w\-]+)/?",
    "smartrecruiters": r"careers\.smartrecruiters\.com/([\w\-]+)/?",
    "personio":        r"([\w\-]+)\.jobs\.personio\.de",
    "workday":         r"mywd\.jobs|wd\d?\.myworkdaysite|workday\.com",
}

# ------------------------------------------------------------------ #
#  CURATED: verified EU/Canada companies — (name, ats, slug, source)
#  *** Europe and Canada ONLY ***
# ------------------------------------------------------------------ #
CURATED = [

    # ================================================================
    # GLOBAL TECH — strong EU/Canada presence, routinely sponsor visas
    # ================================================================
    ("Stripe",           "greenhouse", "stripe",       "global_eu"),
    ("Shopify",          "greenhouse", "shopify",      "global_eu"),
    ("Spotify",          "greenhouse", "spotify",      "global_eu"),
    ("Klarna",           "lever",      "klarna",       "global_eu"),
    ("Zalando",          "greenhouse", "zalando",      "global_eu"),
    ("Delivery Hero",    "greenhouse", "deliveryhero", "global_eu"),
    ("Datadog",          "greenhouse", "datadog",      "global_eu"),
    ("Revolut",          "lever",      "revolut",      "global_eu"),
    ("Intercom",         "lever",      "intercom",     "global_eu"),
    ("HelloFresh",       "greenhouse", "hellofresh",   "global_eu"),
    ("Monzo",            "greenhouse", "monzo",        "global_eu"),
    ("Deliveroo",        "greenhouse", "deliveroo",    "global_eu"),
    ("GoCardless",       "greenhouse", "gocardless",   "global_eu"),
    ("Adyen",            "greenhouse", "adyen",        "global_eu"),
    ("Wise",             "greenhouse", "wise",         "global_eu"),
    ("GitLab",           "greenhouse", "gitlab",       "global_eu"),
    ("Cloudflare",       "greenhouse", "cloudflare",   "global_eu"),
    ("Databricks",       "greenhouse", "databricks",   "global_eu"),
    ("Elastic",          "greenhouse", "elastic",      "global_eu"),
    ("Grafana Labs",     "greenhouse", "grafanalabs",  "global_eu"),
    ("HashiCorp",        "greenhouse", "hashicorp",    "global_eu"),
    ("Weights & Biases", "greenhouse", "wandb",        "global_eu"),
    ("Hugging Face",     "greenhouse", "huggingface",  "global_eu"),
    ("Mistral AI",       "greenhouse", "mistralai",    "global_eu"),
    ("Snyk",             "lever",      "snyk",         "global_eu"),
    ("PostHog",          "lever",      "posthog",      "global_eu"),
    ("Celonis",          "greenhouse", "celonis",      "global_eu"),
    ("SAP SE",           "greenhouse", "sap",          "global_eu"),
    ("Backbase",         "greenhouse", "backbase",     "global_eu"),
    ("ING",              "greenhouse", "ing",          "global_eu"),
    ("MongoDB",          "greenhouse", "mongodb",      "global_eu"),
    ("GitHub",           "greenhouse", "github",       "global_eu"),
    ("Unity",            "greenhouse", "unity",        "global_eu"),
    ("Automattic",       "greenhouse", "automattic",   "global_eu"),
    ("Canonical",        "greenhouse", "canonical",    "global_eu"),
    ("Fastly",           "greenhouse", "fastly",       "global_eu"),
    ("Zendesk",          "greenhouse", "zendesk",      "global_eu"),
    ("PagerDuty",        "greenhouse", "pagerduty",    "global_eu"),

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
    ("Causal",            "lever",      "causal",          "europe_uk"),
    ("Bloom & Wild",      "greenhouse", "bloomwild",       "europe_uk"),
    ("Cuvva",             "lever",      "cuvva",           "europe_uk"),
    ("MessageBird",       "greenhouse", "messagebird",     "europe_uk"),
    ("Pendo",             "greenhouse", "pendoio",         "europe_uk"),
    ("Amplience",         "greenhouse", "amplience",       "europe_uk"),
    ("Wayflyer",          "greenhouse", "wayflyer",        "europe_uk"),
    ("Pollen",            "greenhouse", "pollen",          "europe_uk"),
    ("Samsara",           "greenhouse", "samsara",         "europe_uk"),
    ("Babylon Health",    "greenhouse", "babylonhealth",   "europe_uk"),
    ("Plaid",             "greenhouse", "plaid",           "europe_uk"),
    ("Uncapped",          "lever",      "uncapped",        "europe_uk"),
    ("Nested",            "lever",      "nested",          "europe_uk"),

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
    ("Infarm",           "greenhouse", "infarm",          "europe_de"),
    ("Signavio",         "greenhouse", "signavio",        "europe_de"),
    ("LIQID",            "lever",      "liqid",           "europe_de"),
    ("Moonfare",         "lever",      "moonfare",        "europe_de"),
    ("Thermondo",        "lever",      "thermondo",       "europe_de"),
    ("Relayr",           "lever",      "relayr",          "europe_de"),
    ("Studio71",         "lever",      "studio71",        "europe_de"),

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
    ("Fuse",                "greenhouse", "fuse",           "europe_nl"),
    ("Seenit",              "lever",      "seenit",         "europe_nl"),
    ("IMCD",                "greenhouse", "imcd",           "europe_nl"),
    ("Vistaprint",          "greenhouse", "vistaprint",     "europe_nl"),
    ("Takeaway.com",        "greenhouse", "takeawaycom",    "europe_nl"),

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
    ("Bambora",          "lever",      "bambora",         "europe_se"),
    ("Yepstr",           "greenhouse", "yepstr",          "europe_se"),
    ("Zimpler",          "lever",      "zimpler",         "europe_se"),
    # Finland / Denmark / Norway
    ("Wolt",             "greenhouse", "wolt",            "europe_nordics"),
    ("Aiven",            "greenhouse", "aiven",           "europe_nordics"),
    ("Supermetrics",     "greenhouse", "supermetrics",    "europe_nordics"),
    ("Smartly.io",       "greenhouse", "smartly",         "europe_nordics"),
    ("Visma",            "greenhouse", "visma",           "europe_nordics"),
    ("Futurice",         "greenhouse", "futurice",        "europe_nordics"),
    ("Reaktor",          "lever",      "reaktor",         "europe_nordics"),

    # ================================================================
    # IRELAND (Dublin tech hub)
    # ================================================================
    ("HubSpot",    "greenhouse", "hubspot",    "europe_ie"),
    ("Workday",    "greenhouse", "workday",    "europe_ie"),
    ("Salesforce", "greenhouse", "salesforce", "europe_ie"),
    ("Asana",      "greenhouse", "asana",      "europe_ie"),
    ("Squarespace","greenhouse", "squarespace","europe_ie"),
    ("Slack",      "greenhouse", "slack",      "europe_ie"),
    ("Flipdish",   "greenhouse", "flipdish",   "europe_ie"),
    ("Workhuman",  "greenhouse", "workhuman",  "europe_ie"),
    ("Phorest",    "greenhouse", "phorest",    "europe_ie"),
    ("Teamwork",   "lever",      "teamwork",   "europe_ie"),

    # ================================================================
    # FRANCE
    # ================================================================
    ("Ledger",            "lever",  "ledger",          "europe_fr"),
    ("Doctolib",          "lever",  "doctolib",         "europe_fr"),
    ("Contentsquare",     "lever",  "contentsquare",    "europe_fr"),
    ("BlaBlaCar",         "lever",  "blablacar",        "europe_fr"),
    ("Deezer",            "greenhouse", "deezer",        "europe_fr"),
    ("Alan",              "lever",  "alan",             "europe_fr"),
    ("Swile",             "lever",  "swile",            "europe_fr"),
    ("Qonto",             "lever",  "qonto",            "europe_fr"),
    ("Back Market",       "lever",  "backmarket",       "europe_fr"),
    ("Luko",              "lever",  "luko",             "europe_fr"),
    ("Dataiku",           "greenhouse", "dataiku",       "europe_fr"),
    ("Exotec",            "greenhouse", "exotec",        "europe_fr"),
    ("Inato",             "lever",  "inato",            "europe_fr"),
    ("ManoMano",          "lever",  "manomano",         "europe_fr"),
    ("Meero",             "lever",  "meero",            "europe_fr"),
    ("Mirakl",            "lever",  "mirakl",           "europe_fr"),
    ("Shift Technology",  "lever",  "shifttechnology",  "europe_fr"),
    ("Spendesk",          "lever",  "spendesk",         "europe_fr"),

    # ================================================================
    # SPAIN
    # ================================================================
    ("Glovo",       "lever",      "glovoapp",  "europe_es"),
    ("Cabify",      "greenhouse", "cabify",    "europe_es"),
    ("Wallapop",    "greenhouse", "wallapop",  "europe_es"),
    ("Typeform",    "greenhouse", "typeform",  "europe_es"),
    ("Factorial",   "greenhouse", "factorial", "europe_es"),
    ("Travelperk",  "greenhouse", "travelperk","europe_es"),
    ("Lingokids",   "lever",      "lingokids", "europe_es"),
    ("Packlink",    "lever",      "packlink",  "europe_es"),
    ("Housfy",      "lever",      "housfy",    "europe_es"),
    ("Signifyd",    "greenhouse", "signifyd",  "europe_es"),

    # ================================================================
    # BALTICS & EASTERN EUROPE
    # ================================================================
    # Estonia / Lithuania / Latvia
    ("Bolt",                 "greenhouse", "bolt",           "europe_ee"),
    ("Pipedrive",            "greenhouse", "pipedrive",      "europe_ee"),
    ("Starship Technologies","lever",      "starship",       "europe_ee"),
    ("Montonio",             "lever",      "montonio",       "europe_ee"),
    ("Skeleton Technologies","lever",      "skeletontech",   "europe_ee"),
    # Poland
    ("Allegro",     "greenhouse", "allegro",    "europe_pl"),
    ("Docplanner",  "greenhouse", "docplanner", "europe_pl"),
    ("Brainly",     "greenhouse", "brainly",    "europe_pl"),
    ("LiveChat",    "greenhouse", "livechat",   "europe_pl"),
    ("Booksy",      "greenhouse", "booksy",     "europe_pl"),
    ("Infermedica", "lever",      "infermedica","europe_pl"),
    ("Nethone",     "lever",      "nethone",    "europe_pl"),
    ("Netguru",     "greenhouse", "netguru",    "europe_pl"),
    ("EPAM Systems","greenhouse", "epamsystems","europe_pl"),

    # ================================================================
    # SWITZERLAND & AUSTRIA
    # ================================================================
    ("Scandit",      "lever",      "scandit",      "europe_ch"),
    ("Beekeeper",    "greenhouse", "beekeeper",    "europe_ch"),
    ("Yokoy",        "lever",      "yokoy",         "europe_ch"),
    ("Pricehubble",  "lever",      "pricehubble",  "europe_ch"),
    ("Frontify",     "greenhouse", "frontify",     "europe_ch"),
    ("GetSafe",      "lever",      "getsafe",      "europe_ch"),
    ("Moneyfarm",    "greenhouse", "moneyfarm",    "europe_ch"),

    # ================================================================
    # PORTUGAL
    # ================================================================
    ("Sword Health", "greenhouse", "swordhealth",  "europe_pt"),
    ("Feedzai",      "greenhouse", "feedzai",      "europe_pt"),
    ("OutSystems",   "greenhouse", "outsystems",   "europe_pt"),
    ("Unbabel",      "lever",      "unbabel",       "europe_pt"),
    ("Farfetch",     "greenhouse", "farfetch",     "europe_pt"),
    ("Rows",         "lever",      "rows",          "europe_pt"),
    ("Jungle AI",    "lever",      "jungleai",     "europe_pt"),
    ("Hostelworld",  "greenhouse", "hostelworld",  "europe_pt"),
    ("Uniplaces",    "lever",      "uniplaces",    "europe_pt"),

    # ================================================================
    # ITALY
    # ================================================================
    ("Musixmatch",          "greenhouse", "musixmatch",          "europe_it"),
    ("Prima Assicurazioni", "greenhouse", "primaassicurazioni",   "europe_it"),
    ("Satispay",            "greenhouse", "satispay",            "europe_it"),
    ("Scalapay",            "greenhouse", "scalapay",            "europe_it"),
    ("Bending Spoons",      "greenhouse", "bendingspoons",       "europe_it"),
    ("Soldo",               "greenhouse", "soldo",               "europe_it"),

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
    ("Avidbots",        "lever",      "avidbots",        "canada"),
    ("TouchBistro",     "greenhouse", "touchbistro",     "canada"),
    ("Humi",            "greenhouse", "humi",            "canada"),
    ("Carbon6",         "greenhouse", "carbon6",         "canada"),
    ("HiMama",          "greenhouse", "himama",          "canada"),
    ("AbCellera",       "greenhouse", "abcellera",       "canada"),
    ("Clearco",         "greenhouse", "clearco",         "canada"),
    ("BrainStation",    "greenhouse", "brainstation",    "canada"),
    ("Fiix",            "greenhouse", "fiixsoftware",    "canada"),
    ("Jane Software",   "greenhouse", "jane",            "canada"),
    ("Coconut Software","greenhouse", "coconutsoftware", "canada"),
    ("Tealbook",        "greenhouse", "tealbook",        "canada"),
    ("GreenShield",     "greenhouse", "greenshield",     "canada"),
    ("Mysa",            "lever",      "mysa",            "canada"),
    ("BuildDirect",     "lever",      "builddirect",     "canada"),
    ("Nicoya",          "lever",      "nicoya",          "canada"),
    ("Intellicheck",    "lever",      "intellicheck",    "canada"),
    ("Xanadu Quantum",  "lever",      "xanadu",          "canada"),
    ("Hyper Hippo",     "greenhouse", "hyperhippo",      "canada"),
    ("Pythian Group",   "lever",      "pythian",         "canada"),
]


# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #
def classify_ats(url: str):
    if not url:
        return "unknown", None
    for ats, pattern in ATS_PATTERNS.items():
        m = re.search(pattern, url, re.IGNORECASE)
        if m:
            slug = m.group(1) if ats != "workday" else None
            return ats, slug
    return "custom", None


def is_eu_canada(text: str) -> bool:
    """Return True if the text contains a recognised EU/Canada country keyword."""
    lower = text.lower()
    return any(kw in lower for kw in EU_CANADA_COUNTRIES)


# ------------------------------------------------------------------ #
#  Parsers
# ------------------------------------------------------------------ #
def parse_shubheksha():
    """Fetch and parse https://github.com/shubheksha/companies-sponsoring-visas.
    Only keeps rows whose location column mentions an EU/Canada country.
    """
    print("Fetching shubheksha repo...")
    try:
        r = requests.get(REPOS["shubheksha"], timeout=30)
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
        # Filter: only EU/Canada locations
        if not is_eu_canada(location):
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
    print(f"  Found {len(companies)} EU/Canada companies in shubheksha")
    return companies


def parse_sponsorstats():
    """Iterate all 100 pages of sponsorstats.com and return EU/Canada companies.

    sponsorstats.com lists companies that filed for work visas. The page
    structure uses JSON-LD or plain HTML cards. This parser handles both.

    Note: The site was offline as of 2026-08. The function will gracefully
    skip pages that time out or return errors, and log progress.
    """
    print(f"Scraping sponsorstats.com ({SPONSORSTATS_TOTAL_PAGES} pages) ...")
    companies = []
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (compatible; VisaJobBot/1.0; "
            "+https://github.com/AlirezaNezami96/Visa-Sponsorship-Daily-Jobs)"
        )
    })

    found_total = 0
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 3  # stop early if site is clearly down

    for page in range(1, SPONSORSTATS_TOTAL_PAGES + 1):
        url = SPONSORSTATS_BASE.format(page=page)
        try:
            resp = session.get(url, timeout=5)   # 5s — fail fast if site is down
            consecutive_failures = 0             # reset on success
            if resp.status_code == 404:
                print(f"  Page {page}: 404 — stopping pagination")
                break
            if resp.status_code != 200:
                print(f"  Page {page}: HTTP {resp.status_code} — skipping")
                time.sleep(0.5)
                continue
        except Exception as e:
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"  sponsorstats unreachable after {consecutive_failures} "
                      "consecutive failures — site may be down, skipping.")
                break
            print(f"  Page {page}: {e} — skipping")
            time.sleep(1)
            continue

        html = resp.text

        # Extract company cards via regex on the rendered HTML
        # Pattern: company name in <h3> and country in a nearby element
        card_pattern = re.compile(
            r'<h3[^>]*>.*?<span[^>]*>(.*?)</span>.*?</h3>'
            r'.*?(?:country|location)[^>]*>(.*?)<',
            re.IGNORECASE | re.DOTALL,
        )
        found_on_page = 0
        for m in card_pattern.finditer(html):
            name_raw = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            country_raw = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if not name_raw or not is_eu_canada(country_raw):
                continue
            # Try to find a careers link near this company
            link_m = re.search(
                r'href="(https?://(?:boards\.greenhouse\.io|jobs\.lever\.co|'
                r'ashbyhq\.com|careers\.smartrecruiters\.com)[^"]+)"',
                html[m.start():m.start() + 2000],
            )
            careers_url = link_m.group(1) if link_m else ""
            ats, slug = classify_ats(careers_url)
            companies.append({
                "name": name_raw,
                "careers_url": careers_url,
                "ats": ats,
                "slug": slug,
                "source": "sponsorstats",
            })
            found_on_page += 1

        found_total += found_on_page
        if page % 10 == 0 or found_on_page > 0:
            print(f"  Page {page}/{SPONSORSTATS_TOTAL_PAGES}: "
                  f"+{found_on_page} EU/Canada companies (total so far: {found_total})")
        time.sleep(0.4)   # polite crawl delay

    print(f"  sponsorstats total EU/Canada: {len(companies)}")
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
    result = []
    for co in companies:
        key = co["name"].lower().strip()
        if key in seen:
            existing = seen[key]
            if priority.get(existing["ats"], 0) < priority.get(co["ats"], 0):
                seen[key] = co
            continue
        seen[key] = co
        result.append(co)
    return result


# ------------------------------------------------------------------ #
#  Main
# ------------------------------------------------------------------ #
def main():
    all_companies = []

    # 1. Curated (highest priority — manually verified ATS slugs)
    print("Adding curated EU/Canada companies...")
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

    # 2. shubheksha — EU/Canada filtered
    time.sleep(0.3)
    all_companies.extend(parse_shubheksha())

    # 3. sponsorstats — iterate all 100 pages, EU/Canada filtered
    time.sleep(0.3)
    all_companies.extend(parse_sponsorstats())

    # Deduplicate
    all_companies = deduplicate(all_companies)

    # 4. Split by ATS type
    API_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "personio"}
    scrapable = [c for c in all_companies if c["ats"] in API_ATS]
    custom = [
        c for c in all_companies
        if c["ats"] not in API_ATS and c.get("careers_url")
    ]
    scrapable_names = {c["name"].lower() for c in scrapable}
    custom = [c for c in custom if c["name"].lower() not in scrapable_names]

    # Stats
    print(f"\n{'='*55}")
    print(f"Total unique companies (EU/Canada): {len(all_companies)}")
    print(f"API-scrapable (Greenhouse/Lever/Ashby/etc): {len(scrapable)}")
    print(f"Custom ATS (needs Playwright): {len(custom)}")
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
    print(f"\nSaved companies.json  ✓")


if __name__ == "__main__":
    main()

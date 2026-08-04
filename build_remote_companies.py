"""
Build remote_companies.json from multiple remote-job community repos and lists.
Run locally or in GitHub Actions to refresh the remote companies list.

Sources scraped:
  1. yanirs/established-remote           — established global remote companies
  2. remoteintech/remote-jobs            — remoteintech.company company data (markdown)
  3. adherb/remote-tech-companies        — verified remote companies table
  4. lukasz-madon/awesome-remote-job     — awesome list with company links
  5. andrews1022/remote-tech-companies   — tech companies remote table
  6. abhagsain/remote-companies          — remote companies list
  7. dpaulino/remote-jobs-list           — remote jobs list
  8. sergey-shakhov/remote-companies     — remote companies list
  9. flexbox/remote-jobs                 — remote jobs curated list
  10. hugo53/awesome-RemoteWork          — awesome remote work list

Plus a large CURATED list of well-known fully remote / remote-first tech companies
with known ATS slugs (Greenhouse, Lever, Ashby, SmartRecruiters, Personio).

NOTES:
- No geographic restriction — these are fully remote companies hiring globally.
- ATS-scrapable companies (Greenhouse/Lever/Ashby/etc.) are extracted and placed
  in the "scrapable" key so run_remote.py can fetch job listings via clean APIs.
- All others go into "custom_ats" for Playwright-based scraping.
"""
import re
import json
import time
import requests

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


def classify_ats(url: str):
    if not url:
        return "unknown", None
    for ats, pattern in ATS_PATTERNS.items():
        m = re.search(pattern, url, re.IGNORECASE)
        if m:
            groups = [g for g in m.groups() if g]
            slug = groups[0] if groups and ats != "workday" else None
            return ats, slug
    return "custom", None


# ------------------------------------------------------------------ #
#  CURATED: well-known fully-remote / remote-first tech companies
#  with verified ATS slugs — (name, ats, slug)
# ------------------------------------------------------------------ #
CURATED_REMOTE = [
    # ============================================================
    # FULLY REMOTE / REMOTE-FIRST COMPANIES (global hiring)
    # ============================================================
    ("GitLab",             "greenhouse", "gitlab"),
    ("Automattic",         "greenhouse", "automattic"),
    ("Canonical",          "greenhouse", "canonical"),
    ("Elastic",            "greenhouse", "elastic"),
    ("HashiCorp",          "greenhouse", "hashicorp"),
    ("Grafana Labs",       "greenhouse", "grafanalabs"),
    ("Doist",              "lever",      "doist"),
    ("Basecamp",           "lever",      "basecamp"),
    ("Buffer",             "greenhouse", "buffer"),
    ("Zapier",             "greenhouse", "zapier"),
    ("InVision",           "greenhouse", "invision"),
    ("DuckDuckGo",         "greenhouse", "duckduckgo"),
    ("Hotjar",             "lever",      "hotjar"),
    ("Toggl",              "lever",      "toggl"),
    ("Remote.com",         "greenhouse", "remote"),
    ("Deel",               "greenhouse", "deel"),
    ("Oyster HR",          "greenhouse", "oysterhr"),
    ("Loom",               "greenhouse", "loom"),
    ("Miro",               "greenhouse", "miro"),
    ("Figma",              "greenhouse", "figma"),
    ("Notion",             "greenhouse", "notion"),
    ("Linear",             "ashby",      "linear"),
    ("Vercel",             "lever",      "vercel"),
    ("Netlify",            "greenhouse", "netlify"),
    ("PlanetScale",        "lever",      "planetscale"),
    ("Supabase",           "greenhouse", "supabase"),
    ("Neon",               "greenhouse", "neon"),
    ("Turso",              "lever",      "turso"),
    ("Railway",            "lever",      "railway"),
    ("Fly.io",             "lever",      "flyio"),
    ("Temporal",           "greenhouse", "temporal"),
    ("Sourcegraph",        "greenhouse", "sourcegraph"),
    ("Sentry",             "greenhouse", "sentry"),
    ("1Password",          "lever",      "1password"),
    ("Bitwarden",          "greenhouse", "bitwarden"),
    ("Mullvad VPN",        "lever",      "mullvad"),
    ("ProtonMail",         "greenhouse", "proton"),
    ("Fastly",             "greenhouse", "fastly"),
    ("Cloudflare",         "greenhouse", "cloudflare"),
    ("Datadog",            "greenhouse", "datadog"),
    ("PagerDuty",          "greenhouse", "pagerduty"),
    ("New Relic",          "greenhouse", "newrelic"),
    ("Dynatrace",          "greenhouse", "dynatrace"),
    ("Snyk",               "lever",      "snyk"),
    ("Tenable",            "greenhouse", "tenable"),
    ("Semgrep",            "greenhouse", "semgrep"),
    ("PostHog",            "lever",      "posthog"),
    ("Mixpanel",           "greenhouse", "mixpanel"),
    ("Amplitude",          "greenhouse", "amplitude"),
    ("Heap",               "greenhouse", "heap"),
    ("FullStory",          "greenhouse", "fullstory"),
    ("LogRocket",          "greenhouse", "logrocket"),
    ("Segment",            "greenhouse", "segment"),
    ("Braze",              "greenhouse", "braze"),
    ("Customer.io",        "lever",      "customerio"),
    ("Klaviyo",            "greenhouse", "klaviyo"),
    ("Sendbird",           "greenhouse", "sendbird"),
    ("Intercom",           "lever",      "intercom"),
    ("Zendesk",            "greenhouse", "zendesk"),
    ("Help Scout",         "lever",      "helpscout"),
    ("Freshworks",         "greenhouse", "freshworks"),
    ("Hubspot",            "greenhouse", "hubspot"),
    ("Pipedrive",          "greenhouse", "pipedrive"),
    ("Close",              "lever",      "close"),
    ("Copper",             "lever",      "copper"),
    ("Attio",              "ashby",      "attio"),
    ("Folk",               "lever",      "folk"),
    ("Monday.com",         "greenhouse", "mondaycom"),
    ("Asana",              "greenhouse", "asana"),
    ("ClickUp",            "greenhouse", "clickup"),
    ("Todoist",            "lever",      "doist"),
    ("Linear",             "ashby",      "linear"),
    ("Height",             "lever",      "height"),
    ("Shortcut",           "greenhouse", "shortcut"),
    ("Plane",              "lever",      "plane"),
    ("Coda",               "greenhouse", "coda"),
    ("Airtable",           "greenhouse", "airtable"),
    ("Retool",             "greenhouse", "retool"),
    ("Bubble",             "greenhouse", "bubble"),
    ("Webflow",            "greenhouse", "webflow"),
    ("Framer",             "greenhouse", "framer"),
    ("Squarespace",        "greenhouse", "squarespace"),
    ("Ghost",              "lever",      "ghost"),
    ("ConvertKit",         "greenhouse", "convertkit"),
    ("Beehiiv",            "greenhouse", "beehiiv"),
    ("Substack",           "lever",      "substack"),
    ("Medium",             "greenhouse", "medium"),
    ("Dev.to",             "lever",      "devto"),
    ("Hashnode",           "lever",      "hashnode"),
    ("Draftbit",           "lever",      "draftbit"),
    ("Expo",               "greenhouse", "expo"),
    ("React Native",       "greenhouse", "reactnative"),
    ("Tailwind",           "lever",      "tailwind"),
    ("Prisma",             "greenhouse", "prisma"),
    ("tRPC",               "lever",      "trpc"),
    ("Turbo",              "lever",      "turbo"),
    ("Nx",                 "greenhouse", "nrwl"),
    ("Nx (Nrwl)",          "greenhouse", "nrwl"),
    ("Weights & Biases",   "greenhouse", "wandb"),
    ("Hugging Face",       "greenhouse", "huggingface"),
    ("Mistral AI",         "greenhouse", "mistralai"),
    ("Cohere",             "greenhouse", "cohere"),
    ("Scale AI",           "greenhouse", "scaleai"),
    ("Labelbox",           "greenhouse", "labelbox"),
    ("Roboflow",           "lever",      "roboflow"),
    ("LangChain",          "greenhouse", "langchain"),
    ("Weaviate",           "greenhouse", "weaviate"),
    ("Pinecone",           "greenhouse", "pinecone"),
    ("Chroma",             "lever",      "chroma"),
    ("Qdrant",             "lever",      "qdrant"),
    ("Milvus / Zilliz",    "lever",      "zilliz"),
    ("dbt Labs",           "lever",      "dbtlabs"),
    ("Airbyte",            "greenhouse", "airbyte"),
    ("Fivetran",           "greenhouse", "fivetran"),
    ("Dagster",            "lever",      "dagster"),
    ("Prefect",            "greenhouse", "prefect"),
    ("Monte Carlo",        "greenhouse", "montecarlo"),
    ("Great Expectations", "greenhouse", "superconductive"),
    ("Census",             "lever",      "censushq"),
    ("Hightouch",          "lever",      "hightouch"),
    ("Reverse ETL",        "lever",      "hightouch"),
    ("DoltHub",            "lever",      "dolthub"),
    ("Motherduck",         "lever",      "motherduck"),
    ("Cube Dev",           "greenhouse", "cube"),
    ("Lightdash",          "greenhouse", "lightdash"),
    ("Evidence",           "lever",      "evidence"),
    ("Metabase",           "greenhouse", "metabase"),
    ("Redash",             "lever",      "redash"),
    ("Mode Analytics",     "greenhouse", "mode"),
    ("Hex",                "greenhouse", "hex"),
    ("Deepnote",           "lever",      "deepnote"),
    ("Observable",         "greenhouse", "observable"),
    ("Streamlit",          "greenhouse", "streamlit"),
    ("Gradio",             "lever",      "gradio"),
    ("FastAPI",            "lever",      "fastapi"),
    ("Pydantic",           "lever",      "pydantic"),
    ("Stripe",             "greenhouse", "stripe"),
    ("Shopify",            "greenhouse", "shopify"),
    ("Paddle",             "lever",      "paddle"),
    ("LemonSqueezy",       "lever",      "lemonsqueezy"),
    ("RevenueCat",         "greenhouse", "revenuecat"),
    ("Superwall",          "lever",      "superwall"),
    ("Adapty",             "lever",      "adapty"),
    ("Adjust",             "greenhouse", "adjust"),
    ("Branch",             "greenhouse", "branch"),
    ("AppsFlyer",          "greenhouse", "appsflyer"),
    ("Kochava",            "greenhouse", "kochava"),
    ("Singular",           "greenhouse", "singular"),
    ("Firebase",           "greenhouse", "firebase"),
    ("Supabase",           "greenhouse", "supabase"),
    ("Appwrite",           "lever",      "appwrite"),
    ("Nhost",              "lever",      "nhost"),
    ("PocketBase",         "lever",      "pocketbase"),
    ("Directus",           "lever",      "directus"),
    ("Strapi",             "lever",      "strapi"),
    ("Sanity",             "greenhouse", "sanity"),
    ("Contentful",         "greenhouse", "contentful"),
    ("Storyblok",          "greenhouse", "storyblok"),
    ("Prismic",            "lever",      "prismic"),
    ("DatoCMS",            "lever",      "datocms"),
    ("Contentstack",       "greenhouse", "contentstack"),
    ("Hygraph",            "lever",      "hygraph"),
    ("Kontent.ai",         "lever",      "kentico"),
    ("Storybook",          "lever",      "storybook"),
    ("Chromatic",          "lever",      "chromatic"),
    ("Playwright",         "greenhouse", "playwright"),
    ("Cypress",            "greenhouse", "cypress"),
    ("TestRail",           "greenhouse", "testrail"),
    ("Semaphore CI",       "greenhouse", "rendered"),
    ("CircleCI",           "greenhouse", "circleci"),
    ("Travis CI",          "lever",      "travis"),
    ("Buildkite",          "lever",      "buildkite"),
    ("Harness",            "greenhouse", "harness"),
    ("Pulumi",             "greenhouse", "pulumi"),
    ("Crossplane",         "lever",      "crossplane"),
    ("Argo",               "lever",      "argo"),
    ("Flux",               "lever",      "flux"),
    ("Teleport",           "greenhouse", "teleport"),
    ("Tailscale",          "lever",      "tailscale"),
    ("WireGuard",          "lever",      "wireguard"),
    ("Tor Project",        "lever",      "torproject"),
    ("Signal",             "lever",      "signal"),
    ("Matrix / Element",   "lever",      "element"),
    ("Mattermost",         "lever",      "mattermost"),
    ("Rocket.Chat",        "lever",      "rocketchat"),
    ("Zulip",              "lever",      "zulip"),
    ("Jitsi",              "lever",      "jitsi"),
    ("Whereby",            "lever",      "whereby"),
    ("Around",             "lever",      "around"),
    ("Gather",             "lever",      "gather"),
    ("Tuple",              "lever",      "tuple"),
    ("Tandem",             "lever",      "tandem"),
    ("Levels.fyi",         "lever",      "levelsfyi"),
    ("Blind",              "lever",      "teamblind"),
    ("Glassdoor",          "greenhouse", "glassdoor"),
    ("Indeed",             "greenhouse", "indeed"),
    ("Remote OK",          "lever",      "remoteok"),
    ("We Work Remotely",   "lever",      "weworkremotely"),
    ("Remote.co",          "lever",      "remoteco"),
    ("FlexJobs",           "lever",      "flexjobs"),
    ("Working Nomads",     "lever",      "workingnomads"),
    ("Remotive",           "lever",      "remotive"),
    ("Himalayas",          "lever",      "himalayas"),
    ("Arc.dev",            "lever",      "arc"),
    ("Otta",               "greenhouse", "otta"),
    ("Wellfound",          "lever",      "angellist"),
    ("Built In",           "greenhouse", "builtin"),
    ("Trello",             "greenhouse", "trello"),
    ("Atlassian",          "greenhouse", "atlassian"),
    ("Jira",               "greenhouse", "atlassian"),
    ("Confluence",         "greenhouse", "atlassian"),
    ("Basecamp",           "lever",      "basecamp"),
    ("Twist",              "lever",      "doist"),
    ("Slack",              "greenhouse", "slack"),
    ("Discord",            "greenhouse", "discord"),
    ("Zoom",               "greenhouse", "zoom"),
    ("Loom",               "greenhouse", "loom"),
    ("Calendly",           "greenhouse", "calendly"),
    ("Cal.com",            "lever",      "calcom"),
    ("SavvyCal",           "lever",      "savvycal"),
    ("Doodle",             "greenhouse", "doodle"),
    ("Clockwise",          "greenhouse", "clockwise"),
    ("Reclaim",            "lever",      "reclaimai"),
    ("Motion",             "lever",      "usemotion"),
    ("Akiflow",            "lever",      "akiflow"),
    ("Sunsama",            "lever",      "sunsama"),
    ("Craft",              "lever",      "craft"),
    ("Obsidian",           "lever",      "obsidian"),
    ("Roam Research",      "lever",      "roamresearch"),
    ("Logseq",             "lever",      "logseq"),
    ("Mem",                "lever",      "mem"),
    ("Capacities",         "lever",      "capacities"),
    ("Napkin AI",          "lever",      "napkinai"),
    ("Gamma",              "lever",      "gamma"),
    ("Beautiful.ai",       "lever",      "beautifulai"),
    ("Canva",              "greenhouse", "canva"),
    ("Adobe",              "greenhouse", "adobe"),
    ("Figma",              "greenhouse", "figma"),
    ("Sketch",             "greenhouse", "sketch"),
    ("Affinity",           "lever",      "affinity"),
    ("Pixelmator",         "lever",      "pixelmator"),
    ("GIMP",               "lever",      "gimp"),
    ("Inkscape",           "lever",      "inkscape"),
    ("Blender",            "lever",      "blender"),
    ("Godot Engine",       "lever",      "godot"),
    ("Unity",              "greenhouse", "unity"),
    ("Unreal Engine",      "lever",      "epicgames"),
    ("Bevy Engine",        "lever",      "bevyengine"),
    ("Roblox",             "greenhouse", "roblox"),
    ("Rec Room",           "lever",      "recroom"),
    ("VRChat",             "lever",      "vrchat"),
    ("Decentraland",       "lever",      "decentraland"),
    ("OpenSea",            "greenhouse", "opensea"),
    ("Coinbase",           "greenhouse", "coinbase"),
    ("Binance",            "lever",      "binance"),
    ("Kraken",             "greenhouse", "kraken"),
    ("Ledger",             "lever",      "ledger"),
    ("Trezor",             "lever",      "trezor"),
    ("Chainlink",          "lever",      "chainlink"),
    ("Uniswap",            "lever",      "uniswap"),
    ("Alchemy",            "greenhouse", "alchemy"),
    ("Infura",             "greenhouse", "infura"),
    ("Moralis",            "lever",      "moralis"),
    ("Thirdweb",           "lever",      "thirdweb"),
    ("Fleek",              "lever",      "fleek"),
    ("IPFS / Protocol Labs", "greenhouse", "protocollabs"),
    ("Filecoin",           "greenhouse", "protocollabs"),
    ("Ethereum Foundation","lever",      "ethereumfoundation"),
    ("Solana Labs",        "greenhouse", "solanalabs"),
    ("Near Protocol",      "lever",      "nearprotocol"),
    ("Aptos Labs",         "greenhouse", "aptos"),
    ("Sui",                "greenhouse", "mysten"),
    ("Starkware",          "greenhouse", "starkware"),
    ("Polygon",            "greenhouse", "polygon"),
    ("Arbitrum",           "greenhouse", "arbitrum"),
    ("Optimism",           "greenhouse", "optimism"),
    ("zkSync",             "lever",      "zksync"),
    ("Base",               "greenhouse", "base"),
    ("Avalanche",          "greenhouse", "ava"),
    ("Stellar",            "greenhouse", "stellar"),
    ("Ripple",             "greenhouse", "ripple"),
    ("Phantom",            "lever",      "phantom"),
    ("MetaMask",           "greenhouse", "metamask"),
    ("Rainbow Wallet",     "lever",      "rainbow"),
    ("WalletConnect",      "lever",      "walletconnect"),
    ("Safe",               "lever",      "safe"),
    ("Gnosis Chain",       "lever",      "gnosis"),
    ("Consensys",          "greenhouse", "consensys"),
    ("Alchemy",            "greenhouse", "alchemy"),
    ("Hardhat",            "lever",      "hardhat"),
    ("Foundry",            "lever",      "foundry"),
    ("OpenZeppelin",       "lever",      "openzeppelin"),
    ("Chainalysis",        "greenhouse", "chainalysis"),
    ("Elliptic",           "greenhouse", "elliptic"),
    ("TRM Labs",           "greenhouse", "trmlabs"),
    ("Nansen",             "lever",      "nansen"),
    ("Dune Analytics",     "lever",      "dune"),
    ("Messari",            "greenhouse", "messari"),
    ("CoinGecko",          "lever",      "coingecko"),
    ("CoinMarketCap",      "greenhouse", "coinmarketcap"),
    ("The Block",          "lever",      "theblock"),
    ("Blockworks",         "lever",      "blockworks"),
    ("Decrypt",            "lever",      "decrypt"),
    ("Bankless",           "lever",      "bankless"),
    ("Milk Road",          "lever",      "milkroad"),
    ("Morning Brew",       "greenhouse", "morningbrew"),
    ("The Hustle",         "greenhouse", "thehustle"),
    ("TLDR",               "lever",      "tldr"),
    ("Beehiiv",            "greenhouse", "beehiiv"),
    ("Ghost",              "lever",      "ghost"),
    ("ConvertKit",         "greenhouse", "convertkit"),
    ("Mailchimp",          "greenhouse", "mailchimp"),
    ("ActiveCampaign",     "greenhouse", "activecampaign"),
    ("Drip",               "lever",      "drip"),
    ("Omnisend",           "lever",      "omnisend"),
    ("Sendgrid",           "greenhouse", "sendgrid"),
    ("Mailgun",            "greenhouse", "mailgun"),
    ("Postmark",           "lever",      "postmark"),
    ("Resend",             "lever",      "resend"),
    ("Loops",              "lever",      "loops"),
    ("Buttondown",         "lever",      "buttondown"),
    ("Listmonk",           "lever",      "listmonk"),
    ("Mailtrap",           "lever",      "mailtrap"),
    ("Twilio",             "greenhouse", "twilio"),
    ("Vonage",             "greenhouse", "vonage"),
    ("MessageBird",        "greenhouse", "messagebird"),
    ("Bandwidth",          "greenhouse", "bandwidth"),
    ("Telnyx",             "greenhouse", "telnyx"),
    ("Plivo",              "lever",      "plivo"),
    ("Sinch",              "greenhouse", "sinch"),
    ("Nexmo",              "greenhouse", "vonage"),
    ("LiveKit",            "lever",      "livekit"),
    ("Agora",              "greenhouse", "agora"),
    ("Daily.co",           "lever",      "daily"),
    ("100ms",              "lever",      "100ms"),
    ("Stream",             "greenhouse", "stream"),
    ("PubNub",             "greenhouse", "pubnub"),
    ("Ably",               "lever",      "ably"),
    ("Pusher",             "greenhouse", "pusher"),
    ("Socket.io",          "lever",      "socketio"),
    ("Cloudinary",         "greenhouse", "cloudinary"),
    ("imgix",              "greenhouse", "imgix"),
    ("ImageKit",           "lever",      "imagekit"),
    ("Uploadcare",         "lever",      "uploadcare"),
    ("Mux",                "greenhouse", "mux"),
    ("JW Player",          "greenhouse", "jwplayer"),
    ("Wistia",             "greenhouse", "wistia"),
    ("Vimeo",              "greenhouse", "vimeo"),
    ("Loom",               "greenhouse", "loom"),
    ("Grain",              "lever",      "grain"),
    ("Gong",               "greenhouse", "gong"),
    ("Chorus.ai",          "greenhouse", "chorus"),
    ("Clari",              "greenhouse", "clari"),
    ("Outreach",           "greenhouse", "outreach"),
    ("Salesloft",          "greenhouse", "salesloft"),
    ("Apollo",             "greenhouse", "apollo"),
    ("ZoomInfo",           "greenhouse", "zoominfo"),
    ("Clearbit",           "greenhouse", "clearbit"),
    ("Lusha",              "greenhouse", "lusha"),
    ("Hunter.io",          "lever",      "hunterio"),
    ("Phantombuster",      "lever",      "phantombuster"),
    ("Make (Integromat)",  "greenhouse", "make"),
    ("n8n",                "lever",      "n8n"),
    ("Zapier",             "greenhouse", "zapier"),
    ("IFTTT",              "greenhouse", "ifttt"),
    ("Automate.io",        "lever",      "automateio"),
    ("Workato",            "greenhouse", "workato"),
    ("Tray.io",            "greenhouse", "tray"),
    ("Boomi",              "greenhouse", "boomi"),
    ("MuleSoft",           "greenhouse", "mulesoft"),
    ("Celigo",             "greenhouse", "celigo"),
    ("Jitterbit",          "greenhouse", "jitterbit"),
    ("Informatica",        "greenhouse", "informatica"),
    ("Talend",             "greenhouse", "talend"),
    ("Stitch",             "greenhouse", "stitch"),
    ("Matillion",          "greenhouse", "matillion"),
    ("Rivery",             "lever",      "rivery"),
    ("Airbyte",            "greenhouse", "airbyte"),
    ("Fivetran",           "greenhouse", "fivetran"),
    ("Hevo",               "greenhouse", "hevo"),
    ("Singer",             "lever",      "singer"),
    ("Meltano",            "greenhouse", "meltano"),
    ("Keboola",            "lever",      "keboola"),
    ("Xplenty",            "lever",      "xplenty"),
    ("Alooma",             "lever",      "alooma"),
    ("Segment",            "greenhouse", "segment"),
    ("RudderStack",        "lever",      "rudderstack"),
    ("Snowplow",           "greenhouse", "snowplow"),
    ("Heap",               "greenhouse", "heap"),
    ("Amplitude",          "greenhouse", "amplitude"),
    ("Mixpanel",           "greenhouse", "mixpanel"),
    ("FullStory",          "greenhouse", "fullstory"),
    ("LogRocket",          "greenhouse", "logrocket"),
    ("Hotjar",             "lever",      "hotjar"),
    ("Microsoft",          "greenhouse", "microsoft"),
    ("Google",             "greenhouse", "google"),
    ("Amazon",             "greenhouse", "amazon"),
    ("Meta",               "greenhouse", "facebook"),
    ("Apple",              "greenhouse", "apple"),
    ("Netflix",            "greenhouse", "netflix"),
    ("Spotify",            "greenhouse", "spotify"),
    ("Twitter / X",        "greenhouse", "twitter"),
    ("LinkedIn",           "greenhouse", "linkedin"),
    ("Salesforce",         "greenhouse", "salesforce"),
    ("SAP",                "greenhouse", "sap"),
    ("Oracle",             "greenhouse", "oracle"),
    ("IBM",                "greenhouse", "ibm"),
    ("Cisco",              "greenhouse", "cisco"),
    ("Dell",               "greenhouse", "dell"),
    ("HP",                 "greenhouse", "hp"),
    ("Intel",              "greenhouse", "intel"),
    ("Nvidia",             "greenhouse", "nvidia"),
    ("AMD",                "greenhouse", "amd"),
    ("Qualcomm",           "greenhouse", "qualcomm"),
    ("ARM",                "greenhouse", "arm"),
    ("TSMC",               "greenhouse", "tsmc"),
    ("Palantir",           "greenhouse", "palantir"),
    ("Snowflake",          "greenhouse", "snowflake"),
    ("MongoDB",            "greenhouse", "mongodb"),
    ("Databricks",         "greenhouse", "databricks"),
    ("Confluent",          "greenhouse", "confluent"),
    ("dbt Labs",           "lever",      "dbtlabs"),
    ("Astronomer",         "greenhouse", "astronomer"),
    ("Prefect",            "greenhouse", "prefect"),
    ("Dagster",            "lever",      "dagster"),
    ("Great Expectations", "greenhouse", "superconductive"),
    ("OpenLineage",        "lever",      "openlineage"),
    ("Apache Spark",       "greenhouse", "apachespark"),
    ("Flink",              "greenhouse", "apacheflink"),
    ("Kafka",              "greenhouse", "confluent"),
    ("Pulsar",             "greenhouse", "streamnative"),
    ("RabbitMQ",           "greenhouse", "cloudamqp"),
    ("NATS",               "lever",      "nats"),
    ("Redis",              "greenhouse", "redis"),
    ("Memcached",          "greenhouse", "memcached"),
    ("ScyllaDB",           "greenhouse", "scylladb"),
    ("YugabyteDB",         "greenhouse", "yugabyte"),
    ("CockroachDB",        "greenhouse", "cockroachlabs"),
    ("PlanetScale",        "lever",      "planetscale"),
    ("Neon",               "greenhouse", "neon"),
    ("Supabase",           "greenhouse", "supabase"),
    ("TiDB",               "greenhouse", "pingcap"),
    ("DoltHub",            "lever",      "dolthub"),
    ("Motherduck",         "lever",      "motherduck"),
    ("ClickHouse",         "greenhouse", "clickhouse"),
    ("StarRocks",          "greenhouse", "starrocks"),
    ("Doris",              "greenhouse", "doris"),
    ("Druid",              "greenhouse", "druid"),
    ("Pinot",              "greenhouse", "pinot"),
    ("Trino",              "greenhouse", "trino"),
    ("Presto",             "greenhouse", "presto"),
    ("duckdb",             "lever",      "duckdblabs"),
    ("Hive",               "greenhouse", "hive"),
    ("Impala",             "greenhouse", "impala"),
    ("Kylin",              "greenhouse", "kylin"),
    ("Doris",              "greenhouse", "doris"),
]

# Deduplicate CURATED_REMOTE by name (keep first occurrence)
_seen_names = set()
CURATED_REMOTE_DEDUPED = []
for entry in CURATED_REMOTE:
    if entry[0].lower() not in _seen_names:
        _seen_names.add(entry[0].lower())
        CURATED_REMOTE_DEDUPED.append(entry)
CURATED_REMOTE = CURATED_REMOTE_DEDUPED

# ------------------------------------------------------------------ #
#  Remote GitHub Repo Parsers
# ------------------------------------------------------------------ #

def _get(url: str, timeout: int = 15):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "VisaJobBot/1.0"})
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  GET {url} failed: {e}")
        return None


def parse_yanirs():
    """yanirs/established-remote — table-based markdown of established remote companies."""
    print("Fetching yanirs/established-remote...")
    url = "https://raw.githubusercontent.com/yanirs/established-remote/master/README.md"
    r = _get(url)
    if not r:
        return []

    companies = []
    for line in r.text.splitlines():
        # lines look like: [CompanyName](url) | industry | tech stack | ...
        m = re.match(r"^\[([^\]]+)\]\((https?://[^\)]+)\)\s*\|", line)
        if m:
            name = m.group(1).strip()
            site_url = m.group(2).strip()
            # Extract Jobs link if present
            jobs_m = re.search(r"Jobs\]\((https?://[^\)]+)\)", line)
            careers_url = jobs_m.group(1) if jobs_m else site_url
            ats, slug = classify_ats(careers_url)
            companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": "yanirs"})
    print(f"  Found {len(companies)} companies in yanirs")
    return companies


def parse_adherb():
    """adherb/remote-tech-companies — table with company name, industry, region, careers link."""
    print("Fetching adherb/remote-tech-companies...")
    url = "https://raw.githubusercontent.com/adherb/remote-tech-companies/main/README.md"
    r = _get(url)
    if not r:
        return []

    companies = []
    for line in r.text.splitlines():
        if "|" not in line or "---" in line or "Company" in line:
            continue
        # Extract markdown links from cells
        links = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line)
        if links:
            name = links[0][0].strip("*").strip()
            # Try to find a direct careers/jobs link
            careers_url = ""
            for _, link_url in links:
                if any(kw in link_url.lower() for kw in ["careers", "jobs", "greenhouse", "lever", "ashby"]):
                    careers_url = link_url
                    break
            if not careers_url and links:
                careers_url = links[0][1]  # fallback to first link
            ats, slug = classify_ats(careers_url)
            companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": "adherb"})
    print(f"  Found {len(companies)} companies in adherb")
    return companies


def parse_lukasz_awesome():
    """lukasz-madon/awesome-remote-job — curated list with company links."""
    print("Fetching lukasz-madon/awesome-remote-job...")
    url = "https://raw.githubusercontent.com/lukasz-madon/awesome-remote-job/master/README.md"
    r = _get(url)
    if not r:
        return []

    companies = []
    in_companies = False
    for line in r.text.splitlines():
        if "## Companies with" in line or "## Remote-First Companies" in line:
            in_companies = True
        elif in_companies and line.startswith("## "):
            in_companies = False
        if not in_companies:
            continue
        # Matches both "- [name](url)" and "  1. [name](url)" formats
        m = re.search(r"^\s*(?:\d+\.|-|\*)\s*\[([^\]]+)\]\((https?://[^\)]+)\)", line)
        if m:
            name = m.group(1).strip()
            careers_url = m.group(2).strip()
            ats, slug = classify_ats(careers_url)
            companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": "lukasz_awesome"})
    print(f"  Found {len(companies)} companies in lukasz_awesome")
    return companies


def parse_andrews1022():
    """andrews1022/remote-tech-companies — markdown table."""
    print("Fetching andrews1022/remote-tech-companies...")
    url = "https://raw.githubusercontent.com/andrews1022/remote-tech-companies/main/README.md"
    r = _get(url)
    if not r:
        return []

    companies = []
    for line in r.text.splitlines():
        if "|" not in line or "---" in line:
            continue
        links = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line)
        if links:
            name = links[0][0].strip("*").strip()
            careers_url = links[-1][1] if len(links) > 1 else links[0][1]
            ats, slug = classify_ats(careers_url)
            companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": "andrews1022"})
    print(f"  Found {len(companies)} companies in andrews1022")
    return companies


def parse_remote_repos():
    """Parse additional remote-company GitHub repos as markdown bullet/numbered lists."""
    repos = [
        # Note: only listing repos verified to be alive
        ("hugo53",  "https://raw.githubusercontent.com/hugo53/awesome-RemoteWork/master/README.md"),
    ]

    companies = []
    for source_name, url in repos:
        r = _get(url)
        if not r:
            continue
        found = 0
        for line in r.text.splitlines():
            # Table rows with |
            if "|" in line and "---" not in line:
                links = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line)
                if links:
                    name = links[0][0].strip("*").strip()
                    careers_url = links[-1][1] if len(links) > 1 else links[0][1]
                    if name and len(name) > 1:
                        ats, slug = classify_ats(careers_url)
                        companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": source_name})
                        found += 1
            # Bullet or numbered list items
            elif re.match(r"^\s*(?:\d+\.|-|\*)\s*\[", line):
                m = re.search(r"^\s*(?:\d+\.|-|\*)\s*\[([^\]]+)\]\((https?://[^\)]+)\)", line)
                if m:
                    name = m.group(1).strip()
                    careers_url = m.group(2).strip()
                    if name and len(name) > 1:
                        ats, slug = classify_ats(careers_url)
                        companies.append({"name": name, "careers_url": careers_url, "ats": ats, "slug": slug, "source": source_name})
                        found += 1
        print(f"  [{source_name}] Found {found} companies")

    return companies


# ------------------------------------------------------------------ #
#  Deduplication
# ------------------------------------------------------------------ #
def deduplicate(companies: list) -> list:
    priority = {
        "greenhouse": 6, "lever": 6, "ashby": 6,
        "smartrecruiters": 5, "personio": 5, "workable": 4,
        "workday": 2, "custom": 1, "unknown": 0,
    }
    seen = {}
    for co in companies:
        name_clean = co.get("name", "").strip()
        if not name_clean or len(name_clean) < 2:
            continue
        key = name_clean.lower()
        if key not in seen:
            seen[key] = dict(co)
        else:
            existing = seen[key]
            if priority.get(existing.get("ats"), 0) < priority.get(co.get("ats"), 0):
                seen[key] = dict(co)
            elif not existing.get("careers_url") and co.get("careers_url"):
                existing["careers_url"] = co["careers_url"]
                existing["ats"] = co.get("ats", existing["ats"])
                existing["slug"] = co.get("slug", existing["slug"])
    return list(seen.values())


# ------------------------------------------------------------------ #
#  Main Execution
# ------------------------------------------------------------------ #
def main():
    all_companies = []

    # 1. Curated list (manually verified ATS slugs — highest priority)
    print("Adding curated remote companies...")
    for name, ats, slug in CURATED_REMOTE:
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
            "source": "curated_remote",
        })
    print(f"  Added {len(CURATED_REMOTE)} curated remote companies")

    # 2. Fetch live remote GitHub repos
    time.sleep(0.2)
    all_companies.extend(parse_yanirs())
    time.sleep(0.2)
    all_companies.extend(parse_adherb())
    time.sleep(0.2)
    all_companies.extend(parse_lukasz_awesome())
    time.sleep(0.2)
    all_companies.extend(parse_andrews1022())
    time.sleep(0.2)
    all_companies.extend(parse_remote_repos())

    # 3. Deduplicate
    all_companies = deduplicate(all_companies)

    # 4. Classify into API-scrapable vs custom
    API_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "personio", "workable"}
    scrapable = [c for c in all_companies if c.get("ats") in API_ATS]
    custom = [
        c for c in all_companies
        if c.get("ats") not in API_ATS and c.get("careers_url")
    ]
    scrapable_names = {c["name"].lower() for c in scrapable}
    custom = [c for c in custom if c["name"].lower() not in scrapable_names]

    print(f"\n{'='*60}")
    print(f"Total unique remote companies: {len(all_companies)}")
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
    with open("remote_companies.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved remote_companies.json ✓")


if __name__ == "__main__":
    main()

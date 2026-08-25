# Visa Sponsorship Jobs Scraper & API

Find sponsorship-friendly jobs by combining live public ATS job APIs with official government sponsor registry intelligence.

Stop wasting time on jobs that don't sponsor. Most job scrapers return thousands of listings that explicitly require existing work authorization. This Actor cross-references employer names against **official government sponsor registers** (UK Home Office Skilled Worker Register & US Department of Labor LCA disclosure filings) to deliver actionable visa intelligence.

> **Disclaimer**: *This Actor provides evidence of sponsorship capability via official registries, not a guarantee of employment.*

---

## ⚡ Enriched Visa Intelligence Output (camelCase)

Every dataset record delivers clean, normalized camelCase JSON:

```json
{
  "id": "gh-stripe-4921049",
  "title": "Senior Machine Learning Infrastructure Engineer",
  "company": "Stripe",
  "companyNormalized": "stripe",
  "location": "London, United Kingdom",
  "locations": ["London, United Kingdom"],
  "remote": true,
  "remoteType": "region_restricted",
  "employmentType": "full_time",
  "seniority": "senior",
  "salaryMin": 110000,
  "salaryMax": 150000,
  "salaryCurrency": "GBP",
  "postedAt": "2026-08-22T08:30:00Z",
  "applyUrl": "https://boards.greenhouse.io/stripe/jobs/4921049",
  "jobUrl": "https://boards.greenhouse.io/stripe/jobs/4921049",
  "source": "greenhouse",
  "ats": "greenhouse",
  "technologies": ["Python", "PyTorch", "Kubernetes", "Ray", "CUDA"],
  
  "visaSignal": "on_sponsor_list",
  "visaConfidence": 0.85,
  "visaType": "UK Skilled Worker",
  "visaSponsorMeta": {
    "matched_sponsor": "Stripe Payments UK Limited",
    "country": "GB",
    "rating": "A",
    "routes": ["Skilled Worker"]
  },
  "authFit": "sponsor_required_and_plausible",

  "relevanceScore": 0.94,
  "compositeScore": 0.91,
  "opportunityScore": 91,
  "classificationReason": "Core ML platform engineering role managing distributed GPU training clusters.",
  "isAiRole": true
}
```

---

## 📦 Run Output & Reports

Every run produces a **machine-readable Dataset** *and* a set of **human-friendly reports**, so you get both an API-ready feed and a polished intelligence summary.

**Output tab links** (defined in the Actor output schema):

| Output | What it is |
|---|---|
| 📊 **Jobs Dataset** | All normalized, visa-enriched jobs. Canonical output for APIs, automation, and CSV/Excel/JSON export. Ordered by `opportunityScore` in the Console table. |
| 🌐 **HTML Report** | Beautiful standalone report: key statistics, top opportunities, country / company / visa / source breakdowns, methodology, and disclaimers. Opens directly in the Output tab. |
| 📄 **Run Summary (JSON)** | Machine-readable run summary — search criteria, statistics, top matches, and aggregations. Useful for downstream agents and pipelines. |
| 📈 **Run Statistics** | Low-level pipeline execution statistics (fetched, filtered, deduplicated, enriched, duration, source health). |

**New dataset column — `opportunityScore` (0–100):** a single transparent ranking number (`compositeScore × 100`) combining visa evidence, relevance, recency, seniority fit, salary, and source trust. Sort the Dataset by it descending to surface the strongest opportunities first.

**Top-opportunity cards** in the HTML report show, per job: opportunity score, title, company, location + country, visa evidence badge with explanation, seniority/employment, remote/hybrid, salary, technologies, posted date, the data-backed reasons it is recommended, and a direct **Apply** link.

**Empty runs are still useful:** if no jobs match, the report explains how many jobs and sources were scanned and gives concrete suggestions to broaden the search.

> Reports are generated from the already-produced pipeline results — no extra fetching, no extra billing.

---

## 🛡️ What Makes This Different?

- **🛂 Official Visa Intelligence**: Checks company names against official UK Skilled Worker sponsor registers and US DOL LCA historical filings.
- **📊 6-Tier Signal Model**:
  - `stated_in_jd` (1.00): Job description explicitly mentions visa sponsorship or relocation support.
  - `on_sponsor_list` (0.85): Company is an active licensed sponsor on official government registers.
  - `employer_sponsored_region` (0.70): Destination uses an employer-sponsored work-permit model (Gulf/EPS/SSW) — overseas pack only, not a registry match.
  - `historical_filings` (0.65): Company has certified US DOL LCA filings in the past 12 months.
  - `unknown` (0.25): No explicit signal either way.
  - `explicit_no` (0.00): Job explicitly states no sponsorship is available (filtered out by default).
- **📡 Multi-ATS Coverage**: Public API endpoints for Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Personio, RemoteOK, Remotive, Arbeitnow, Himalayas, HN Who's Hiring, and Jobicy.
- **🤖 Optional AI Classification**: Provider-agnostic LLM relevance evaluation (Gemini, Groq, OpenRouter) scoring tech stack match quality.
- **⚡ Fast, HTTP-First Architecture**: Lightweight API requests without heavy headless browser overhead.

---

## 💰 Pay-Per-Event (PPE) Pricing

You only pay for the exact volume of data emitted:

| Event | Description | Price |
|---|---|---|
| `apify-actor-start` | Actor start fee *(Configured in Apify Console)* | $0.05 / run |
| `job-result` | Per normalized job returned | $2.00 / 1,000 jobs |
| `visa-enriched-job` | Per job verified against official government registers | +$1.00 / 1,000 jobs |
| `ai-classified-job` | Per job analyzed with AI technical scoring | +$3.00 / 1,000 jobs |
| `overseas-job` | Per job from the overseas expansion pack *(optional; final price set in Apify Console)* | +$1.50 / 1,000 jobs |

*Filtered-out and duplicate listings are NEVER charged.*

---

## ⚙️ Input Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `keywords` | `array` | `[]` | Job titles, skills, or stack terms (e.g. `["Machine Learning", "Kotlin", "Python"]`). |
| `countries` | `array` | `[]` | Country filter (e.g. `["United Kingdom", "Germany", "United States"]`). |
| `visaSponsorshipOnly` | `boolean` | `true` | When true, returns jobs with confirmed sponsorship signals (`on_sponsor_list`, `stated_in_jd`, `historical_filings`, `employer_sponsored_region`). |
| `includeUnknownVisa` | `boolean` | `false` | When `visaSponsorshipOnly` is enabled, set to true to also include unknown visa status jobs. |
| `minVisaConfidence` | `string` | `"unknown"` | Minimum required confidence (`"unknown"`, `"historical_filings"`, `"employer_sponsored_region"`, `"on_sponsor_list"`, `"stated_in_jd"`). |
| `sources` | `array` | `["greenhouse", "lever", ...]` | Target ATS endpoints and job boards to query. |
| `companyUrls` | `array` | `[]` | Specific ATS career page URLs to auto-extract. |
| `postedWithinDays` | `integer` | `30` | Maximum posting age in days. |
| `enableAIClassification` | `boolean` | `false` | Enable LLM technical relevance scoring. |
| `maxResults` | `integer` | `200` | Maximum jobs to return. |

---

## 🔌 Integration Example (Python SDK)

```python
from apify_client import ApifyClient

client = ApifyClient("YOUR_APIFY_TOKEN")
run = client.actor("alireza_nezami/visa-sponsorship-jobs-scraper").call(
    run_input={
        "keywords": ["Machine Learning", "Python"],
        "countries": ["United Kingdom"],
        "visaSponsorshipOnly": True,
        "includeUnknownVisa": False,
        "maxResults": 100
    }
)

for job in client.dataset(run["defaultDatasetId"]).iterate_items():
    print(f"{job['company']} - {job['title']} (Signal: {job['visaSignal']}, Score: {job['visaConfidence']}) -> {job['applyUrl']}")
```

---

## 🌍 Overseas Expansion (Optional)

> **Off by default.** Nothing changes unless you set `enableOverseasSources: true`.

This optional pack adds **248 build-time-verified overseas sources** for the India/Pakistan/Bangladesh → Gulf, Europe, East Asia, Canada and Australia migration corridors: government labor portals, licensed manpower agencies, niche job boards, aggregators, and visa-specialist sites. Sources were DNS+HTTP probed before inclusion and are shipped as a curated data file — they are never invented or auto-discovered at runtime. This Actor does not scrape LinkedIn, Indeed, or Glassdoor; those domains (plus ZipRecruiter, Monster, CareerBuilder, SimplyHired, Snagajob, Ladders and Dice) are hard-blacklisted and unfetchable. Overseas sources are public pages fetched with robots.txt respect and per-host rate limits.

**Categories** (selectable via `overseasCategories`): `government`, `manpower_agency`, `aggregator`, `remote_board`, `visa_specialist`, `unknown_board`.

### An honest visa signal: `employer_sponsored_region`

Jobs from Gulf and East-Asia destinations can never match the UK/US sponsor registries. The destination-country employment model (UAE/Saudi/Qatar/Kuwait/Oman/Bahrain work permits, Japan SSW, Korea EPS E-9) is **employer-sponsored by construction**, so these jobs get their own confidence level instead of being dropped:

- `employer_sponsored_region` (0.70): destination uses an employer-sponsored work-permit model. **This is NOT a verified registry match** — it records the destination's employment model honestly. If the job description itself mentions sponsorship, the stronger `stated_in_jd` signal is kept instead; `explicit_no` always wins and the job is excluded.

### Overseas input parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enableOverseasSources` | `boolean` | `false` | Include the 248 verified overseas sources. Raise `maxRuntimeSecs` to ≥ 900 when enabling. |
| `overseasCategories` | `array` | all six | Source categories to include. |
| `overseasDestinationCountries` | `array` | `[]` (all) | Keep only jobs for these destinations (jobs with unknown destination are kept). |
| `overseasMaxSourcesPerRun` | `integer` | `150` | Max sources fetched per run (10–573). |
| `overseasConcurrency` | `integer` | `20` | Concurrent overseas page fetches (5–40). |
| `overseasBudgetSecs` | `integer` | `600` | Time budget in seconds (60–3000, auto-clamped to 80% of `maxRuntimeSecs`). |
| `overseasFetchDetails` | `boolean` | `false` | Fetch job detail pages for richer descriptions and better dedup (slower, more requests). |
| `overseasMaxDetailFetches` | `integer` | `300` | Max detail-page fetches per run (0–2000). |
| `overseasSimhashDedup` | `boolean` | `true` | SimHash near-duplicate removal for copy-pasted agency JDs. |
| `respectRobotsTxt` | `boolean` | `true` | Honor robots.txt on overseas domains. |

### Sample overseas record

```json
{
  "id": "ov-gulfagency.example-8f2c1a9b3e4d5c67",
  "title": "Mason – Dubai construction vacancy",
  "company": "Al Rashid Manpower",
  "location": "Dubai",
  "country": "UAE",
  "salaryMin": 2500,
  "salaryCurrency": "AED",
  "salaryPeriod": "month",
  "applyUrl": "https://gulfagency.example/vacancies/mason-dubai/",
  "source": "overseas",
  "ats": "gulfagency.example",
  "sourceCategory": "manpower_agency",
  "destinationCountry": "UAE",
  "visaSignal": "employer_sponsored_region",
  "visaConfidence": 0.7,
  "visaType": "UAE Work Permit"
}
```

*When enabling overseas in the Actor UI: set `maxRuntimeSecs ≥ 900` and consider raising memory to 2048 MB if also enabling `overseasFetchDetails`.*

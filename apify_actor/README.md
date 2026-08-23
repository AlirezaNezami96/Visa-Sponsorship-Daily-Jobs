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
  "classificationReason": "Core ML platform engineering role managing distributed GPU training clusters.",
  "isAiRole": true
}
```

---

## 🛡️ What Makes This Different?

- **🛂 Official Visa Intelligence**: Checks company names against official UK Skilled Worker sponsor registers and US DOL LCA historical filings.
- **📊 5-Tier Signal Model**:
  - `stated_in_jd` (1.00): Job description explicitly mentions visa sponsorship or relocation support.
  - `on_sponsor_list` (0.85): Company is an active licensed sponsor on official government registers.
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

*Filtered-out and duplicate listings are NEVER charged.*

---

## ⚙️ Input Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `keywords` | `array` | `[]` | Job titles, skills, or stack terms (e.g. `["Machine Learning", "Kotlin", "Python"]`). |
| `countries` | `array` | `[]` | Country filter (e.g. `["United Kingdom", "Germany", "United States"]`). |
| `visaSponsorshipOnly` | `boolean` | `true` | When true, returns jobs with confirmed sponsorship signals (`on_sponsor_list`, `stated_in_jd`, `historical_filings`). |
| `includeUnknownVisa` | `boolean` | `false` | When `visaSponsorshipOnly` is enabled, set to true to also include unknown visa status jobs. |
| `minVisaConfidence` | `string` | `"unknown"` | Minimum required confidence (`"unknown"`, `"historical_filings"`, `"on_sponsor_list"`, `"stated_in_jd"`). |
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

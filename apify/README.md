# Visa Sponsorship Jobs Scraper & API

Stop wasting time applying to jobs that don't sponsor. This Actor cross-references official government sponsor registries (UK Skilled Worker, US H-1B/LCA) with live ATS job boards to find opportunities where visa sponsorship is actually available — not just listings that happen to contain the word "visa".

## What makes this different?

Most job scrapers return raw, unfiltered listings. This Actor delivers **actionable visa intelligence**:

- **🛂 Official Visa Intelligence**: Cross-references company names against the official UK GOV Register of Licensed Sponsors (A/B rating) and US Department of Labor LCA disclosure filings.
- **📊 Authoritative Confidence Levels**: Every job includes an explicit `visaConfidence` rating:
  - `stated_in_jd`: Job description explicitly offers visa sponsorship or relocation assistance.
  - `on_sponsor_list`: Company is a licensed sponsor on official government registries.
  - `historical_filings`: Company has certified US DOL LCA filings in the past 12 months.
  - `unknown`: No explicit signal either way.
  - `explicit_no`: Job explicitly states no sponsorship is provided (automatically filtered out by default).
- **📡 Multi-Source Public ATS Coverage**: Fetches from Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Personio, RemoteOK, Remotive, Arbeitnow, Himalayas, Jobicy, and Hacker News in a single coordinated run.
- **🤖 Optional AI Classification**: Deep job description inspection to score technical relevance (0.0–1.0), detect AI/ML roles, and extract exact tech stacks.
- **🏆 Weighted Composite Scoring**: Jobs are ranked by a balanced composite score combining visa confidence, relevance, recency, and salary fit.

---

## Who is this for?

- **Immigration attorneys & consultancies** building live employer sponsor registries.
- **Niche job boards** needing reliable "Visa Sponsorship Available" feeds.
- **Technical recruiters** sourcing global candidates for relocation.
- **Automation workflows** (n8n, Make.com, Zapier) triggering automated application pipelines.
- **Software engineers** seeking sponsorship-friendly employers worldwide.

---

## Sample Dataset Output (camelCase)

```json
{
  "id": "gh-stripe-123456",
  "title": "Senior Machine Learning Engineer",
  "company": "Stripe",
  "companyNormalized": "stripe",
  "location": "London, United Kingdom",
  "locations": ["London, United Kingdom"],
  "remote": true,
  "remoteType": "region_restricted",
  "employmentType": "full_time",
  "seniority": "senior",
  "salaryMin": 95000,
  "salaryMax": 130000,
  "salaryCurrency": "GBP",
  "postedAt": "2026-08-20T10:00:00Z",
  "applyUrl": "https://boards.greenhouse.io/stripe/jobs/123456",
  "jobUrl": "https://boards.greenhouse.io/stripe/jobs/123456",
  "source": "greenhouse",
  "ats": "greenhouse",
  "technologies": ["Python", "PyTorch", "Kubernetes"],
  "visaSponsorship": true,
  "visaConfidence": "on_sponsor_list",
  "visaType": "UK Skilled Worker",
  "visaSponsorMeta": {
    "matched_sponsor": "Stripe Payments UK Limited",
    "rating": "A",
    "country": "GB",
    "routes": ["Skilled Worker"]
  },
  "authFit": "sponsor_required_and_plausible",
  "relevanceScore": 0.92,
  "compositeScore": 0.88,
  "classificationReason": "Core ML platform role working with LLM inference pipelines.",
  "isAiRole": true
}
```

---

## Pay-Per-Event (PPE) Pricing

This Actor uses fair Pay-Per-Event pricing — you only pay for the exact volume of data emitted:

| Event | Description | Price |
|---|---|---|
| `apify-actor-start` | Actor start fee | $0.05 |
| `job-result` | Per normalized job returned | $2.00 / 1,000 jobs |
| `visa-enriched-job` | Per job matched to government registry | +$1.00 / 1,000 jobs |
| `ai-classified-job` | Per job with AI relevance analysis | +$3.00 / 1,000 jobs |

*Filtered-out and duplicate jobs are NEVER charged.*

---

## Input Options

| Parameter | Type | Default | Description |
|---|---|---|---|
| `keywords` | `array` | `[]` | Job title or skill keywords (e.g. `["Machine Learning", "Android"]`). |
| `countries` | `array` | `[]` | Country filter (e.g. `["United Kingdom", "Germany"]`). |
| `visaSponsorshipOnly` | `boolean` | `true` | Exclude jobs with negative visa signals. |
| `minVisaConfidence` | `string` | `"unknown"` | Minimum confidence level (`"unknown"`, `"historical_filings"`, `"on_sponsor_list"`, `"stated_in_jd"`). |
| `sources` | `array` | `[]` | Sources to scrape (leave empty for all). |
| `companyUrls` | `array` | `[]` | Custom career page URLs to auto-scrape. |
| `postedWithinDays` | `integer` | `30` | Max posting age in days. |
| `enableAIClassification` | `boolean` | `false` | Enable AI relevance scoring. |
| `maxResults` | `integer` | `200` | Maximum jobs to return. |

---

## Legal and Compliance

All data is fetched exclusively from public, unauthenticated ATS JSON endpoints and public job board APIs. No residential proxies, browser automation, or ToS-fragile platforms (LinkedIn, Indeed, Glassdoor) are used.

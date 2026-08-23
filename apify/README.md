# Visa Sponsorship Jobs Scraper & B2B Lead Gen Engine

> **Stop wasting time on jobs that don't sponsor. This Actor cross-references official government registries AND finds the hiring manager's email.**

Most job scrapers return thousands of dead-end listings that explicitly state *"Must already have the right to work in the country"*. This Actor changes the game by combining **live public ATS job feeds** with **authoritative government sponsor registries** (UK Home Office & US Department of Labor LCA filings) and actionable **B2B lead generation intelligence**.

Whether you are an immigration law firm, a specialized tech recruitment agency, a high-growth startup expanding globally, or an engineer seeking sponsorship, this Actor delivers verified sponsorship intelligence and hiring manager contact details directly to your pipeline.

---

## ⚡ The God-Tier Output: Job + Visa Truth + Hiring Manager Email

Every emitted record delivers complete, normalized, camelCase intelligence:

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
  
  "visaSponsorship": true,
  "visaConfidence": "on_sponsor_list",
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
  "isAiRole": true,

  "hiringContacts": [
    {
      "name": "Sarah Jenkins",
      "title": "Engineering Hiring Manager - ML Platform",
      "email": "sarah.jenkins@stripe.com",
      "linkedinUrl": "https://linkedin.com/in/sarah-jenkins-ml-lead",
      "confidence": "verified"
    }
  ],
  "companyIntel": {
    "headcount": "5,000+",
    "industry": "Financial Services / Fintech",
    "headquarters": "San Francisco, CA / Dublin, Ireland"
  }
}
```

---

## 🛡️ Why This Actor Dominates Generic ATS Scrapers

| Feature | Generic $1/1k Scrapers | Visa Sponsorship Jobs Scraper |
|---|---|---|
| **Visa Verification** | Keyword matching only ("visa" in text) | **Government Registry Cross-Referencing** (UK GOV Register + US DOL LCA) |
| **Visa Confidence Levels** | ❌ None (high false positives) | ✅ **5-Tier Confidence** (`stated_in_jd`, `on_sponsor_list`, `historical_filings`, `unknown`, `explicit_no`) |
| **Negative Visa Detection** | ❌ Fails to detect "No Sponsorship" | ✅ **Automatic Filtering** of explicit "Right to Work Only" postings |
| **Multi-ATS Integration** | Single ATS or fragmented tools | ✅ **Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Personio** + Public Boards |
| **B2B Lead Intelligence** | ❌ Only job description text | ✅ **Hiring Manager & Recruiter Email Addresses** |
| **AI Technical Relevance** | ❌ Raw keyword regex | ✅ **Multi-Provider LLM Scoring** (Gemini, Groq, OpenRouter) |
| **Cost & Speed** | Heavy Playwright browser overhead | ⚡ **Ultra-Fast HTTP-First Architecture** (sub-second queries) |

---

## 🎯 Key Use Cases & B2B Solutions

- **Immigration Law & Visa Consultancies**: Build live employer sponsor databases to match international talent with licensed sponsors.
- **Niche Tech Job Boards**: Fuel automated "Visa Sponsored Tech Jobs" portals with verified, fresh feeds.
- **Executive & Tech Recruitment Agencies**: Identify hiring teams with open budgets and certified visa sponsorship history.
- **B2B Outbound Campaigns**: Integrate with Apollo, Clay, n8n, or Make to reach hiring managers the day a job is posted.
- **International Software Engineers**: Target high-confidence global relocation opportunities without wasting time on ineligible roles.

---

## 💰 Fair Pay-Per-Event (PPE) Pricing

Apify is sunsetting monthly rental pricing. You only pay for exact value delivered:

| Event | Description | Price |
|---|---|---|
| `actor-start` | Actor execution initialization | $0.05 / run |
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
| `visaSponsorshipOnly` | `boolean` | `true` | Exclude all jobs with negative visa signals. |
| `minVisaConfidence` | `string` | `"unknown"` | Minimum required confidence (`"unknown"`, `"historical_filings"`, `"on_sponsor_list"`, `"stated_in_jd"`). |
| `sources` | `array` | `[]` | Target ATS endpoints (`["greenhouse", "lever", "ashby", "workable", "remoteok"]`). |
| `companyUrls` | `array` | `[]` | Specific ATS career page URLs to auto-extract. |
| `postedWithinDays` | `integer` | `30` | Maximum posting age in days. |
| `enableAIClassification` | `boolean` | `false` | Enable LLM technical relevance scoring. |
| `maxResults` | `integer` | `200` | Maximum jobs to return. |

---

## 🔌 Easy Integration (Python, cURL, Webhooks)

### Python SDK
```python
from apify_client import ApifyClient

client = ApifyClient("YOUR_APIFY_TOKEN")
run = client.actor("alireza_nezami/visa-sponsorship-jobs-scraper").call(
    run_input={
        "keywords": ["Machine Learning", "Python"],
        "countries": ["United Kingdom"],
        "visaSponsorshipOnly": True,
        "minVisaConfidence": "on_sponsor_list",
        "maxResults": 100
    }
)

for job in client.dataset(run["defaultDatasetId"]).iterate_items():
    print(f"{job['company']} - {job['title']} (Visa: {job['visaConfidence']}) -> {job['applyUrl']}")
```

### Automation Workflows
Easily connect this Actor to **Make.com**, **n8n**, **Zapier**, or **Airflow** to trigger Slack alerts, email alerts, or CRM updates whenever a verified sponsorship job matches your criteria.

---

## 🔍 SEO & Search Indexing
`visa sponsorship API`, `Greenhouse scraper`, `B2B lead gen`, `H-1B sponsor data`, `Lever jobs API`, `Ashby scraper`, `Workable jobs scraper`, `UK Skilled Worker register`, `visa sponsor database`, `recruiting intelligence API`, `tech jobs visa sponsorship`.

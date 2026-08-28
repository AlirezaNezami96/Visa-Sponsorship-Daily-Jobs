# Pay-Per-Event (PPE) Pricing Model

The **Visa Sponsorship Jobs Scraper & Intelligence API** uses Apify's **Pay-Per-Event (PPE)** monetization model. You only pay for verified, actionable data that matches your search criteria.

---

## 🎟️ Event Definitions

All events are charged atomically **before** delivery using strict Charge-Before-Push invariants:

| Event Name | Description | Trigger Condition |
| :--- | :--- | :--- |
| `job-result` | **Base Verified Job Result** | Triggered for each qualified job record delivered to your dataset. |
| `visa-enriched-job` | **Official Visa Registry Match** | Triggered when a job is confirmed against official government registries (UK Home Office Licensed Sponsors or US DOL LCA historical disclosures) or verified global tech sponsor programs. |
| `overseas-job` | **International Corridor / Overseas Expansion** | Triggered when jobs originate from specialized overseas manpower agencies, government overseas boards, or international migration channels. |
| `ai-classified-job` | **AI Role & Seniority Scoring** | Triggered only when LLM role evaluation (relevance score 0-100, stack extraction, and seniority analysis) is executed using your provided LLM API key. |

---

## 💰 Cost Estimation Matrix

Typical cost breakdown per **1,000 jobs**:

| Mode / Permutation | Typical Total Cost (per 1,000 Jobs) | Included Events | Recommended Use Case |
| :--- | :--- | :--- | :--- |
| **Standard Mode** | **$3.00 – $4.00** | `job-result` | General tech & remote job scraping from ATS platforms. |
| **Visa Verified** | **$5.00 – $6.50** | `job-result` + `visa-enriched-job` | Candidates and recruiters seeking verified UK/US visa sponsorship eligibility. |
| **Global Corridor** | **$6.50 – $8.00** | `job-result` + `visa-enriched-job` + `overseas-job` | International relocations and agency-sponsored roles (Europe, Gulf, Asia). |
| **Full Intelligence** | **$9.00 – $11.00** | `job-result` + `visa-enriched-job` + `overseas-job` + `ai-classified-job` | High-precision screening with deep AI role relevance scoring and tech-stack extraction. |

---

## 🛡️ Spending Protection & Zero-Liability Guarantees

1. **Atomic Charge-Before-Push**: Every record is billed before push. If your Apify Actor spending limit is reached, uncharged records are discarded immediately.
2. **Cross-Run Deduplication**: When `deduplicationAcrossRuns: true` is set, repeat daily/hourly runs skip previously billed jobs within your TTL (default: 30 days). You are **never double-billed** for identical jobs.
3. **Zero Operator LLM Liabilities**: AI classification requires a user-supplied API key (`llmApiKey`). If omitted, AI evaluation gracefully bypasses without error, and 0 `ai-classified-job` charges occur.

# VisaLane — Chrome Extension Legal & Terms of Service (ToS) Review

**Date:** September 2, 2026  
**Scope:** Phase 5 Browser Extension Architecture & Third-Party Platform Compliance (LinkedIn, Indeed)

---

## 1. Executive Summary & Policy Context

Operating a browser extension that annotates third-party job boards (such as LinkedIn and Indeed) carries specific legal and policy considerations. Both platforms maintain strict Terms of Service (ToS) designed to protect their proprietary data, prevent unauthorized scraping, and maintain control over their user experience.

This document details our analysis of LinkedIn's User Agreement and Indeed's Terms of Service, evaluates risk vectors (data extraction vs. local DOM augmentation), and establishes our architectural security boundary to maintain compliance and user privacy.

---

## 2. Platform Terms of Service Analysis

### 2.1 LinkedIn User Agreement (Section 8.2: "Don'ts")
* **Prohibitions:** LinkedIn explicitly forbids:
  1. Developing, supporting, or using software, devices, scripts, robots, or other means/processes (including crawlers, browser plugins, add-ons, or other technology) to **scrape** the Services or copy profiles and data.
  2. Overriding security features or bypassing access controls.
  3. Modifying the platform's appearance or functionality in ways that deceive users.
* **Precedents & Enforcement Posture:** LinkedIn has historically litigated against unauthorized bulk data scrapers (e.g., *hiQ Labs v. LinkedIn*). While pure client-side assist tools (such as password managers, accessibility tools, and single-card annotators) are widely tolerated, any tool that executes automated bulk paging or profile harvesting faces aggressive enforcement.

### 2.2 Indeed Terms of Service & Site Rules
* **Prohibitions:** Indeed prohibits:
  1. Automated querying, indexing, or scraping of job postings without explicit contractual permission.
  2. Altering Indeed's core job application flow or intercepting candidate submissions.
* **Posture:** Local client-side inspection of visible job metadata for personal applicant assistance is standard across career extensions.

---

## 3. Technical Safeguards & Compliant Architecture

To prevent violating platform rules and avoid triggering bot detection, the VisaLane Extension adheres to the following architectural constraints:

| Design Concern | Prohibited Pattern (Risk) | VisaLane Implementation (Compliant) |
| :--- | :--- | :--- |
| **Data Extraction** | Automated feed crawling, saving platform profiles/jobs to an external database. | **Zero Scraping:** Reads only the single company name string visible on the active card to perform a lookup against VisaLane's independent database. |
| **Execution Context** | Injected scripts calling external APIs from within the host page DOM execution context. | **Isolated Background Service Worker:** Network requests are routed through the extension's background service worker via Chrome `host_permissions`. Host page scripts cannot inspect or intercept API traffic. |
| **DOM Footprint** | Altering host page layout, modifying native application buttons. | **Shadow DOM Badge:** Inserts an isolated, non-disruptive badge (`<visalane-badge>`) adjacent to the employer name. |
| **Request Rate** | Scripted rapid queries scraping thousands of employers. | **Passive User-Driven Lookups:** Lookups only occur as the human user manually scrolls or views an employer. Rate limited to 120 requests/minute. |

---

## 4. Operational Conclusion & Recommendation

The VisaLane Chrome Extension functions strictly as a **client-side annotation and decision-support overlay** using VisaLane's own proprietary sponsorship database. It does not extract, re-index, or harvest data from LinkedIn or Indeed. 

By routing all lookups through the extension's background service worker and isolating UI elements within Shadow DOM, we minimize exposure and adhere to platform guidelines.

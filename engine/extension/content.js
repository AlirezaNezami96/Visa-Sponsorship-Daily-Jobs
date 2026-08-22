/**
 * content.js — Job Description Scraper
 *
 * Injected into job listing pages across all platforms (LinkedIn, Indeed,
 * Greenhouse, Lever, Ashby, Workday, SAP SuccessFactors, SmartRecruiters,
 * BambooHR, Personio, NoFluffJobs, JustJoin.it, Taleo, etc.).
 *
 * Extracts clean job description text, job title, and company name.
 * Manifest V3 compliant.
 */

'use strict';

// ── Job Description Selectors ─────────────────────────────────────────────────
// Ordered from most-specific to most-generic. First match with > 100 chars wins.

const JD_SELECTORS = [
  // Schema.org Microdata & Universal JobPosting specs (used by SuccessFactors, Google Jobs, etc.)
  '[itemprop="description"]',
  '[itemtype*="JobPosting"]',
  '.jobDisplay',
  '.jobDisplayShell',
  '[data-careersite-propertyid="description"]',

  // Greenhouse
  '#content .job__description',
  '.job-post__description',
  '#app-body',

  // Lever
  '.posting-description',
  '.section-wrapper.page-full-width',
  '.section-wrapper',

  // LinkedIn
  '.jobs-description__content',
  '.jobs-description-content__text',
  '.jobs-box__html-content',
  '#job-details',

  // Indeed
  '#jobDescriptionText',
  '.jobsearch-jobDescriptionText',
  '.jobsearch-JobComponent-description',

  // Ashby
  '[data-testid="job-description"]',
  '.ashby-job-posting-description',
  '._jobDescription_11w28_1',

  // Workday
  '[data-automation-id="jobPostingDescription"]',
  '[data-automation-id="job-posting-details"]',
  '.css-11y9s8l',

  // SmartRecruiters
  '.job-sections',
  '.job-detail',
  'st-job-detail',
  '[data-qa="job-detail"]',

  // JustJoin.it & NoFluffJobs
  '.JobDetailsComponent',
  '[data-testid="job-details"]',
  '[data-cy="job-requirements"]',
  'nfj-postings-details',
  'section.posting-details-description',

  // BambooHR & Personio
  '.pos-description',
  '#BambooHR-ATS-Jobs',
  '[data-test="job-description"]',

  // Teamtailor & Recruitee
  '.body--job',
  '.section--description',
  '.offer-description',

  // Wellfound / AngelList
  '.styles_description__R-qJX',
  '.job-description',

  // Taleo / Oracle Cloud
  '#requisitionDescriptionInterface',
  '.masterPageTable',

  // Broad semantic fallbacks
  '[class*="job-description"]',
  '[class*="jobDescription"]',
  '[class*="job_description"]',
  '[class*="job-details"]',
  '[class*="jobDetails"]',
  '[class*="job-content"]',
  '[class*="jobContent"]',
  '[class*="job-posting"]',
  '[class*="jobPosting"]',
  '[class*="joblayouttoken"]',
  '[id*="job-description"]',
  '[id*="jobDescription"]',
  '[id*="job_description"]',
  '[id*="job-details"]',
  '[id*="jobDetails"]',
  'article.job',
  'article',
  'main',
];

// ── Metadata Selectors ────────────────────────────────────────────────────────

const TITLE_SELECTORS = [
  // Microdata
  '[itemprop="title"]',
  '[data-careersite-propertyid="title"]',
  // Lever & Greenhouse
  'h1.posting-headline',
  'h1.app-title',
  // Ashby & Indeed & LinkedIn
  'h1[data-testid="job-title"]',
  '.jobs-unified-top-card__job-title',
  '.job-details-jobs-unified-top-card__job-title',
  '[data-testid="jobsearch-JobInfoHeader-title"]',
  'h1.jobsearch-JobInfoHeader-title',
  '.jobTitle h1',
  'h1',
];

const COMPANY_SELECTORS = [
  // Microdata & SuccessFactors
  '[data-careersite-propertyid="dept"]',
  '[itemprop="hiringOrganization"]',
  // LinkedIn
  '.jobs-unified-top-card__company-name',
  '.job-details-jobs-unified-top-card__company-name',
  // Indeed
  '[data-testid="jobsearch-CompanyInfoContainer"] a',
  '[data-company-name="true"]',
  // Lever & Greenhouse
  'h2.posting-categories',
  '[data-automation-id="company-name"]',
  '.company-name',
  '[class*="company-name"]',
  '[class*="companyName"]',
  'meta[property="og:site_name"]',
  'h2',
];

// ── Utility Functions ─────────────────────────────────────────────────────────

function cleanText(text) {
  return (text || '')
    .replace(/\r/g, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n\s*\n\s*\n+/g, '\n\n')
    .trim();
}

function queryFirst(selectors, minLength = 20) {
  for (const sel of selectors) {
    try {
      const el = document.querySelector(sel);
      if (el) {
        const text = el.innerText || el.textContent || '';
        if (text.trim().length >= minLength) return el;
      }
    } catch (_) { /* skip invalid selector */ }
  }
  return null;
}

/**
 * Fallback: Find the largest readable text container on the page
 * when standard selectors fail.
 */
function findLargestContentContainer() {
  const candidates = Array.from(document.querySelectorAll('div, section, article, main'));
  let bestCandidate = null;
  let maxScore = 0;

  for (const el of candidates) {
    // Skip headers, footers, navs
    const tag = el.tagName.toLowerCase();
    if (['nav', 'header', 'footer', 'script', 'style', 'noscript', 'aside'].includes(tag)) continue;

    const text = cleanText(el.innerText || '');
    if (text.length < 150) continue;

    // Score based on paragraphs, lists, and keywords
    const pCount = el.querySelectorAll('p, li').length;
    const hasJobKeywords = /requirements|responsibilities|qualifications|about the role|skills|experience/i.test(text);
    const score = text.length + (pCount * 100) + (hasJobKeywords ? 1000 : 0);

    if (score > maxScore && text.length < 50000) {
      maxScore = score;
      bestCandidate = el;
    }
  }

  return bestCandidate;
}

function extractJobDescription() {
  // 1. Try known ATS selectors
  const el = queryFirst(JD_SELECTORS, 80);
  if (el) {
    const text = cleanText(el.innerText || el.textContent || '');
    if (text.length >= 80) return text;
  }

  // 2. Try largest content container fallback
  const fallbackEl = findLargestContentContainer();
  if (fallbackEl) {
    const text = cleanText(fallbackEl.innerText || fallbackEl.textContent || '');
    if (text.length >= 80) return text;
  }

  // 3. Last resort: body text if sufficiently detailed
  const bodyText = cleanText(document.body.innerText || '');
  if (bodyText.length >= 200 && /requirements|responsibilities|qualifications|experience/i.test(bodyText)) {
    return bodyText.slice(0, 10000);
  }

  return null;
}

function extractTitle() {
  const el = queryFirst(TITLE_SELECTORS, 3);
  if (el) {
    const t = cleanText(el.innerText || el.textContent || '');
    // Clean up trailing "Job Details", "Apply now", etc.
    const cleanTitle = t.replace(/\s*(?:Job Details|Apply now|»|\|).*$/i, '').trim();
    if (cleanTitle.length > 2) return cleanTitle;
  }

  // Fallback: document.title
  const rawTitle = document.title || '';
  const parts = rawTitle.split(/[-|–—•]/);
  return cleanText(parts[0] || rawTitle);
}

function extractCompany() {
  // 1. Specific company selectors
  const el = queryFirst(COMPANY_SELECTORS, 2);
  if (el) {
    const val = el.getAttribute('content') || el.innerText || el.textContent || '';
    const cleaned = cleanText(val).replace(/^Company:\s*/i, '').trim();
    if (cleaned.length > 1 && cleaned.length < 60) return cleaned;
  }

  // 2. Meta tag og:site_name
  const metaSite = document.querySelector('meta[property="og:site_name"], meta[name="author"]');
  if (metaSite && metaSite.content) {
    return cleanText(metaSite.content);
  }

  // 3. LinkedIn URL pattern
  const linkedinMatch = window.location.href.match(/\/company\/([^\/]+)\//);
  if (linkedinMatch) return decodeURIComponent(linkedinMatch[1]).replace(/-/g, ' ');

  // 4. Subdomain matching: careers.allegro.eu -> Allegro, foo.greenhouse.io -> foo
  const host = window.location.hostname;
  const parts = host.split('.');
  if (parts.length >= 2) {
    if (parts[0] === 'careers' || parts[0] === 'jobs' || parts[0] === 'career') {
      const companyDomain = parts[1];
      return companyDomain.charAt(0).toUpperCase() + companyDomain.slice(1);
    }
    if (parts.length >= 3 && (parts[1] === 'greenhouse' || parts[1] === 'lever' || parts[1] === 'workday' || parts[1] === 'smartrecruiters')) {
      return parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
    }
  }

  return '';
}

// ── Form Autofill Assist (Non-Submitting) ───────────────────────────────────

function autofillApplicationForm(candidateData) {
  if (!candidateData) return { count: 0 };
  let filledCount = 0;

  const setInputValue = (input, value) => {
    if (!input || !value) return;
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    filledCount++;
  };

  const inputs = Array.from(document.querySelectorAll('input, textarea, select'));

  for (const el of inputs) {
    const name = (el.name || '').toLowerCase();
    const id = (el.id || '').toLowerCase();
    const placeholder = (el.placeholder || '').toLowerCase();
    const label = (el.labels && el.labels[0] ? el.labels[0].textContent : '').toLowerCase();
    const combined = `${name} ${id} ${placeholder} ${label}`;

    // Full name
    if (combined.includes('full name') || (combined.includes('name') && !combined.includes('first') && !combined.includes('last') && !combined.includes('company'))) {
      if (candidateData.full_name) setInputValue(el, candidateData.full_name);
    }
    // First name
    else if (combined.includes('first name') || combined.includes('firstname') || combined.includes('fname')) {
      const first = (candidateData.full_name || '').split(' ')[0];
      if (first) setInputValue(el, first);
    }
    // Last name
    else if (combined.includes('last name') || combined.includes('lastname') || combined.includes('lname')) {
      const parts = (candidateData.full_name || '').split(' ');
      const last = parts.length > 1 ? parts.slice(1).join(' ') : '';
      if (last) setInputValue(el, last);
    }
    // Email
    else if (combined.includes('email') || el.type === 'email') {
      if (candidateData.email) setInputValue(el, candidateData.email);
    }
    // Phone
    else if (combined.includes('phone') || combined.includes('mobile') || combined.includes('tel') || el.type === 'tel') {
      if (candidateData.phone) setInputValue(el, candidateData.phone);
    }
    // LinkedIn
    else if (combined.includes('linkedin')) {
      if (candidateData.linkedin) setInputValue(el, candidateData.linkedin);
    }
    // GitHub
    else if (combined.includes('github') || combined.includes('git')) {
      if (candidateData.github) setInputValue(el, candidateData.github);
    }
    // Portfolio / Website
    else if (combined.includes('portfolio') || combined.includes('website') || combined.includes('url')) {
      if (candidateData.portfolio) setInputValue(el, candidateData.portfolio);
    }
    // Location / City
    else if (combined.includes('location') || combined.includes('city') || combined.includes('address')) {
      if (candidateData.location) setInputValue(el, candidateData.location);
    }
    // Visa sponsorship screening questions (Honest answers)
    else if (combined.includes('sponsorship') || combined.includes('visa') || combined.includes('authorized')) {
      if (combined.includes('require') || combined.includes('need') || combined.includes('future')) {
        // Will you require sponsorship? -> Yes
        if (el.tagName === 'SELECT') {
          for (const opt of el.options) {
            if (opt.text.toLowerCase().includes('yes') || opt.value.toLowerCase().includes('yes')) {
              el.value = opt.value;
              el.dispatchEvent(new Event('change', { bubbles: true }));
              filledCount++;
              break;
            }
          }
        } else if (el.type === 'radio' && el.value.toLowerCase().includes('yes')) {
          el.checked = true;
          el.dispatchEvent(new Event('change', { bubbles: true }));
          filledCount++;
        }
      }
    }
  }

  return { count: filledCount };
}

// ── Message Handler ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'EXTRACT_JD') {
    try {
      const jdText = extractJobDescription();
      if (!jdText || jdText.length < 60) {
        sendResponse({
          success: false,
          error: 'Could not find a job description on this page. Try scrolling to the full description.',
        });
        return true;
      }

      sendResponse({
        success: true,
        jobDescription: jdText,
        jobTitle: extractTitle(),
        companyName: extractCompany(),
        pageUrl: window.location.href,
        charCount: jdText.length,
      });
    } catch (err) {
      sendResponse({
        success: false,
        error: `Extraction error: ${err.message}`,
      });
    }
    return true;
  }

  if (message.action === 'AUTOFILL_FORM') {
    try {
      const res = autofillApplicationForm(message.candidateData);
      sendResponse({ success: true, filledFields: res.count });
    } catch (err) {
      sendResponse({ success: false, error: err.message });
    }
    return true;
  }

  return true;
});

// Broadcast readiness & initialize Copilot on apply pages
try {
  chrome.runtime.sendMessage({ action: 'CONTENT_READY', url: window.location.href });
} catch (_) { /* Background worker might be inactive */ }

// Initialize Job OS Copilot Overlay on apply forms
(async () => {
  try {
    const isApplyForm = (
      window.location.href.includes('/apply') ||
      window.location.href.includes('/application') ||
      window.location.hostname.includes('myworkdayjobs.com') ||
      document.querySelector('#application_form, .application-form, [data-testid="application-form"], [data-automation-id="workdayApplication"]') !== null
    );

    if (isApplyForm) {
      const src = chrome.runtime.getURL('autofill/engine.js');
      const { detectAndMountAutofill } = await import(src);
      detectAndMountAutofill();
    }
  } catch (err) {
    console.debug('Job OS Copilot mount skipped or delayed:', err);
  }
})();

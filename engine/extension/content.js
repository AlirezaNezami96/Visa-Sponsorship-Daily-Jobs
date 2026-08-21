/**
 * content.js — Job Description Scraper
 *
 * Injected into job listing pages. Extracts the job description text and
 * metadata (company name, job title, URL) from the page DOM.
 * Communicates with background.js via chrome.runtime.onMessage.
 *
 * Manifest V3 compliant.
 */

'use strict';

// ── Job Description Selectors ─────────────────────────────────────────────────
// Ordered from most-specific to most-generic. First match wins.

const JD_SELECTORS = [
  // Greenhouse
  '#content .job__description',
  '.job-post__description',
  // Lever
  '.posting-description',
  '.section-wrapper',
  // LinkedIn
  '.jobs-description__content',
  '.jobs-description-content__text',
  // Indeed
  '#jobDescriptionText',
  '.jobsearch-jobDescriptionText',
  // Ashby
  '[data-testid="job-description"]',
  '.ashby-job-posting-description',
  // Workday
  '[data-automation-id="jobPostingDescription"]',
  // JustJoin.it
  '.JobDetailsComponent',
  '[data-testid="job-details"]',
  // SmartRecruiters
  '.job-sections',
  // Wellfound / AngelList
  '.styles_description__R-qJX',
  '.job-description',
  // Generic fallbacks
  '[class*="job-description"]',
  '[class*="jobDescription"]',
  '[id*="job-description"]',
  'article.job',
  'main',
];

// ── Metadata Selectors ────────────────────────────────────────────────────────

const TITLE_SELECTORS = [
  'h1.posting-headline',       // Lever
  'h1.app-title',              // Greenhouse
  'h1[data-testid="job-title"]',
  '.jobs-unified-top-card__job-title',  // LinkedIn
  '[data-testid="jobsearch-JobInfoHeader-title"]',  // Indeed
  'h1.jobsearch-JobInfoHeader-title',
  'h1',
];

const COMPANY_SELECTORS = [
  '.jobs-unified-top-card__company-name',  // LinkedIn
  '[data-testid="jobsearch-CompanyInfoContainer"] a',  // Indeed
  'h2.posting-categories',
  '[data-automation-id="company-name"]',
  '.company-name',
  '[class*="company-name"]',
  'h2',
];

// ── Utility Functions ─────────────────────────────────────────────────────────

function queryFirst(selectors) {
  for (const sel of selectors) {
    try {
      const el = document.querySelector(sel);
      if (el && el.innerText && el.innerText.trim().length > 20) return el;
    } catch (_) { /* invalid selector — skip */ }
  }
  return null;
}

function cleanText(text) {
  return (text || '')
    .replace(/\s+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function extractJobDescription() {
  const el = queryFirst(JD_SELECTORS);
  if (!el) return null;
  return cleanText(el.innerText);
}

function extractTitle() {
  const el = queryFirst(TITLE_SELECTORS);
  return cleanText(el?.innerText || document.title || '');
}

function extractCompany() {
  const el = queryFirst(COMPANY_SELECTORS);
  if (el) return cleanText(el.innerText);

  // LinkedIn: extract from URL pattern /company/{name}/
  const linkedinMatch = window.location.href.match(/\/company\/([^\/]+)\//);
  if (linkedinMatch) return decodeURIComponent(linkedinMatch[1]).replace(/-/g, ' ');

  // Greenhouse: domain is {company}.greenhouse.io
  const ghMatch = window.location.hostname.match(/^(.+)\.greenhouse\.io$/);
  if (ghMatch) return ghMatch[1].replace(/-/g, ' ');

  return '';
}

// ── Message Handler ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action !== 'EXTRACT_JD') return;

  const jdText = extractJobDescription();
  if (!jdText || jdText.length < 80) {
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

  return true; // Keep message channel open for async sendResponse
});

// Let the popup know this content script is ready
chrome.runtime.sendMessage({ action: 'CONTENT_READY', url: window.location.href });

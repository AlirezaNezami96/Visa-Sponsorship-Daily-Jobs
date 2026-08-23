/**
 * workday.js — Workday ATS Multi-Page Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class WorkdayAdapter extends BaseAtsAdapter {
  constructor() {
    super('workday', 'Workday');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('myworkdayjobs.com') ||
      host.includes('myworkday.com') ||
      host.includes('myworkdaysite.com') ||
      doc.querySelector('[data-automation-id="workdayApplication"], [data-automation-id="legalNameSection"]') !== null
    );
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['[data-automation-id="legalNameSection_firstName"]', 'input[data-automation-id*="firstName"]'] },
      last_name: { selectors: ['[data-automation-id="legalNameSection_lastName"]', 'input[data-automation-id*="lastName"]'] },
      email: { selectors: ['[data-automation-id="email"]', 'input[data-automation-id*="email"]'] },
      phone: { selectors: ['[data-automation-id="phone-number"]', 'input[data-automation-id*="phone"]'] },
      address_line1: { selectors: ['[data-automation-id="addressSection_addressLine1"]'] },
      city: { selectors: ['[data-automation-id="addressSection_city"]', '[data-automation-id*="city"]'] },
      postal_code: { selectors: ['[data-automation-id="addressSection_postalCode"]'] },
      country: { selectors: ['[data-automation-id="addressSection_countryRegion"]', '[data-automation-id*="country"]'] },
      linkedin_url: { selectors: ['[data-automation-id*="linkedin"]', 'input[data-automation-id*="LinkedIn"]'] },
      github_url: { selectors: ['[data-automation-id*="github"]', 'input[data-automation-id*="GitHub"]'] },
      portfolio_url: { selectors: ['[data-automation-id*="website"]', 'input[data-automation-id*="portfolio"]'] },
      resume_file: { selectors: ['[data-automation-id="file-upload-drop-zone"] input[type="file"]', 'input[data-automation-id*="resume"]'] },
    };
  }

  getFormContainer(doc = document) {
    return doc.querySelector('[data-automation-id="workdayApplication"]') || doc.body;
  }

  getNextPageButton(doc = document) {
    return (
      doc.querySelector('[data-automation-id="bottom-navigation-next-button"]') ||
      doc.querySelector('button[data-automation-id*="next"]') ||
      doc.querySelector('button[data-automation-id*="saveAndContinue"]')
    );
  }

  getJobContext(doc = document) {
    return {
      jobTitle: doc.querySelector('[data-automation-id="jobPostingHeader"]')?.textContent?.trim() || '',
      company: doc.querySelector('[data-automation-id="companyName"]')?.textContent?.trim() || '',
    };
  }
}

/**
 * ashby.js — Ashby ATS Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class AshbyAdapter extends BaseAtsAdapter {
  constructor() {
    super('ashby', 'Ashby');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('ashbyhq.com') ||
      doc.querySelector('[data-testid="application-form"], .ashby-application-form') !== null
    );
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['input[name="firstName"]', '[data-testid="field-firstName"] input'] },
      last_name: { selectors: ['input[name="lastName"]', '[data-testid="field-lastName"] input'] },
      email: { selectors: ['input[name="email"]', '[data-testid="field-email"] input'] },
      phone: { selectors: ['input[name="phone"]', '[data-testid="field-phone"] input'] },
      resume_file: { selectors: ['[data-testid="field-resume"] input[type="file"]', 'input[name="resume"]'] },
      linkedin_url: { selectors: ['input[name*="linkedin"]', '[data-testid*="linkedin"] input'] },
      github_url: { selectors: ['input[name*="github"]', '[data-testid*="github"] input'] },
      portfolio_url: { selectors: ['input[name*="website"]', 'input[name*="portfolio"]'] },
    };
  }

  getFormContainer(doc = document) {
    return doc.querySelector('[data-testid="application-form"], form') || doc.body;
  }

  getJobContext(doc = document) {
    return {
      jobTitle: doc.querySelector('h1[data-testid="job-title"], h1')?.textContent?.trim() || '',
      company: doc.querySelector('.ashby-job-posting-company-name')?.textContent?.trim() || '',
    };
  }
}

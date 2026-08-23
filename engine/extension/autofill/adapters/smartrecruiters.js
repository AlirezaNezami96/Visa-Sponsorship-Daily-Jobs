/**
 * smartrecruiters.js — SmartRecruiters ATS Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class SmartRecruitersAdapter extends BaseAtsAdapter {
  constructor() {
    super('smartrecruiters', 'SmartRecruiters');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('smartrecruiters.com') ||
      doc.querySelector('.job-sections, st-apply, [data-qa="job-detail"]') !== null
    );
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['input[name="firstName"]', '#first-name-input', 'input[data-qa="first-name"]'] },
      last_name: { selectors: ['input[name="lastName"]', '#last-name-input', 'input[data-qa="last-name"]'] },
      email: { selectors: ['input[name="email"]', '#email-input', 'input[data-qa="email"]'] },
      phone: { selectors: ['input[name="phoneNumber"]', '#phone-number-input', 'input[data-qa="phone-number"]'] },
      city: { selectors: ['input[name="city"]', 'input[data-qa="city"]', '#location-input'] },
      resume_file: { selectors: ['input[type="file"][data-qa="resume-upload"]', 'input[type="file"]'] },
      linkedin_url: { selectors: ['input[name*="linkedin"]', 'input[data-qa*="linkedin"]'] },
    };
  }

  getJobContext(doc = document) {
    return {
      jobTitle: doc.querySelector('h1.job-title, [data-qa="job-title"]')?.textContent?.trim() || '',
      company: doc.querySelector('.company-name, [data-qa="company-name"]')?.textContent?.trim() || '',
    };
  }
}

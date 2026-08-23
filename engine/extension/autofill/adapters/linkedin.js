/**
 * linkedin.js — LinkedIn Easy Apply Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class LinkedInAdapter extends BaseAtsAdapter {
  constructor() {
    super('linkedin', 'LinkedIn Easy Apply');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('linkedin.com') &&
      doc.querySelector('.jobs-easy-apply-modal, .jobs-easy-apply-content, [data-easy-apply-modal]') !== null
    );
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['input[id*="firstName"]', 'input[name*="firstName"]'] },
      last_name: { selectors: ['input[id*="lastName"]', 'input[name*="lastName"]'] },
      email: { selectors: ['input[id*="email"]', 'select[id*="email"]'] },
      phone: { selectors: ['input[id*="phoneNumber-nationalNumber"]', 'input[id*="phoneNumber"]', 'input[type="tel"]'] },
      city: { selectors: ['input[id*="city"]', 'input[id*="location"]'] },
      resume_file: { selectors: ['input[type="file"][id*="resume"]', 'input[type="file"]'] },
    };
  }

  getFormContainer(doc = document) {
    return doc.querySelector('.jobs-easy-apply-modal, .jobs-easy-apply-content') || doc.body;
  }

  getNextPageButton(doc = document) {
    return doc.querySelector('button[aria-label="Continue to next step"], button[aria-label="Review your application"]');
  }
}

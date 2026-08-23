/**
 * indeed.js — Indeed Apply Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class IndeedAdapter extends BaseAtsAdapter {
  constructor() {
    super('indeed', 'Indeed Apply');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('indeed.com') &&
      doc.querySelector('#ia-container, .ia-JobApplication, [data-testid="ia-container"]') !== null
    );
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['#input-firstName', 'input[name="firstName"]'] },
      last_name: { selectors: ['#input-lastName', 'input[name="lastName"]'] },
      full_name: { selectors: ['#input-applicant\\.name', 'input[name*="name"]'] },
      email: { selectors: ['#input-applicant\\.email', 'input[type="email"]'] },
      phone: { selectors: ['#input-applicant\\.phoneNumber', 'input[type="tel"]'] },
      city: { selectors: ['#input-applicant\\.location', 'input[name*="location"]'] },
      resume_file: { selectors: ['input[type="file"][id*="resume"]', 'input[type="file"]'] },
    };
  }

  getNextPageButton(doc = document) {
    return doc.querySelector('button[data-testid="ia-continue-button"], button.ia-continueButton');
  }
}

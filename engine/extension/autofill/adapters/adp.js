/**
 * adp.js — ADP Workforce Now / Career Center Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class AdpAdapter extends BaseAtsAdapter {
  constructor() {
    super('adp', 'ADP');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('adp.com') ||
      doc.querySelector('.adp-career-center, [id*="adp"]') !== null
    );
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['input[id*="FirstName"]', 'input[name*="firstName"]'] },
      last_name: { selectors: ['input[id*="LastName"]', 'input[name*="lastName"]'] },
      email: { selectors: ['input[id*="Email"]', 'input[type="email"]'] },
      phone: { selectors: ['input[id*="Phone"]', 'input[type="tel"]'] },
      postal_code: { selectors: ['input[id*="PostalCode"]', 'input[id*="Zip"]'] },
      resume_file: { selectors: ['input[type="file"]'] },
    };
  }

  getNextPageButton(doc = document) {
    return doc.querySelector('button[id*="next"], input[value="Next"]');
  }
}

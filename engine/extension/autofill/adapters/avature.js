/**
 * avature.js — Avature ATS Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class AvatureAdapter extends BaseAtsAdapter {
  constructor() {
    super('avature', 'Avature');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('avature.net') ||
      doc.querySelector('.avature-form, [id*="avature"]') !== null
    );
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['input[name*="FirstName"]', 'input[id*="firstName"]'] },
      last_name: { selectors: ['input[name*="LastName"]', 'input[id*="lastName"]'] },
      email: { selectors: ['input[name*="Email"]', 'input[type="email"]'] },
      phone: { selectors: ['input[name*="Phone"]', 'input[type="tel"]'] },
      city: { selectors: ['input[name*="City"]', 'input[name*="Location"]'] },
      resume_file: { selectors: ['input[type="file"][name*="resume"]', 'input[type="file"]'] },
    };
  }

  getNextPageButton(doc = document) {
    return doc.querySelector('button[name="next"], input[value="Next"], .btn-next');
  }
}

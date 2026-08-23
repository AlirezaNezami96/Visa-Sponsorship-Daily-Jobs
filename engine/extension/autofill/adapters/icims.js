/**
 * icims.js — iCIMS Portal ATS Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class IcimsAdapter extends BaseAtsAdapter {
  constructor() {
    super('icims', 'iCIMS');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('icims.com') ||
      doc.querySelector('.iCIMS_JobContent, iframe[src*="icims.com"], .icims-app') !== null
    );
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['#rcm-first-name', 'input[name="rcm-first-name"]', '#firstName'] },
      last_name: { selectors: ['#rcm-last-name', 'input[name="rcm-last-name"]', '#lastName'] },
      email: { selectors: ['#rcm-email', 'input[name="rcm-email"]', '#email'] },
      phone: { selectors: ['#rcm-phone', 'input[name="rcm-phone"]', '#phone'] },
      address_line1: { selectors: ['#rcm-address', 'input[name="rcm-address"]'] },
      city: { selectors: ['#rcm-city', 'input[name="rcm-city"]'] },
      postal_code: { selectors: ['#rcm-zip', 'input[name="rcm-zip"]'] },
      country: { selectors: ['#rcm-country', 'select[name="rcm-country"]'] },
      resume_file: { selectors: ['input[type="file"][name*="resume"]', 'input[type="file"]'] },
    };
  }

  getNextPageButton(doc = document) {
    return doc.querySelector('#rcm-next, input[value="Next"], input[value="Submit Profile"]');
  }
}

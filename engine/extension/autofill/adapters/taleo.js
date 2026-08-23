/**
 * taleo.js — Oracle Cloud / Taleo ATS Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class TaleoAdapter extends BaseAtsAdapter {
  constructor() {
    super('taleo', 'Taleo / Oracle Cloud');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('taleo.net') ||
      host.includes('oraclecloud.com') ||
      doc.querySelector('#requisitionDescriptionInterface, .masterPageTable') !== null
    );
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['input[id*="FirstName"]', 'input[name*="FirstName"]'] },
      last_name: { selectors: ['input[id*="LastName"]', 'input[name*="LastName"]'] },
      email: { selectors: ['input[id*="Email"]', 'input[type="email"]'] },
      phone: { selectors: ['input[id*="Phone"]', 'input[id*="CellPhone"]'] },
      address_line1: { selectors: ['input[id*="Address"]', 'input[id*="Street"]'] },
      city: { selectors: ['input[id*="City"]'] },
      postal_code: { selectors: ['input[id*="Zip"]', 'input[id*="PostalCode"]'] },
      resume_file: { selectors: ['input[type="file"][id*="Resume"]', 'input[type="file"]'] },
    };
  }

  getNextPageButton(doc = document) {
    return doc.querySelector('input[id*="Next"], button[id*="Next"], a[id*="Next"]');
  }
}

/**
 * generic.js — Universal Fallback ATS Adapter for Arbitrary Career Sites
 */

import { BaseAtsAdapter } from './base.js';

export class GenericAdapter extends BaseAtsAdapter {
  constructor() {
    super('generic', 'Universal Career Application');
  }

  matches(url, doc = document) {
    // Universal fallback always matches if an application form or resume input exists
    return true;
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['input[name*="first_name" i]', 'input[name*="firstName" i]', 'input[autocomplete="given-name"]'] },
      last_name: { selectors: ['input[name*="last_name" i]', 'input[name*="lastName" i]', 'input[autocomplete="family-name"]'] },
      full_name: { selectors: ['input[name*="full_name" i]', 'input[name="name" i]', 'input[autocomplete="name"]'] },
      email: { selectors: ['input[type="email"]', 'input[name*="email" i]'] },
      phone: { selectors: ['input[type="tel"]', 'input[name*="phone" i]', 'input[name*="mobile" i]'] },
      city: { selectors: ['input[name*="city" i]', 'input[name*="location" i]'] },
      postal_code: { selectors: ['input[name*="postal" i]', 'input[name*="zip" i]'] },
      resume_file: { selectors: ['input[type="file"][name*="resume" i]', 'input[type="file"][name*="cv" i]', 'input[type="file"]'] },
    };
  }

  getFormContainer(doc = document) {
    return doc.querySelector('form[action*="apply" i], form[action*="job" i], form') || doc.body;
  }
}

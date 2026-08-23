/**
 * lever.js — Lever ATS Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class LeverAdapter extends BaseAtsAdapter {
  constructor() {
    super('lever', 'Lever');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('lever.co') ||
      doc.querySelector('.application-form, .posting-header') !== null
    );
  }

  getFieldHints() {
    return {
      full_name: { selectors: ['input[name="name"]', '#name'] },
      email: { selectors: ['input[name="email"]', '#email'] },
      phone: { selectors: ['input[name="phone"]', '#phone'] },
      current_company: { selectors: ['input[name="org"]', '#org'] },
      linkedin_url: { selectors: ['input[name="urls[LinkedIn]"]', 'input[name*="linkedin"]'] },
      github_url: { selectors: ['input[name="urls[GitHub]"]', 'input[name*="github"]'] },
      portfolio_url: { selectors: ['input[name="urls[Portfolio]"]', 'input[name*="portfolio"]', 'input[name*="other"]'] },
      city: { selectors: ['input[name="location"]', '#location'] },
      resume_file: { selectors: ['input[name="resume"]', 'input[type="file"]'] },
      cover_letter_text: { selectors: ['textarea[name="comments"]', '#comments'] },
    };
  }

  getFormContainer(doc = document) {
    return doc.querySelector('.application-form, form#application-form') || doc.body;
  }

  getJobContext(doc = document) {
    return {
      jobTitle: doc.querySelector('.posting-headline h2')?.textContent?.trim() || '',
      company: doc.querySelector('.posting-headline .main-header-logo img')?.getAttribute('alt') || '',
    };
  }
}

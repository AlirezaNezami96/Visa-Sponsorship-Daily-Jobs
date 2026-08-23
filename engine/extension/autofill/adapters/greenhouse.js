/**
 * greenhouse.js — Greenhouse ATS Adapter
 */

import { BaseAtsAdapter } from './base.js';

export class GreenhouseAdapter extends BaseAtsAdapter {
  constructor() {
    super('greenhouse', 'Greenhouse');
  }

  matches(url, doc = document) {
    const host = (url ? new URL(url).hostname : window.location.hostname).toLowerCase();
    return (
      host.includes('greenhouse.io') ||
      doc.querySelector('#application_form, #apply_form, .job-post-form') !== null
    );
  }

  getFieldHints() {
    return {
      first_name: { selectors: ['#first_name', 'input[name="first_name"]', 'input[autocomplete="given-name"]'] },
      last_name: { selectors: ['#last_name', 'input[name="last_name"]', 'input[autocomplete="family-name"]'] },
      email: { selectors: ['#email', 'input[name="email"]', 'input[type="email"]'] },
      phone: { selectors: ['#phone', 'input[name="phone"]', 'input[type="tel"]'] },
      city: { selectors: ['#job_application_location', 'input[name*="location"]', '#location'] },
      resume_file: { selectors: ['#resume_file', 'input[data-qa="resume-upload"]', 'input[name="resume"]', 'input[type="file"]'] },
      cover_letter_file: { selectors: ['#cover_letter_file', 'input[name="cover_letter"]'] },
      cover_letter_text: { selectors: ['#cover_letter_text', 'textarea[name="cover_letter_text"]'] },
      linkedin_url: { selectors: ['input[name*="linkedin"]', 'input[name*="question_"][data-qa*="linkedin"]'] },
      github_url: { selectors: ['input[name*="github"]', 'input[name*="question_"][data-qa*="github"]'] },
      portfolio_url: { selectors: ['input[name*="website"]', 'input[name*="portfolio"]'] },
    };
  }

  getFormContainer(doc = document) {
    return doc.querySelector('#application_form, #apply_form') || doc.body;
  }

  getJobContext(doc = document) {
    return {
      jobTitle: doc.querySelector('.app-title, .job-title, h1')?.textContent?.trim() || '',
      company: doc.querySelector('.company-name, .logo-container')?.textContent?.trim() || '',
    };
  }
}

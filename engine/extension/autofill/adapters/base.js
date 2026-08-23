/**
 * base.js — Base ATS Adapter Interface
 */

export class BaseAtsAdapter {
  constructor(id, name) {
    this.id = id;
    this.name = name;
  }

  /**
   * Returns true if this adapter matches the current page context.
   */
  matches(url, doc = document) {
    return false;
  }

  /**
   * Returns custom selector overrides and field hints.
   */
  getFieldHints() {
    return {};
  }

  /**
   * Returns application form element or container.
   */
  getFormContainer(doc = document) {
    return doc.querySelector('form') || doc.body;
  }

  /**
   * Returns next page / continue button if multi-page.
   */
  getNextPageButton(doc = document) {
    return null;
  }

  /**
   * Detects if application has been submitted (Thank you / Success).
   */
  detectSubmissionState(doc = document) {
    const text = (doc.body?.innerText || '').toLowerCase();
    return (
      text.includes('application submitted') ||
      text.includes('thank you for applying') ||
      text.includes('we received your application') ||
      text.includes('application complete')
    );
  }

  /**
   * Extracts job context if available.
   */
  getJobContext(doc = document) {
    return null;
  }
}

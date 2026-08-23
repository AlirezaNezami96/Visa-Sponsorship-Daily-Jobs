/**
 * session.js — Application Session State Machine & Multi-Page Progression Manager
 */

export class ApplicationSession {
  constructor({
    sessionId = `session_${Date.now()}`,
    jobTitle = '',
    companyName = '',
    pageUrl = window.location.href,
  }) {
    this.sessionId = sessionId;
    this.jobTitle = jobTitle;
    this.companyName = companyName;
    this.pageUrl = pageUrl;
    this.pageIndex = 1;
    this.discoveredFields = [];
    this.filledFields = [];
    this.skippedFields = [];
    this.needsReviewFields = [];
    this.errors = [];
    this.status = 'detecting'; // 'detecting' | 'analyzing' | 'filling' | 'waiting_navigation' | 'review' | 'submitted' | 'stopped'
    this.isStopped = false;
  }

  startFilling() {
    this.status = 'filling';
    this.isStopped = false;
  }

  stop() {
    this.status = 'stopped';
    this.isStopped = true;
  }

  recordFill(field, valueUsed) {
    this.filledFields.push({ field, valueUsed, timestamp: Date.now() });
  }

  recordSkip(field, reason) {
    this.skippedFields.push({ field, reason, timestamp: Date.now() });
    if (field.isRequired || field.confidenceTier === 'AI_REVIEW') {
      this.needsReviewFields.push({ field, reason });
    }
  }

  validateForm(fields) {
    const invalidFields = [];
    for (const f of fields) {
      if (f.isRequired) {
        const val = f.element.value || '';
        if (!val.trim() && f.fieldType !== 'file' && f.fieldType !== 'checkbox') {
          invalidFields.push({ field: f, reason: 'Required field is empty' });
        }
      }
    }
    return invalidFields;
  }

  detectSubmissionState(doc = document) {
    const text = (doc.body?.innerText || '').toLowerCase();
    const isSubmitted =
      text.includes('application submitted') ||
      text.includes('thank you for applying') ||
      text.includes('we received your application') ||
      text.includes('application complete') ||
      text.includes('your application has been submitted');

    if (isSubmitted) {
      this.status = 'submitted';
    }
    return isSubmitted;
  }
}

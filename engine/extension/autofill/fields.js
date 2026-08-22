/**
 * fields.js — Form Field Classifier & Context Extractor
 */

export function getFieldDescriptor(el) {
  const name = (el.name || '').toLowerCase();
  const id = (el.id || '').toLowerCase();
  const placeholder = (el.placeholder || '').toLowerCase();
  const autocomplete = (el.getAttribute('autocomplete') || '').toLowerCase();
  const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
  const dataAutomationId = (el.getAttribute('data-automation-id') || '').toLowerCase();

  // Find associated label text
  let labelText = '';
  if (el.labels && el.labels[0]) {
    labelText = el.labels[0].textContent || '';
  } else {
    // Look for parent label or nearby text container
    const parentLabel = el.closest('label, .field, [data-automation-id*="formField"], .form-group');
    if (parentLabel) {
      labelText = parentLabel.textContent || '';
    }
  }
  labelText = labelText.toLowerCase().replace(/\s+/g, ' ').trim();

  const combined = `${name} ${id} ${placeholder} ${autocomplete} ${ariaLabel} ${dataAutomationId} ${labelText}`;

  return {
    el,
    name,
    id,
    type: (el.type || el.tagName).toLowerCase(),
    labelText,
    combined,
    isRequired: el.required || el.getAttribute('aria-required') === 'true' || labelText.includes('*'),
  };
}

export function classifyFieldType(field) {
  const c = field.combined;
  const label = field.labelText;

  // 1. Consent / Terms / GDPR
  if (
    field.type === 'checkbox' ||
    c.includes('agree') ||
    c.includes('consent') ||
    c.includes('terms') ||
    c.includes('privacy') ||
    c.includes('certify') ||
    c.includes('acknowledge') ||
    c.includes('gdpr') ||
    c.includes('data processing') ||
    c.includes('truthful') ||
    c.includes('accurate')
  ) {
    if (field.type === 'checkbox' || c.includes('checkbox') || c.includes('terms')) {
      return 'CONSENT';
    }
  }

  // 2. Files
  if (field.type === 'file' || c.includes('resume') || c.includes('cv') || c.includes('curriculum vitae')) {
    if (c.includes('cover') && c.includes('letter')) return 'FILE_COVER_LETTER';
    return 'FILE_RESUME';
  }
  if (field.type === 'file' && c.includes('cover')) {
    return 'FILE_COVER_LETTER';
  }

  // 3. Names
  if (c.includes('first name') || c.includes('firstname') || c.includes('given-name') || c.includes('fname')) return 'FIRST_NAME';
  if (c.includes('last name') || c.includes('lastname') || c.includes('family-name') || c.includes('lname') || c.includes('surname')) return 'LAST_NAME';
  if (c.includes('full name') || c.includes('fullname') || (c.includes('name') && !c.includes('company') && !c.includes('user') && !c.includes('file') && !c.includes('country') && !c.includes('school'))) return 'FULL_NAME';

  // 4. Contact
  if (c.includes('email') || field.type === 'email') return 'EMAIL';
  if (c.includes('phone country') || c.includes('country code') || c.includes('dialing code') || c.includes('dial code')) return 'PHONE_COUNTRY';
  if (c.includes('phone') || c.includes('mobile') || c.includes('telephone') || c.includes('tel') || field.type === 'tel') return 'PHONE';

  // 5. Links (Fixed: avoid false positive git on digital/legitimate, url on hourly)
  if (c.includes('linkedin')) return 'LINK_LINKEDIN';
  if (c.includes('github') || /\bgit\b/.test(c)) return 'LINK_GITHUB';
  if (c.includes('portfolio') || c.includes('personal site') || c.includes('blog') || (/\b(website|portfolio_url|web_url)\b/.test(c) && !c.includes('hourly'))) return 'LINK_PORTFOLIO';

  // 6. Address / Location
  if (c.includes('country') && !c.includes('phone')) return 'COUNTRY';
  if (c.includes('work location preference') || c.includes('remote preference') || c.includes('workplace preference')) return 'LOCATION_PREFERENCE';
  if (c.includes('city') || c.includes('location') || c.includes('where do you live') || c.includes('current location') || c.includes('residence')) return 'LOCATION_CITY';
  if (c.includes('postal') || c.includes('zip') || c.includes('postcode')) return 'POSTAL_CODE';
  if (c.includes('address line') || c.includes('street address')) return 'ADDRESS_LINE';

  // 7. Work Authorization & Sponsorship (Polarity handled in answerWorkAuth)
  if (
    c.includes('authorized') ||
    c.includes('authorisation') ||
    c.includes('sponsorship') ||
    c.includes('visa') ||
    c.includes('right to work') ||
    c.includes('work permit') ||
    c.includes('eligibility to work') ||
    c.includes('eligible to work') ||
    c.includes('immigration')
  ) {
    return 'WORK_AUTH';
  }

  // 8. EEO / Voluntary Disclosures
  if (c.includes('gender') || c.includes('sex') || c.includes('pronoun')) return 'EEO_GENDER';
  if (c.includes('ethnicity') || c.includes('race') || c.includes('hispanic') || c.includes('latino')) return 'EEO_ETHNICITY';
  if (c.includes('veteran')) return 'EEO_VETERAN';
  if (c.includes('disability') || c.includes('handicap')) return 'EEO_DISABILITY';
  if (c.includes('lgbtq') || c.includes('sexual orientation')) return 'EEO_LGBTQ';

  // 9. Compensation & Experience
  if (
    c.includes('salary') ||
    c.includes('compensation') ||
    c.includes('pay') ||
    c.includes('ctc') ||
    c.includes('wage') ||
    c.includes('stipend') ||
    c.includes('day rate') ||
    c.includes('b2b') ||
    c.includes('contractor rate') ||
    c.includes('remuneration') ||
    c.includes('desired rate') ||
    c.includes('hourly rate')
  ) {
    return 'SALARY_EXPECTATION';
  }

  if (c.includes('years of experience') || c.includes('years of') || c.includes('experience with')) return 'YEARS_EXPERIENCE';
  if (c.includes('hear about') || c.includes('source') || c.includes('how did you hear')) return 'HOW_HEARD';

  // 10. Free-text Unique Questions
  if (field.el.tagName === 'TEXTAREA' || field.type === 'textarea') return 'UNIQUE_FREE_TEXT';

  return 'UNKNOWN';
}

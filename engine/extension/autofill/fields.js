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

  // 1. Files
  if (field.type === 'file' || c.includes('resume') || c.includes('cv')) {
    if (c.includes('cover') && c.includes('letter')) return 'FILE_COVER_LETTER';
    return 'FILE_RESUME';
  }

  // 2. Names
  if (c.includes('first name') || c.includes('firstname') || c.includes('given-name') || c.includes('fname')) return 'FIRST_NAME';
  if (c.includes('last name') || c.includes('lastname') || c.includes('family-name') || c.includes('lname') || c.includes('surname')) return 'LAST_NAME';
  if (c.includes('full name') || c.includes('fullname') || (c.includes('name') && !c.includes('company') && !c.includes('user') && !c.includes('file'))) return 'FULL_NAME';

  // 3. Contact
  if (c.includes('email') || field.type === 'email') return 'EMAIL';
  if (c.includes('phone') || c.includes('mobile') || c.includes('telephone') || c.includes('tel') || field.type === 'tel') return 'PHONE';

  // 4. Links
  if (c.includes('linkedin')) return 'LINK_LINKEDIN';
  if (c.includes('github') || c.includes('git')) return 'LINK_GITHUB';
  if (c.includes('portfolio') || c.includes('website') || c.includes('personal site') || c.includes('blog') || c.includes('url')) return 'LINK_PORTFOLIO';

  // 5. Address
  if (c.includes('country')) return 'COUNTRY';
  if (c.includes('city') || c.includes('location')) return 'CITY';
  if (c.includes('postal') || c.includes('zip')) return 'POSTAL_CODE';

  // 6. Work Auth & Sponsorship
  if (c.includes('authorized to work in the united states') || c.includes('authorized to work in the u.s.') || c.includes('work authorization (us)')) return 'WORK_AUTH_US';
  if (c.includes('authorized to work in canada')) return 'WORK_AUTH_CA';
  if (c.includes('authorized to work in the united kingdom') || c.includes('authorized to work in the uk')) return 'WORK_AUTH_UK';
  if (c.includes('sponsorship') || c.includes('require visa') || c.includes('visa sponsorship') || c.includes('immigration status')) return 'SPONSORSHIP_REQUIRED';
  if (c.includes('legally authorized') || c.includes('right to work') || c.includes('work permit')) return 'WORK_AUTH_GENERAL';

  // 7. EEO / Voluntary Disclosures
  if (c.includes('gender') || c.includes('sex')) return 'EEO_GENDER';
  if (c.includes('ethnicity') || c.includes('race') || c.includes('hispanic') || c.includes('latino')) return 'EEO_ETHNICITY';
  if (c.includes('veteran')) return 'EEO_VETERAN';
  if (c.includes('disability') || c.includes('handicap')) return 'EEO_DISABILITY';
  if (c.includes('lgbtq') || c.includes('sexual orientation')) return 'EEO_LGBTQ';

  // 8. Compensation & Preferences
  if (c.includes('salary') || c.includes('compensation') || c.includes('expected pay') || c.includes('desired pay')) return 'SALARY_EXPECTATION';
  if (c.includes('years of experience') || c.includes('years of') || c.includes('experience with')) return 'YEARS_EXPERIENCE';
  if (c.includes('hear about') || c.includes('source') || c.includes('how did you')) return 'HOW_HEARD';

  // 9. Free-text Unique Questions
  if (field.el.tagName === 'TEXTAREA' || field.type === 'textarea') return 'UNIQUE_FREE_TEXT';

  return 'UNKNOWN';
}

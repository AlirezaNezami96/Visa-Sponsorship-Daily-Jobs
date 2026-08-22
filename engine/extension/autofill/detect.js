/**
 * detect.js — Robust Application Form Detector
 *
 * Inspects DOM for real application forms (Greenhouse, Lever, Ashby, Workday, LinkedIn, or generic career forms).
 */

export function isApplicationFormPresent(doc = document) {
  // 1. Known ATS container selectors
  if (doc.querySelector('#application_form, #apply_form, .application-form, [data-testid="application-form"]')) {
    return true;
  }
  if (doc.querySelector('[data-automation-id="workdayApplication"], [data-automation-id="legalNameSection"]')) {
    return true;
  }
  if (doc.querySelector('.jobs-easy-apply-modal, .jobs-easy-apply-content')) {
    return true;
  }
  if (doc.querySelector('form[action*="apply"], form[action*="application"], form[class*="apply"]')) {
    return true;
  }

  // 2. Presence of a Resume / CV file input
  const fileInputs = Array.from(doc.querySelectorAll('input[type="file"]'));
  for (const input of fileInputs) {
    const text = (input.name + ' ' + input.id + ' ' + (input.labels?.[0]?.textContent || '')).toLowerCase();
    if (text.includes('resume') || text.includes('cv') || text.includes('pdf') || text.includes('curriculum')) {
      return true;
    }
  }

  // 3. Name + Email + Phone/LinkedIn input combination
  const inputs = Array.from(doc.querySelectorAll('input, select, textarea'));
  let hasName = false;
  let hasEmail = false;
  let hasContact = false;

  for (const el of inputs) {
    const text = (el.name + ' ' + el.id + ' ' + el.placeholder + ' ' + (el.labels?.[0]?.textContent || '')).toLowerCase();
    if (text.includes('first_name') || text.includes('firstname') || text.includes('full name') || text.includes('fullname')) hasName = true;
    if (text.includes('email') || el.type === 'email') hasEmail = true;
    if (text.includes('phone') || text.includes('tel') || text.includes('linkedin') || text.includes('resume')) hasContact = true;
  }

  return (hasName && hasEmail) || (hasEmail && hasContact);
}

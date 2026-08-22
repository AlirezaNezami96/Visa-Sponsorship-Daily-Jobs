/**
 * fill.js — Precise ATS Field Dispatcher & Value Applicator
 */

import { setNativeValue, wait } from './reactSet.js';
import { selectNativeOrCustom, findMatchingOption } from './select.js';
import { getDeterministicAnswer, answerWorkAuth } from './answers.js';
import { attachBase64PdfToFileElement } from './files.js';
import { fillCountry, fillPhoneCountryThenNumber, fillLocationAutocomplete } from './widgets.js';
import { calculateTargetCompensation } from './compensation.js';

export async function fillSingleField(field, context) {
  const { profile, jobData, cachedResume, cachedCover, batchAnswers } = context;
  const { el, type, classification, desc, key } = field;

  // 1. Consent / GDPR / Terms Checkbox
  if (classification === 'CONSENT' || el.type === 'checkbox') {
    const label = desc.labelText.toLowerCase();
    const isConsent =
      label.includes('agree') ||
      label.includes('consent') ||
      label.includes('terms') ||
      label.includes('privacy') ||
      label.includes('certify') ||
      label.includes('acknowledge') ||
      label.includes('gdpr') ||
      label.includes('data processing') ||
      label.includes('truthful') ||
      label.includes('accurate');

    const isMarketing = label.includes('marketing') || label.includes('newsletter') || label.includes('sms alerts') || label.includes('promotional');

    if (isConsent && !isMarketing) {
      if (!el.checked) {
        el.click();
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return { success: true, valueUsed: 'Consent Agreed' };
      }
      return { success: true, valueUsed: 'Already Agreed' };
    }
  }

  // 2. Radio Button Group
  if (type === 'radio-group') {
    let answer = null;
    if (classification === 'WORK_AUTH') {
      answer = answerWorkAuth(desc.labelText || desc.combined, profile);
    } else {
      answer = getDeterministicAnswer(classification, profile, desc);
    }

    // Fallback to Batch AI answer if available
    if (!answer && batchAnswers && batchAnswers[key]) {
      answer = batchAnswers[key].option || batchAnswers[key].value;
    }

    if (answer && field.options) {
      for (const radio of field.options) {
        const labelText = (
          radio.labels?.[0]?.textContent ||
          radio.value ||
          radio.getAttribute('aria-label') ||
          ''
        ).trim().toLowerCase();

        if (
          labelText === answer.toLowerCase() ||
          labelText.includes(answer.toLowerCase()) ||
          (answer === 'Yes' && (labelText.startsWith('yes') || labelText === 'true')) ||
          (answer === 'No' && (labelText.startsWith('no') || labelText === 'false'))
        ) {
          radio.click();
          radio.dispatchEvent(new Event('change', { bubbles: true }));
          return { success: true, valueUsed: answer };
        }
      }
    }
    return { success: false, skipped: true, reason: 'No matching radio option' };
  }

  // 3. Country Widget (Turkey / Türkiye flyouts & native selects)
  if (classification === 'COUNTRY') {
    const success = await fillCountry(el, profile);
    if (success) {
      return { success: true, valueUsed: 'Turkey (Türkiye)' };
    }
    return { success: false, skipped: true, reason: 'Could not select Turkey/Türkiye' };
  }

  // 4. Phone Country & National Phone Number (intl-tel-input .iti support)
  if (classification === 'PHONE' || classification === 'PHONE_COUNTRY') {
    const success = await fillPhoneCountryThenNumber(el, profile);
    if (success) {
      return { success: true, valueUsed: profile.identity.phone_national || '5437437966' };
    }
    return { success: false, skipped: true, reason: 'Phone input failed' };
  }

  // 5. City / Location Autocomplete (Geocode Earth & dropdowns)
  if (classification === 'LOCATION_CITY') {
    const res = await fillLocationAutocomplete(el, profile);
    return res;
  }

  // 6. Work Authorization & Sponsorship
  if (classification === 'WORK_AUTH') {
    const answer = answerWorkAuth(desc.labelText || desc.combined, profile);
    if (el.tagName === 'SELECT' || el.getAttribute('role') === 'combobox') {
      const selected = await selectNativeOrCustom(el, [answer, answer === 'Yes' ? 'True' : 'False']);
      if (selected) return { success: true, valueUsed: answer };
    } else {
      setNativeValue(el, answer);
      return { success: true, valueUsed: answer };
    }
  }

  // 7. Compensation / Salary (3000 USD monthly converted to period & currency)
  if (classification === 'SALARY_EXPECTATION') {
    const comp = calculateTargetCompensation(desc.combined, profile);
    setNativeValue(el, comp.formatted);

    // Look for sibling currency/frequency dropdowns to set matching values
    try {
      const parent = el.closest('.form-group, .field, [data-automation-id*="formField"], div') || el.parentElement;
      if (parent) {
        const siblingSelects = Array.from(parent.querySelectorAll('select, [role="combobox"]'));
        for (const s of siblingSelects) {
          if (s !== el) {
            await selectNativeOrCustom(s, [comp.currency, comp.period, comp.period === 'month' ? 'Monthly' : comp.period]);
          }
        }
      }
    } catch (_) {}

    return { success: true, valueUsed: comp.display };
  }

  // 8. File Input: Resume / CV
  if (classification === 'FILE_RESUME' || (el.type === 'file' && !desc.combined.includes('cover'))) {
    let pdfData = cachedResume;
    if (!pdfData) {
      const resp = await chrome.runtime.sendMessage({
        action: 'TAILOR_RESUME_DIRECT',
        jobData,
      });
      if (resp && resp.success && resp.pdfBase64) {
        pdfData = resp;
        context.cachedResume = resp;
      }
    }

    if (pdfData && pdfData.pdfBase64) {
      const attached = attachBase64PdfToFileElement(el, pdfData.pdfBase64, pdfData.filename);
      if (attached) {
        return { success: true, valueUsed: `Attached: ${pdfData.filename}` };
      }
    }
    return { success: false, skipped: true, reason: 'Resume attach blocked or unavailable' };
  }

  // 9. File Input: Cover Letter
  if (classification === 'FILE_COVER_LETTER' || (el.type === 'file' && desc.combined.includes('cover'))) {
    let coverData = cachedCover;
    if (!coverData) {
      const resp = await chrome.runtime.sendMessage({
        action: 'GENERATE_COVER_DIRECT',
        jobData,
      });
      if (resp && resp.success) {
        coverData = resp;
        context.cachedCover = resp;
      }
    }

    if (coverData && coverData.pdfBase64) {
      const attached = attachBase64PdfToFileElement(el, coverData.pdfBase64, coverData.filename);
      if (attached) {
        return { success: true, valueUsed: `Attached: ${coverData.filename}` };
      }
    }
    return { success: false, skipped: true, reason: 'Cover letter file attach skipped' };
  }

  // 10. Cover Letter Textarea
  if (el.tagName === 'TEXTAREA' && desc.combined.includes('cover') && desc.combined.includes('letter')) {
    let coverData = cachedCover;
    if (!coverData) {
      const resp = await chrome.runtime.sendMessage({
        action: 'GENERATE_COVER_DIRECT',
        jobData,
      });
      if (resp && resp.success) {
        coverData = resp;
        context.cachedCover = resp;
      }
    }
    if (coverData && coverData.cover_letter_text) {
      setNativeValue(el, coverData.cover_letter_text);
      return { success: true, valueUsed: 'Generated Cover Letter' };
    }
  }

  // 11. Batch AI Answer (for custom questions, multi-select, checklists, or unique text)
  if (batchAnswers && batchAnswers[key]) {
    const aiItem = batchAnswers[key];
    const aiVal = aiItem.option || aiItem.value;

    if (el.tagName === 'SELECT' || el.getAttribute('role') === 'combobox') {
      const selected = await selectNativeOrCustom(el, [aiVal, aiItem.value]);
      if (selected) {
        return { success: true, valueUsed: String(aiVal) };
      }
    } else if (el.type === 'checkbox') {
      if (Array.isArray(aiItem.value)) {
        const shouldCheck = aiItem.value.some((v) => desc.labelText.toLowerCase().includes(String(v).toLowerCase()));
        if (shouldCheck && !el.checked) {
          el.click();
          return { success: true, valueUsed: 'Checked' };
        }
      }
    } else {
      setNativeValue(el, String(aiVal));
      return { success: true, valueUsed: String(aiVal).slice(0, 45) + '…' };
    }
  }

  // 12. Standard Deterministic Fields (Names, Email, Links, EEO, How Heard)
  const detAnswer = getDeterministicAnswer(classification, profile, desc);
  if (detAnswer) {
    if (el.tagName === 'SELECT' || el.getAttribute('role') === 'combobox') {
      const selected = await selectNativeOrCustom(el, detAnswer);
      if (selected) return { success: true, valueUsed: detAnswer };
    } else {
      setNativeValue(el, detAnswer);
      return { success: true, valueUsed: detAnswer };
    }
  }

  return { success: false, skipped: true, reason: 'No matching profile field' };
}

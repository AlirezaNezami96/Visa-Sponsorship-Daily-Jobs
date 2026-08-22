/**
 * fill.js — Single Field Dispatcher & Value Applicator
 */

import { setNativeValue, wait } from './reactSet.js';
import { selectNativeOrCustom, findMatchingOption } from './select.js';
import { getDeterministicAnswer } from './answers.js';
import { attachBase64PdfToFileElement } from './files.js';

export async function fillSingleField(field, context) {
  const { profile, jobData, cachedResume, cachedCover } = context;
  const { el, type, classification, desc } = field;

  // 1. Radio Button Group
  if (type === 'radio-group') {
    const answer = getDeterministicAnswer(classification, profile);
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

  // 2. Checkboxes (GDPR, Consent, Terms)
  if (el.type === 'checkbox') {
    const label = desc.labelText.toLowerCase();
    if (label.includes('agree') || label.includes('consent') || label.includes('terms') || label.includes('privacy') || label.includes('certify')) {
      if (!el.checked) {
        el.click();
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return { success: true, valueUsed: 'Checked' };
      }
    }
    return { success: false, skipped: true, reason: 'Optional checkbox' };
  }

  // 3. File Input: Resume / CV
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

  // 4. File Input: Cover Letter
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

  // 5. Select / Custom Combobox
  if (el.tagName === 'SELECT' || el.getAttribute('role') === 'combobox') {
    const answer = getDeterministicAnswer(classification, profile);
    if (answer) {
      const aliases = classification === 'COUNTRY' ? profile.address.country_aliases : [];
      const selected = await selectNativeOrCustom(el, answer, aliases);
      if (selected) {
        return { success: true, valueUsed: answer };
      }
    }
    return { success: false, skipped: true, reason: 'Option not found in dropdown' };
  }

  // 6. Free-Text Textarea (Cover letter or Unique Question)
  if (el.tagName === 'TEXTAREA') {
    if (desc.combined.includes('cover') && desc.combined.includes('letter')) {
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

    // Unique Application Question
    const questionText = desc.labelText || desc.name || 'Tell us about your background';
    const resp = await chrome.runtime.sendMessage({
      action: 'ANSWER_QUESTION',
      question: questionText,
      jobTitle: jobData?.jobTitle,
      companyName: jobData?.companyName,
      jobDescription: jobData?.jobDescription,
    });

    if (resp && resp.success && resp.answer) {
      setNativeValue(el, resp.answer);
      return { success: true, valueUsed: resp.answer.slice(0, 40) + '…' };
    }
    return { success: false, skipped: true, reason: 'Unique question unanswered' };
  }

  // 7. Standard Text / Email / Phone / URL inputs
  const answer = getDeterministicAnswer(classification, profile);
  if (answer) {
    setNativeValue(el, answer);
    return { success: true, valueUsed: answer };
  }

  return { success: false, skipped: true, reason: 'No matching profile field' };
}

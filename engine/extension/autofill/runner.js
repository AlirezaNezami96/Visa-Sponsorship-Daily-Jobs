/**
 * runner.js — Master Sequential Form Walk Executor with Upfront Batch AI
 */

import { enumerateFormFields } from './enumerate.js';
import { fillSingleField } from './fill.js';
import { fillExperienceRepeaters, fillEducationRepeaters } from './repeaters.js';
import { wait, rand } from './reactSet.js';

const DETERMINISTIC_TYPES = new Set([
  'FIRST_NAME',
  'LAST_NAME',
  'FULL_NAME',
  'EMAIL',
  'PHONE',
  'PHONE_COUNTRY',
  'LINK_LINKEDIN',
  'LINK_GITHUB',
  'LINK_PORTFOLIO',
  'COUNTRY',
  'LOCATION_CITY',
  'POSTAL_CODE',
  'ADDRESS_LINE',
  'LOCATION_PREFERENCE',
  'WORK_AUTH',
  'EEO_GENDER',
  'EEO_ETHNICITY',
  'EEO_VETERAN',
  'EEO_DISABILITY',
  'EEO_LGBTQ',
  'SALARY_EXPECTATION',
  'YEARS_EXPERIENCE',
  'HOW_HEARD',
  'CONSENT',
  'FILE_RESUME',
  'FILE_COVER_LETTER',
]);

export async function runAutofillSequence(drawer, jobData = {}) {
  // 1. Fetch applicant profile from background worker
  const profileResp = await chrome.runtime.sendMessage({ action: 'GET_PROFILE' });
  if (!profileResp || !profileResp.success || !profileResp.profile) {
    drawer.setStatus('❌ Error: Could not load applicant profile from backend.');
    alert('Please ensure Job Acquisition Engine is running on http://127.0.0.1:8000.');
    return;
  }

  const profile = profileResp.profile;

  // 2. Enumerate visible form fields in visual order
  const fields = enumerateFormFields(document);
  if (fields.length === 0) {
    drawer.setStatus('⚠️ No interactive form fields found on this page.');
    return;
  }

  // Populate drawer rows upfront
  fields.forEach((f, idx) => {
    const key = `field_${idx}`;
    f.key = key;
    const label = f.desc?.labelText || f.name || f.classification;
    drawer.addFieldRow(key, label, f.el);
  });

  // 3. Batch AI Answering for custom/unmatched questions before the walk
  const batchAnswers = {};
  const aiFields = fields.filter((f) => !DETERMINISTIC_TYPES.has(f.classification));

  if (aiFields.length > 0) {
    drawer.setStatus(`🧠 Answering ${aiFields.length} custom questions with Batch AI…`);
    try {
      const questionsPayload = aiFields.map((f) => {
        let options = [];
        if (f.el.tagName === 'SELECT') {
          options = Array.from(f.el.options)
            .map((o) => (o.text || o.textContent || '').trim())
            .filter((t) => t && !t.toLowerCase().includes('select') && !t.toLowerCase().includes('choose'));
        }
        return {
          id: f.key,
          label: f.desc?.labelText || f.name || 'Question',
          type: f.type,
          options,
        };
      });

      const batchResp = await chrome.runtime.sendMessage({
        action: 'BATCH_ANSWER',
        payload: {
          job_title: jobData.jobTitle,
          company_name: jobData.companyName,
          job_description: jobData.jobDescription,
          questions: questionsPayload,
        },
      });

      if (batchResp && batchResp.success && Array.isArray(batchResp.answers)) {
        batchResp.answers.forEach((ans) => {
          if (ans && ans.id) {
            batchAnswers[ans.id] = ans;
          }
        });
      }
    } catch (batchErr) {
      console.warn('Batch AI answering failed, falling back to local defaults:', batchErr);
    }
  }

  const context = {
    profile,
    jobData,
    cachedResume: null,
    cachedCover: null,
    batchAnswers,
  };

  drawer.setStatus('Autofilling fields sequentially…');
  let filledCount = 0;
  let skippedCount = 0;

  // 4. Walk one field at a time
  for (const field of fields) {
    const targetEl = field.el;

    // Scroll into viewport center smoothly
    if (targetEl && targetEl.scrollIntoView) {
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      targetEl.classList.add('job-os-highlight-field');
    }

    drawer.updateFieldRow(field.key, 'active');
    await wait(rand(130, 200));

    // Fill field
    let result = { success: false, skipped: true };
    try {
      result = await fillSingleField(field, context);
    } catch (err) {
      console.warn('Field fill error:', err);
      result = { success: false, skipped: true, reason: err.message };
    }

    if (targetEl) {
      targetEl.classList.remove('job-os-highlight-field');
    }

    if (result.success) {
      filledCount++;
      drawer.updateFieldRow(field.key, 'success', result.valueUsed);
    } else {
      skippedCount++;
      drawer.updateFieldRow(field.key, 'skipped', result.reason || 'Skipped');
    }

    drawer.updateFooter(filledCount, skippedCount);
    await wait(rand(120, 220));
  }

  // 5. Fill Experience & Education Repeaters if present
  try {
    if (profile.experience && profile.experience.length > 0) {
      await fillExperienceRepeaters(document, profile.experience);
    }
    if (profile.education && profile.education.length > 0) {
      await fillEducationRepeaters(document, profile.education);
    }
  } catch (repErr) {
    console.debug('Repeater fill completed or skipped:', repErr);
  }

  // 6. Finished walk (Never submits)
  drawer.showComplete(filledCount, skippedCount);
}

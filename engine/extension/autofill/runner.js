/**
 * runner.js — Master Sequential Form Walk Executor
 */

import { enumerateFormFields } from './enumerate.js';
import { fillSingleField } from './fill.js';
import { fillExperienceRepeaters, fillEducationRepeaters } from './repeaters.js';
import { wait, rand } from './reactSet.js';

export async function runAutofillSequence(drawer, jobData = {}) {
  // 1. Fetch applicant profile from background script (sole secure gateway)
  const profileResp = await chrome.runtime.sendMessage({ action: 'GET_PROFILE' });
  if (!profileResp || !profileResp.success || !profileResp.profile) {
    drawer.setStatus('❌ Error: Could not load applicant profile from backend.');
    alert('Please ensure Job Acquisition Engine is running on http://127.0.0.1:8000.');
    return;
  }

  const profile = profileResp.profile;
  if (profile.identity?.full_name === 'Alex Doe') {
    drawer.setStatus('⚠️ Notice: Using example profile. Edit data/applicant_profile.json for your real data.');
  }

  const context = {
    profile,
    jobData,
    cachedResume: null,
    cachedCover: null,
  };

  // 2. Enumerate visible form fields in visual order
  const fields = enumerateFormFields(document);
  if (fields.length === 0) {
    drawer.setStatus('⚠️ No interactive form fields found on this page.');
    return;
  }

  let filledCount = 0;
  let skippedCount = 0;

  // Populate drawer rows upfront
  fields.forEach((f, idx) => {
    const key = `field_${idx}`;
    f.key = key;
    const label = f.desc?.labelText || f.name || f.classification;
    drawer.addFieldRow(key, label, f.el);
  });

  // 3. Walk one field at a time
  for (const field of fields) {
    const targetEl = field.el;

    // Scroll into viewport center smoothly
    if (targetEl && targetEl.scrollIntoView) {
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      targetEl.classList.add('job-os-highlight-field');
    }

    drawer.updateFieldRow(field.key, 'active');
    await wait(rand(140, 220));

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
    await wait(rand(120, 240));
  }

  // 4. Fill Experience & Education Repeaters if present
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

  // 5. Finished walk
  drawer.showComplete(filledCount, skippedCount);
}

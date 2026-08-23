/**
 * runner.js — Universal Master Sequential Form Walk Executor with Session State Machine
 */

import { discoverFormFields } from './discovery.js';
import { classifyFormField } from './classifier.js';
import { resolveCandidateValue } from './resolver.js';
import { defaultAdapterRegistry } from './adapters/registry.js';
import { remoteConfigManager } from './remote_config.js';
import { verifyAndApplyValue, applyCustomComboboxValue, applyCheckboxOrRadio, wait } from './applicator.js';
import { fillExperienceRepeaters, fillEducationRepeaters } from './repeaters.js';
import { attachBase64PdfToFileElement } from './files.js';
import { fillCountry, fillPhoneCountryThenNumber, fillLocationAutocomplete } from './widgets.js';
import { localDiagnostics } from './diagnostics.js';

export async function runAutofillSequence(drawer, jobData = {}, session = null) {
  const startTime = Date.now();

  // 1. Fetch applicant profile from background worker
  const profileResp = await chrome.runtime.sendMessage({ action: 'GET_PROFILE' });
  if (!profileResp || !profileResp.success || !profileResp.profile) {
    drawer.setStatus('❌ Error: Could not load applicant profile from backend.');
    alert('Please ensure Job Acquisition Engine is running on http://127.0.0.1:8000.');
    return;
  }
  const profile = profileResp.profile;

  // 2. Resolve Active ATS Adapter & Remote Platform Hints
  const adapter = defaultAdapterRegistry.resolveAdapter(window.location.href, document);
  const platformHints = await remoteConfigManager.getPlatformHints(adapter.id);
  const combinedHints = { ...adapter.getFieldHints(), ...platformHints };

  // 3. Discover all form fields across DOM & Shadow DOM
  const formFields = discoverFormFields(document);
  if (formFields.length === 0) {
    drawer.setStatus('⚠️ No interactive form fields found on this page.');
    return;
  }

  // 4. Classify each FormField using weighted multi-signal scoring
  for (const field of formFields) {
    classifyFormField(field, combinedHints);
  }

  // 5. Populate Drawer UI upfront with confidence tiers
  drawer.clearFieldRows();
  formFields.forEach((f, idx) => {
    const key = `field_${idx}`;
    f.key = key;
    const label = f.labelInfo?.raw || f.name || f.classification || 'Field';
    drawer.addFieldRow(key, label, f.element, f.confidenceTier);
  });

  // 6. Batch AI Answering for custom/unmatched questions (strictly firewalled from demographics)
  const batchAnswers = {};
  const aiFields = formFields.filter(
    (f) => f.confidenceTier === 'AI_REVIEW' && !f.isSensitive && f.fieldType !== 'file'
  );

  if (aiFields.length > 0) {
    drawer.setStatus(`🧠 Answering ${aiFields.length} custom questions with Batch AI…`);
    try {
      const questionsPayload = aiFields.map((f) => {
        let options = [];
        if (f.fieldType === 'select' && f.options) {
          options = f.options.map((o) => o.text).filter((t) => t && !t.toLowerCase().includes('select'));
        }
        return {
          id: f.key,
          label: f.labelInfo?.raw || f.name || 'Question',
          type: f.fieldType,
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
      console.warn('Batch AI answering warning:', batchErr);
    }
  }

  drawer.setStatus('Autofilling fields sequentially…');
  let filledCount = 0;
  let skippedCount = 0;
  let aiFilledCount = 0;

  // 7. Sequential Field Walk
  for (const field of formFields) {
    // Check if user clicked Stop
    if (session && session.isStopped) {
      drawer.setStatus('⏹️ Autofill stopped by user.');
      break;
    }

    const targetEl = field.element;

    // Scroll into view & highlight
    if (targetEl && targetEl.scrollIntoView) {
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      targetEl.classList.add('job-os-highlight-field');
    }

    drawer.updateFieldRow(field.key, 'active');
    await wait(140);

    let fillSuccess = false;
    let valueUsed = '';
    let skipReason = '';

    try {
      const classification = field.classification;

      // Case A: Consent checkbox
      if (classification === 'consent_terms' || field.fieldType === 'checkbox') {
        applyCheckboxOrRadio(targetEl, true);
        fillSuccess = true;
        valueUsed = 'Agreed';
      }
      // Case B: Radio Group
      else if (field.fieldType === 'radio-group') {
        let answer = resolveCandidateValue(classification, profile, field, jobData);
        if (!answer && batchAnswers[field.key]) {
          answer = batchAnswers[field.key].option || batchAnswers[field.key].value;
          aiFilledCount++;
        }
        if (answer && field.options) {
          for (const opt of field.options) {
            const optText = (opt.text || opt.value || '').toLowerCase();
            const ansText = String(answer).toLowerCase();
            if (optText === ansText || optText.includes(ansText) || (ansText === 'yes' && optText.startsWith('yes')) || (ansText === 'no' && optText.startsWith('no'))) {
              opt.element.click();
              opt.element.dispatchEvent(new Event('change', { bubbles: true }));
              fillSuccess = true;
              valueUsed = answer;
              break;
            }
          }
        }
      }
      // Case C: Country Widget (Turkey / Türkiye selector)
      else if (classification === 'country') {
        fillSuccess = await fillCountry(targetEl, profile);
        valueUsed = 'Turkey (Türkiye)';
      }
      // Case D: Phone Number Widget
      else if (classification === 'phone' || classification === 'phone_country') {
        fillSuccess = await fillPhoneCountryThenNumber(targetEl, profile);
        valueUsed = profile.identity?.phone_national || '5437437966';
      }
      // Case E: City Autocomplete
      else if (classification === 'city') {
        const res = await fillLocationAutocomplete(targetEl, profile);
        fillSuccess = res.success;
        valueUsed = res.valueUsed || 'Istanbul';
      }
      // Case F: File Uploads (Resume & Cover Letter)
      else if (classification === 'resume_file' || (field.fieldType === 'file' && !field.name.includes('cover'))) {
        const resp = await chrome.runtime.sendMessage({ action: 'TAILOR_RESUME_DIRECT', jobData });
        if (resp && resp.success && resp.pdfBase64) {
          const attached = attachBase64PdfToFileElement(targetEl, resp.pdfBase64, resp.filename);
          if (attached) {
            fillSuccess = true;
            valueUsed = `Attached: ${resp.filename}`;
          }
        }
      }
      // Case G: Custom Combobox
      else if (field.fieldType === 'combobox') {
        const val = resolveCandidateValue(classification, profile, field, jobData);
        if (val) {
          fillSuccess = await applyCustomComboboxValue(targetEl, val);
          valueUsed = String(val);
        }
      }
      // Case H: Batch AI Answer
      else if (batchAnswers[field.key]) {
        const aiAns = batchAnswers[field.key];
        const val = aiAns.option || aiAns.value;
        if (val) {
          if (field.fieldType === 'select') {
            fillSuccess = await applyCustomComboboxValue(targetEl, val);
          } else {
            fillSuccess = await verifyAndApplyValue(targetEl, String(val));
          }
          valueUsed = String(val);
          aiFilledCount++;
        }
      }
      // Case I: Standard Deterministic Text / Textarea / Select
      else {
        const val = resolveCandidateValue(classification, profile, field, jobData);
        if (val) {
          if (field.fieldType === 'select') {
            fillSuccess = await applyCustomComboboxValue(targetEl, val);
          } else {
            fillSuccess = await verifyAndApplyValue(targetEl, String(val));
          }
          valueUsed = String(val);
        } else {
          skipReason = 'No matching profile value';
        }
      }
    } catch (err) {
      skipReason = err.message;
    }

    if (targetEl) {
      targetEl.classList.remove('job-os-highlight-field');
    }

    if (fillSuccess) {
      filledCount++;
      drawer.updateFieldRow(field.key, 'success', valueUsed);
      if (session) session.recordFill(field, valueUsed);
    } else {
      skippedCount++;
      drawer.updateFieldRow(field.key, 'skipped', skipReason || 'Skipped');
      if (session) session.recordSkip(field, skipReason);
    }

    drawer.updateFooter(filledCount, skippedCount);
    await wait(120);
  }

  // 8. Experience & Education Repeaters
  try {
    if (profile.experience && profile.experience.length > 0) {
      await fillExperienceRepeaters(document, profile.experience);
    }
    if (profile.education && profile.education.length > 0) {
      await fillEducationRepeaters(document, profile.education);
    }
  } catch (_) {}

  // 9. Record local diagnostics telemetry
  const durationMs = Date.now() - startTime;
  localDiagnostics.logRun({
    atsName: adapter.name,
    fieldCount: formFields.length,
    filledCount,
    aiCount: aiFilledCount,
    skippedCount,
    durationMs,
  });

  // 10. Complete (Never auto-submits)
  drawer.showComplete(filledCount, skippedCount, aiFilledCount);
}

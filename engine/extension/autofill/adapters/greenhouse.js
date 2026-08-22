/**
 * greenhouse.js — Greenhouse ATS Adapter
 */

import { setNativeValue, wait, humanType } from '../reactSet.js';
import { selectNativeOrCustom } from '../select.js';
import { getDeterministicAnswer } from '../answers.js';
import { classifyFieldType, getFieldDescriptor } from '../fields.js';

export const GreenhouseAdapter = {
  name: 'Greenhouse',

  matches() {
    return (
      window.location.hostname.includes('greenhouse.io') ||
      document.querySelector('#application_form, #apply_form, .job-post-form') !== null
    );
  },

  async fillForm(profile, jobData, onProgress) {
    const form = document.querySelector('#application_form, #apply_form, form') || document;
    const inputs = Array.from(form.querySelectorAll('input, select, textarea'));
    let filled = 0;
    const skipped = [];

    for (const input of inputs) {
      if (input.type === 'hidden' || input.type === 'submit') continue;

      const desc = getFieldDescriptor(input);
      const classification = classifyFieldType(desc);
      const answer = getDeterministicAnswer(classification, profile);

      if (answer) {
        if (input.tagName === 'SELECT') {
          const aliases = classification === 'COUNTRY' ? profile.address.country_aliases : [];
          await selectNativeOrCustom(input, answer, aliases);
        } else {
          await humanType(input, answer);
        }
        filled++;
        if (onProgress) onProgress({ current: filled, total: inputs.length, field: desc.name });
      } else if (desc.isRequired) {
        skipped.push(desc.labelText || desc.name);
      }
    }

    return { filled, skipped };
  },
};

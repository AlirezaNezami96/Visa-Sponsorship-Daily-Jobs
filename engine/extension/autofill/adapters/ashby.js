/**
 * ashby.js — Ashby ATS Adapter
 */

import { setNativeValue, humanType } from '../reactSet.js';
import { selectNativeOrCustom } from '../select.js';
import { getDeterministicAnswer } from '../answers.js';
import { classifyFieldType, getFieldDescriptor } from '../fields.js';

export const AshbyAdapter = {
  name: 'Ashby',

  matches() {
    return (
      window.location.hostname.includes('ashbyhq.com') ||
      document.querySelector('[data-testid="application-form"], .ashby-job-posting-container') !== null
    );
  },

  async fillForm(profile, jobData, onProgress) {
    const form = document.querySelector('[data-testid="application-form"], form') || document;
    const inputs = Array.from(form.querySelectorAll('input, select, textarea, [role="combobox"]'));
    let filled = 0;
    const skipped = [];

    for (const input of inputs) {
      if (input.type === 'hidden' || input.type === 'submit') continue;

      const desc = getFieldDescriptor(input);
      const classification = classifyFieldType(desc);
      const answer = getDeterministicAnswer(classification, profile);

      if (answer) {
        if (input.tagName === 'SELECT' || input.getAttribute('role') === 'combobox') {
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

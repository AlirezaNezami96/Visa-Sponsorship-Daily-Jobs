/**
 * linkedin.js — LinkedIn Easy Apply Modal Adapter (Stops before submit)
 */

import { setNativeValue, humanType } from '../reactSet.js';
import { selectNativeOrCustom } from '../select.js';
import { getDeterministicAnswer } from '../answers.js';
import { classifyFieldType, getFieldDescriptor } from '../fields.js';

export const LinkedInAdapter = {
  name: 'LinkedIn Easy Apply',

  matches() {
    return (
      window.location.hostname.includes('linkedin.com') &&
      document.querySelector('.jobs-easy-apply-modal, .jobs-easy-apply-content') !== null
    );
  },

  async fillForm(profile, jobData, onProgress) {
    const modal = document.querySelector('.jobs-easy-apply-modal') || document;
    const inputs = Array.from(modal.querySelectorAll('input, select, textarea'));
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

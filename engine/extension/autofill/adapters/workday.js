/**
 * workday.js — Workday ATS Multi-Page Wizard Adapter
 */

import { setNativeValue, wait, humanType } from '../reactSet.js';
import { selectNativeOrCustom } from '../select.js';
import { getDeterministicAnswer } from '../answers.js';
import { classifyFieldType, getFieldDescriptor } from '../fields.js';

export const WorkdayAdapter = {
  name: 'Workday',

  matches() {
    return (
      window.location.hostname.includes('myworkdayjobs.com') ||
      window.location.hostname.includes('myworkday.com') ||
      document.querySelector('[data-automation-id="workdayApplication"]') !== null
    );
  },

  async fillForm(profile, jobData, onProgress) {
    const inputs = Array.from(
      document.querySelectorAll(
        'input:not([type="hidden"]), select, textarea, [data-automation-id*="formField"], [role="combobox"]'
      )
    );
    let filled = 0;
    const skipped = [];

    for (const input of inputs) {
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

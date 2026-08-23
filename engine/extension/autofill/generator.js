/**
 * generator.js — Developer Tool: ATS Adapter / Config Generator
 */

import { discoverFormFields } from './discovery.js';
import { classifyFormField } from './classifier.js';

/**
 * Inspects the current page and produces an ATS configuration draft JSON.
 */
export function generatePlatformConfigDraft(platformId = 'custom_ats') {
  const fields = discoverFormFields(document);
  const config = {
    id: platformId,
    urlPatterns: [`*://${window.location.hostname}/*`],
    fields: {},
  };

  for (const f of fields) {
    const res = classifyFormField(f);
    if (res.canonicalKey && res.canonicalKey !== 'unknown') {
      if (!config.fields[res.canonicalKey]) {
        config.fields[res.canonicalKey] = { selectors: [] };
      }

      // Generate best selector
      let sel = '';
      if (f.element.id) {
        sel = `#${CSS.escape(f.element.id)}`;
      } else if (f.element.getAttribute('data-automation-id')) {
        sel = `[data-automation-id="${f.element.getAttribute('data-automation-id')}"]`;
      } else if (f.element.name) {
        sel = `${f.element.tagName.toLowerCase()}[name="${f.element.name}"]`;
      }

      if (sel && !config.fields[res.canonicalKey].selectors.includes(sel)) {
        config.fields[res.canonicalKey].selectors.push(sel);
      }
    }
  }

  return config;
}

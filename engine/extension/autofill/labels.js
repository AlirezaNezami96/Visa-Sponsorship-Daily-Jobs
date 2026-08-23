/**
 * labels.js — 13-Priority Semantic Label & Metadata Extractor
 */

import { normalizeSemanticText } from './taxonomy.js';

export function extractSemanticLabel(el) {
  if (!el) return { raw: '', normalized: '', source: 'none' };

  // 1. Explicit <label for="id">
  if (el.id) {
    try {
      const explicitLabel = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (explicitLabel) {
        const text = explicitLabel.textContent?.trim();
        if (text && text.length > 1) {
          return { raw: text, normalized: normalizeSemanticText(text), source: 'label_for' };
        }
      }
    } catch (_) {}
  }

  // 2. Element's native labels collection (HTML5 standard)
  if (el.labels && el.labels.length > 0) {
    for (const l of el.labels) {
      const text = l.textContent?.trim();
      if (text && text.length > 1) {
        return { raw: text, normalized: normalizeSemanticText(text), source: 'native_labels' };
      }
    }
  }

  // 3. Wrapping <label>
  const wrappingLabel = el.closest('label');
  if (wrappingLabel) {
    // Clone and remove inputs to extract clean label text
    const clone = wrappingLabel.cloneNode(true);
    clone.querySelectorAll('input, select, textarea, button, script, style').forEach((n) => n.remove());
    const text = clone.textContent?.trim();
    if (text && text.length > 1) {
      return { raw: text, normalized: normalizeSemanticText(text), source: 'wrapping_label' };
    }
  }

  // 4. aria-labelledby (resolves target element text)
  const labelledBy = el.getAttribute('aria-labelledby');
  if (labelledBy) {
    const ids = labelledBy.split(/\s+/);
    const texts = [];
    for (const id of ids) {
      const ref = document.getElementById(id);
      if (ref && ref.textContent?.trim()) {
        texts.push(ref.textContent.trim());
      }
    }
    if (texts.length > 0) {
      const combined = texts.join(' ');
      return { raw: combined, normalized: normalizeSemanticText(combined), source: 'aria_labelledby' };
    }
  }

  // 5. aria-label
  const ariaLabel = el.getAttribute('aria-label');
  if (ariaLabel && ariaLabel.trim().length > 1) {
    return { raw: ariaLabel.trim(), normalized: normalizeSemanticText(ariaLabel), source: 'aria_label' };
  }

  // 6. placeholder
  const placeholder = el.getAttribute('placeholder');
  if (placeholder && placeholder.trim().length > 1) {
    return { raw: placeholder.trim(), normalized: normalizeSemanticText(placeholder), source: 'placeholder' };
  }

  // 7. autocomplete
  const autocomplete = el.getAttribute('autocomplete');
  if (autocomplete && autocomplete !== 'off' && autocomplete !== 'on') {
    return { raw: autocomplete.trim(), normalized: normalizeSemanticText(autocomplete), source: 'autocomplete' };
  }

  // 8. Preceding Sibling text / label element
  let prev = el.previousElementSibling;
  while (prev) {
    if (prev.matches && (prev.matches('label, span, div, p, strong, b') || prev.classList.contains('label'))) {
      const text = prev.textContent?.trim();
      if (text && text.length > 1 && text.length < 150) {
        return { raw: text, normalized: normalizeSemanticText(text), source: 'preceding_sibling' };
      }
    }
    prev = prev.previousElementSibling;
  }

  // 9. Parent Form Group Container Text
  const container = el.closest('.form-group, .field, [data-automation-id*="formField"], .form-field, .input-group, .css-form-item');
  if (container) {
    const clone = container.cloneNode(true);
    clone.querySelectorAll('input, select, textarea, button, script, style').forEach((n) => n.remove());
    const text = clone.textContent?.trim();
    if (text && text.length > 1 && text.length < 150) {
      return { raw: text, normalized: normalizeSemanticText(text), source: 'parent_container' };
    }
  }

  // 10. Fieldset <legend>
  const fieldset = el.closest('fieldset');
  if (fieldset) {
    const legend = fieldset.querySelector('legend');
    if (legend && legend.textContent?.trim()) {
      const text = legend.textContent.trim();
      return { raw: text, normalized: normalizeSemanticText(text), source: 'fieldset_legend' };
    }
  }

  // 11. Section Heading (h2, h3, h4, .section-header)
  const section = el.closest('section, .section, .card, fieldset, [data-automation-id*="section"]');
  if (section) {
    const header = section.querySelector('h1, h2, h3, h4, h5, .section-title, .section-header');
    if (header && header.textContent?.trim()) {
      const text = header.textContent.trim();
      if (text.length > 1 && text.length < 100) {
        return { raw: text, normalized: normalizeSemanticText(text), source: 'section_heading' };
      }
    }
  }

  // 12. ATS-specific metadata attributes (data-automation-id, data-qa, data-testid)
  const dataAttr =
    el.getAttribute('data-automation-id') ||
    el.getAttribute('data-qa') ||
    el.getAttribute('data-testid') ||
    el.getAttribute('name') ||
    el.id ||
    '';
  if (dataAttr && dataAttr.length > 1) {
    const formatted = dataAttr.replace(/[-_]/g, ' ');
    return { raw: formatted, normalized: normalizeSemanticText(formatted), source: 'ats_metadata' };
  }

  return { raw: '', normalized: '', source: 'none' };
}

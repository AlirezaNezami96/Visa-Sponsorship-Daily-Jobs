/**
 * discovery.js — Universal Form Discovery & Shadow DOM / Iframe Tree Walker
 */

import { extractSemanticLabel } from './labels.js';

export class FormField {
  constructor({
    id,
    element,
    framePath = [],
    fieldType,
    source,
    labelInfo,
    options = [],
    isRequired = false,
  }) {
    this.id = id;
    this.element = element;
    this.framePath = framePath;
    this.fieldType = fieldType; // 'text' | 'textarea' | 'select' | 'combobox' | 'radio-group' | 'checkbox' | 'file' | 'contenteditable'
    this.source = source;
    this.labelInfo = labelInfo;
    this.options = options;
    this.isRequired = isRequired;
    this.name = element.getAttribute('name') || '';
    this.htmlId = element.id || '';
    this.placeholder = element.getAttribute('placeholder') || '';
    this.ariaLabel = element.getAttribute('aria-label') || '';
    this.autocomplete = element.getAttribute('autocomplete') || '';
    this.dataAutomationId = element.getAttribute('data-automation-id') || '';
    this.boundingRect = element.getBoundingClientRect ? element.getBoundingClientRect() : null;
    this.classification = null;
    this.confidence = 0;
    this.confidenceTier = 'UNKNOWN';
    this.scoreSignals = [];
    this.suggestedValue = null;
  }
}

/**
 * Recursively discover all interactive form fields across DOM, open Shadow DOMs, and nested accessible frames.
 */
export function discoverFormFields(root = document, framePath = []) {
  const fields = [];
  const processedElements = new Set();
  const radioGroups = new Map();

  function isVisible(el) {
    if (!el) return false;
    // File inputs might be styled with opacity 0 or display none inside custom dropzones
    if (el.type === 'file') return true;
    const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
    if (style) {
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
        // Check if parent is custom upload or interactive wrapper
        if (el.closest('.dropzone, [data-testid*="upload"], .upload-btn, .file-upload')) {
          return true;
        }
        return false;
      }
    }
    const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
    if (rect && rect.width === 0 && rect.height === 0 && !el.closest('label, .custom-control')) {
      return false;
    }
    return true;
  }

  function traverse(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return;

    const tag = node.tagName.toLowerCase();
    const role = node.getAttribute('role') || '';
    const type = (node.type || '').toLowerCase();

    // 1. Skip scripts, styles, noscript, hidden templates
    if (['script', 'style', 'noscript', 'template', 'svg', 'path'].includes(tag)) {
      return;
    }

    // 2. Radio Input Groups
    if (tag === 'input' && type === 'radio') {
      if (!processedElements.has(node) && isVisible(node)) {
        processedElements.add(node);
        const groupName = node.name || node.closest('.form-group, fieldset, [data-automation-id*="formField"]')?.id || `radio_${fields.length}`;
        if (!radioGroups.has(groupName)) {
          radioGroups.set(groupName, []);
        }
        radioGroups.get(groupName).push(node);
      }
      return;
    }

    // 3. File Inputs
    if (tag === 'input' && type === 'file') {
      if (!processedElements.has(node)) {
        processedElements.add(node);
        const labelInfo = extractSemanticLabel(node);
        fields.push(
          new FormField({
            id: `field_file_${fields.length}`,
            element: node,
            framePath,
            fieldType: 'file',
            source: 'file',
            labelInfo,
            isRequired: node.required || node.getAttribute('aria-required') === 'true',
          })
        );
      }
      return;
    }

    // 4. Custom Comboboxes (e.g. role="combobox", Workday/Ashby custom dropdowns)
    if (role === 'combobox' || node.classList.contains('select2-selection') || node.classList.contains('css-combobox')) {
      if (!processedElements.has(node) && isVisible(node)) {
        processedElements.add(node);
        const labelInfo = extractSemanticLabel(node);
        fields.push(
          new FormField({
            id: `field_combobox_${fields.length}`,
            element: node,
            framePath,
            fieldType: 'combobox',
            source: 'combobox',
            labelInfo,
            isRequired: node.getAttribute('aria-required') === 'true' || node.classList.contains('required'),
          })
        );
      }
    }
    // 5. Native Inputs (text, email, tel, number, url, date, password)
    else if (tag === 'input') {
      if (!['hidden', 'submit', 'button', 'image', 'reset'].includes(type) && !processedElements.has(node) && isVisible(node)) {
        processedElements.add(node);
        const labelInfo = extractSemanticLabel(node);
        const fType = type === 'checkbox' ? 'checkbox' : 'text';
        fields.push(
          new FormField({
            id: `field_${fType}_${fields.length}`,
            element: node,
            framePath,
            fieldType: fType,
            source: 'input',
            labelInfo,
            isRequired: node.required || node.getAttribute('aria-required') === 'true',
          })
        );
      }
    }
    // 6. Textareas
    else if (tag === 'textarea') {
      if (!processedElements.has(node) && isVisible(node)) {
        processedElements.add(node);
        const labelInfo = extractSemanticLabel(node);
        fields.push(
          new FormField({
            id: `field_textarea_${fields.length}`,
            element: node,
            framePath,
            fieldType: 'textarea',
            source: 'textarea',
            labelInfo,
            isRequired: node.required || node.getAttribute('aria-required') === 'true',
          })
        );
      }
    }
    // 7. Native Selects
    else if (tag === 'select') {
      if (!processedElements.has(node) && isVisible(node)) {
        processedElements.add(node);
        const labelInfo = extractSemanticLabel(node);
        const options = Array.from(node.options).map((opt) => ({
          value: opt.value,
          text: (opt.text || opt.textContent || '').trim(),
          element: opt,
        }));
        fields.push(
          new FormField({
            id: `field_select_${fields.length}`,
            element: node,
            framePath,
            fieldType: 'select',
            source: 'select',
            labelInfo,
            options,
            isRequired: node.required || node.getAttribute('aria-required') === 'true',
          })
        );
      }
    }
    // 8. ContentEditable elements
    else if (node.isContentEditable || node.getAttribute('contenteditable') === 'true') {
      if (!processedElements.has(node) && isVisible(node)) {
        processedElements.add(node);
        const labelInfo = extractSemanticLabel(node);
        fields.push(
          new FormField({
            id: `field_editable_${fields.length}`,
            element: node,
            framePath,
            fieldType: 'contenteditable',
            source: 'contenteditable',
            labelInfo,
            isRequired: node.getAttribute('aria-required') === 'true',
          })
        );
      }
    }

    // 9. Recurse into open Shadow DOM
    if (node.shadowRoot) {
      Array.from(node.shadowRoot.children).forEach(traverse);
    }

    // 10. Recurse into children
    Array.from(node.children).forEach(traverse);
  }

  // Execute DOM tree walk
  if (root.body) {
    traverse(root.body);
  } else {
    traverse(root);
  }

  // Process Radio Groups into composite FormField objects
  for (const [groupName, radios] of radioGroups.entries()) {
    if (radios.length === 0) continue;
    const first = radios[0];
    const parentContainer = first.closest('fieldset, .form-group, [data-automation-id*="formField"], div') || first.parentElement;
    const labelInfo = extractSemanticLabel(parentContainer || first);
    const options = radios.map((r) => ({
      value: r.value,
      text: (r.labels?.[0]?.textContent || r.value || r.getAttribute('aria-label') || '').trim(),
      element: r,
    }));

    fields.push(
      new FormField({
        id: `field_radio_${groupName}_${fields.length}`,
        element: parentContainer || first,
        framePath,
        fieldType: 'radio-group',
        source: 'radio',
        labelInfo,
        options,
        isRequired: radios.some((r) => r.required || r.getAttribute('aria-required') === 'true'),
      })
    );
  }

  // Sort fields visually by top-to-bottom, left-to-right DOM geometry
  fields.sort((a, b) => {
    const rectA = a.element.getBoundingClientRect ? a.element.getBoundingClientRect() : { top: 0, left: 0 };
    const rectB = b.element.getBoundingClientRect ? b.element.getBoundingClientRect() : { top: 0, left: 0 };
    if (Math.abs(rectA.top - rectB.top) > 15) {
      return rectA.top - rectB.top;
    }
    return rectA.left - rectB.left;
  });

  return fields;
}

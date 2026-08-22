/**
 * enumerate.js — Shadow DOM Piercing & Visual Order Field Enumerator
 */

import { getFieldDescriptor, classifyFieldType } from './fields.js';

function walkNodes(root, list = []) {
  if (!root) return list;

  const children = Array.from(root.children || []);
  for (const node of children) {
    if (
      node.tagName === 'INPUT' ||
      node.tagName === 'TEXTAREA' ||
      node.tagName === 'SELECT' ||
      node.getAttribute('role') === 'combobox' ||
      node.isContentEditable
    ) {
      list.push(node);
    }

    if (node.shadowRoot) {
      walkNodes(node.shadowRoot, list);
    }
    if (node.children && node.children.length > 0) {
      walkNodes(node, list);
    }
  }
  return list;
}

function isElementVisible(el) {
  if (!el) return false;
  if (el.type === 'hidden') return false;
  if (el.getAttribute('aria-hidden') === 'true') return false;

  // File inputs may be visually hidden in modern ATS styled upload zones
  if (el.type === 'file') return true;

  const style = window.getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
    return false;
  }

  const rect = el.getBoundingClientRect();
  return rect.width > 0 || rect.height > 0;
}

function isSubmitOrNavigation(el) {
  const type = (el.type || '').toLowerCase();
  const text = (el.value || el.textContent || el.getAttribute('aria-label') || '').toLowerCase();
  const dataAuto = (el.getAttribute('data-automation-id') || '').toLowerCase();

  if (type === 'submit') return true;
  if (text.includes('submit') || text.includes('apply now') || text.includes('send application') || text.includes('easy apply')) {
    return true;
  }
  if (dataAuto.includes('submit') || dataAuto.includes('reviewsubmit')) {
    return true;
  }
  return false;
}

export function enumerateFormFields(root = document) {
  const rawElements = Array.from(
    root.querySelectorAll('input, textarea, select, [role="combobox"], [contenteditable="true"]')
  );

  const seen = new Set();
  const uniqueElements = [];
  for (const el of rawElements) {
    if (!seen.has(el)) {
      seen.add(el);
      uniqueElements.push(el);
    }
  }

  const fields = [];
  const radioGroups = new Map();

  for (const el of uniqueElements) {
    if (!isElementVisible(el)) continue;
    if (isSubmitOrNavigation(el)) continue;

    const desc = getFieldDescriptor(el);
    const classification = classifyFieldType(desc);

    // Group radio buttons by name
    if (el.type === 'radio' && el.name) {
      if (!radioGroups.has(el.name)) {
        const group = {
          type: 'radio-group',
          name: el.name,
          el,
          options: [el],
          classification,
          desc,
          rect: el.getBoundingClientRect(),
        };
        radioGroups.set(el.name, group);
        fields.push(group);
      } else {
        radioGroups.get(el.name).options.push(el);
      }
      continue;
    }

    fields.push({
      type: desc.type,
      name: desc.name,
      el,
      classification,
      desc,
      rect: el.getBoundingClientRect(),
    });
  }

  // Sort fields by visual document flow (top coordinate, then left)
  fields.sort((a, b) => {
    const topDiff = a.rect.top - b.rect.top;
    if (Math.abs(topDiff) > 15) {
      return topDiff;
    }
    return a.rect.left - b.rect.left;
  });

  return fields;
}

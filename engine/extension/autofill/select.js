/**
 * select.js — Robust Select & Custom Combobox Matcher
 */

export function normalizeStr(str) {
  if (!str) return '';
  return String(str)
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function findMatchingOption(options, targetValues, aliases = []) {
  if (!options || options.length === 0) return null;

  const targets = Array.isArray(targetValues) ? targetValues : [targetValues];
  const allAliases = [...targets, ...aliases].map((s) => (s ? String(s).trim() : '')).filter(Boolean);

  // 1. Exact text or value match
  for (const opt of options) {
    const text = (opt.text || opt.textContent || opt.innerText || '').trim();
    const val = (opt.value || '').trim();
    for (const target of allAliases) {
      if (text.toLowerCase() === target.toLowerCase() || val.toLowerCase() === target.toLowerCase()) {
        return opt;
      }
    }
  }

  // 2. Normalized equality match (e.g. Türkiye == Turkiye == Turkey)
  const normAliases = allAliases.map(normalizeStr);
  for (const opt of options) {
    const normText = normalizeStr(opt.text || opt.textContent || opt.innerText || '');
    const normVal = normalizeStr(opt.value || '');
    for (const normTarget of normAliases) {
      if (normText === normTarget || normVal === normTarget) {
        return opt;
      }
    }
  }

  // 3. Includes match (for strings with min length 4)
  for (const opt of options) {
    const normText = normalizeStr(opt.text || opt.textContent || opt.innerText || '');
    for (const normTarget of normAliases) {
      if (normTarget.length >= 4 && (normText.includes(normTarget) || normTarget.includes(normText))) {
        return opt;
      }
    }
  }

  return null;
}

export async function selectNativeOrCustom(el, targets, aliases = []) {
  if (!el) return false;

  // 1. Standard HTMLSelectElement
  if (el.tagName === 'SELECT') {
    const match = findMatchingOption(Array.from(el.options), targets, aliases);
    if (match) {
      el.value = match.value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
      return true;
    }
    return false;
  }

  // 2. Custom ARIA combobox / listbox / custom dropdown
  if (el.getAttribute('role') === 'combobox' || el.classList.contains('select__control') || el.dataset.automationId) {
    el.click();
    await new Promise((r) => setTimeout(r, 220));

    const candidates = Array.from(
      document.querySelectorAll('[role="option"], .select__option, [data-automation-id*="menu-item"], li')
    ).filter((o) => o.offsetParent !== null);

    const match = findMatchingOption(candidates, targets, aliases);
    if (match) {
      match.click();
      return true;
    }
  }

  return false;
}

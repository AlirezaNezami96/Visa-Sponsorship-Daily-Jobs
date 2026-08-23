/**
 * applicator.js — Framework-Safe Value Applicator & Widget Drivers
 */

export function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Applies a value to React/Vue/Angular controlled text inputs with native property setter and full event lifecycle.
 */
export function applyNativeValue(element, value) {
  if (!element) return false;

  try {
    element.focus();

    // 1. Get native prototype descriptor to bypass framework overriding
    let proto = Object.getPrototypeOf(element);
    if (element.tagName === 'INPUT') proto = HTMLInputElement.prototype;
    else if (element.tagName === 'TEXTAREA') proto = HTMLTextAreaElement.prototype;
    else if (element.tagName === 'SELECT') proto = HTMLSelectElement.prototype;

    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
    if (descriptor && descriptor.set) {
      descriptor.set.call(element, String(value));
    } else {
      element.value = String(value);
    }

    // 2. Clear React internal value tracker to register change
    if (element._valueTracker) {
      element._valueTracker.setValue('');
    }

    // 3. Dispatch full event sequence
    element.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    element.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    element.dispatchEvent(new Event('blur', { bubbles: true, composed: true }));

    return true;
  } catch (err) {
    try {
      element.value = String(value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    } catch (_) {
      return false;
    }
  }
}

/**
 * Verifies if the element retains the filled value after framework re-render.
 */
export async function verifyAndApplyValue(element, value) {
  applyNativeValue(element, value);
  await wait(50);
  if (element.value !== String(value)) {
    // Retry once with direct dispatch
    applyNativeValue(element, value);
  }
  return element.value === String(value) || element.value.includes(String(value));
}

/**
 * Custom Combobox Driver (supports role="combobox", Workday, Ashby, Select2, React Select).
 */
export async function applyCustomComboboxValue(element, targetValues = []) {
  if (!element) return false;

  const targets = (Array.isArray(targetValues) ? targetValues : [targetValues])
    .filter(Boolean)
    .map((v) => String(v).toLowerCase().trim());

  if (targets.length === 0) return false;

  try {
    // 1. Focus and trigger open
    element.focus();
    element.click();
    element.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', code: 'ArrowDown', bubbles: true }));
    await wait(200);

    // 2. Find options list container (aria-controls, role="listbox", popup, or nearby dropdown)
    const listboxId = element.getAttribute('aria-controls') || element.getAttribute('aria-owns');
    let listbox = listboxId ? document.getElementById(listboxId) : null;
    if (!listbox) {
      listbox =
        document.querySelector('[role="listbox"], [role="menu"], .select2-results, .css-menu, [data-automation-id*="promptOption"]') ||
        element.closest('.form-group, fieldset')?.querySelector('[role="listbox"]');
    }

    // 3. Match and click option
    if (listbox) {
      const optionElements = Array.from(
        listbox.querySelectorAll('[role="option"], [role="menuitem"], li, .select2-results__option, [data-automation-id*="promptOption"]')
      );

      for (const opt of optionElements) {
        const text = (opt.textContent || opt.innerText || '').toLowerCase().trim();
        for (const target of targets) {
          if (text === target || text.includes(target) || (target.length > 2 && text.startsWith(target))) {
            opt.scrollIntoView({ block: 'nearest' });
            opt.click();
            opt.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
            opt.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
            await wait(100);
            return true;
          }
        }
      }
    }

    // Fallback: If combobox contains an internal input, type the value
    const innerInput = element.querySelector('input') || (element.tagName === 'INPUT' ? element : null);
    if (innerInput) {
      applyNativeValue(innerInput, targets[0]);
      innerInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
      await wait(150);
      return true;
    }
  } catch (e) {
    console.debug('Custom combobox fill warning:', e);
  }

  return false;
}

/**
 * Checkbox & Radio Driver.
 */
export function applyCheckboxOrRadio(element, shouldCheck = true) {
  if (!element) return false;

  try {
    if (element.type === 'checkbox') {
      if (element.checked !== shouldCheck) {
        element.click();
        element.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
      }
      return true;
    }

    if (element.type === 'radio') {
      element.click();
      element.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
      return true;
    }
  } catch (_) {}

  return false;
}

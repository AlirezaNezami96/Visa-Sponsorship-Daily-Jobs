/**
 * reactSet.js — React/Vue/Angular-Safe Native Value Setter & Human Pacing
 */

export function setNativeValue(el, value) {
  if (!el) return;

  if (el.isContentEditable) {
    el.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return;
  }

  const proto = el instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;

  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
  if (desc && desc.set) {
    desc.set.call(el, value);
  } else {
    el.value = value;
  }

  el.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  el.dispatchEvent(new Event('blur', { bubbles: true }));
}

export function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function rand(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

export async function humanType(el, value, speedMin = 20, speedMax = 50) {
  if (!el) return;
  el.focus();
  setNativeValue(el, value);
  await wait(rand(speedMin, speedMax));
}

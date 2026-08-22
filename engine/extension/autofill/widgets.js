/**
 * widgets.js — Precise ATS Widget Drivers (Greenhouse, Lever, Ashby, Workday)
 */

import { setNativeValue, wait } from './reactSet.js';
import { selectNativeOrCustom, findMatchingOption, normalizeStr } from './select.js';

export async function fillCountry(el, profile) {
  const aliases = profile?.address?.country_aliases || [
    'Turkey',
    'Türkiye',
    'Turkiye',
    'Republic of Turkey',
    'Republic of Türkiye',
    'TR',
  ];

  return await selectNativeOrCustom(el, aliases);
}

export async function fillPhoneCountryThenNumber(phoneInput, profile) {
  const nationalNumber = profile?.identity?.phone_national || '5437437966';

  // 1. Check for intl-tel-input (.iti) flag container or custom dropdown
  const container = phoneInput.closest('.iti, .phone-input-container, .intl-tel-input') || phoneInput.parentElement;
  if (container) {
    const flagBtn = container.querySelector('.iti__selected-flag, .iti__flag-container, [aria-haspopup="listbox"]');
    if (flagBtn) {
      flagBtn.click();
      await wait(250);

      // Search input if present inside dropdown
      const searchInput = document.querySelector('.iti__search-input, .iti__search');
      if (searchInput) {
        setNativeValue(searchInput, 'Turkey');
        await wait(200);
      }

      // Find Turkey (+90 / tr) country item
      const countryItems = Array.from(
        document.querySelectorAll('li.iti__country, [role="option"], .iti__country-list li')
      );

      const match = countryItems.find((li) => {
        const code = (li.getAttribute('data-country-code') || '').toLowerCase();
        const text = (li.textContent || '').toLowerCase();
        return code === 'tr' || (text.includes('turkey') && !text.includes('turkmenistan')) || text.includes('+90');
      });

      if (match) {
        match.click();
        await wait(150);
      }
    }
  }

  // 2. Set national number only (no +90, no spaces)
  setNativeValue(phoneInput, nationalNumber);
  return true;
}

export async function fillLocationAutocomplete(el, profile) {
  const query = profile?.address?.city_query || 'Istanbul';
  const fallbackDisplay = profile?.address?.city_display || 'Istanbul, Turkey';

  // 1. Focus, clear, and type city query
  el.focus();
  setNativeValue(el, '');
  await wait(100);
  setNativeValue(el, query);
  el.dispatchEvent(new Event('input', { bubbles: true }));

  // 2. Wait 1600ms for async geocode/listbox response
  await wait(1600);

  // 3. Look for autocomplete dropdown suggestions
  const optionSelectors = [
    '[role="option"]',
    '.pac-item',
    '.autocomplete-suggestion',
    '.autocomplete-result',
    '.select__option',
    '.typeahead-result',
    '.location-suggestion',
    'ul.ui-autocomplete li',
    'div[id*="autocomplete"] div',
  ];

  const visibleOptions = Array.from(document.querySelectorAll(optionSelectors.join(','))).filter(
    (opt) => opt.offsetParent !== null && opt.textContent.trim().length > 0
  );

  if (visibleOptions.length > 0) {
    // Prefer Istanbul + Turkey/Türkiye match
    const bestMatch = visibleOptions.find((opt) => {
      const txt = normalizeStr(opt.textContent);
      return txt.includes('istanbul') && (txt.includes('turkey') || txt.includes('turkiye'));
    });

    const chosen = bestMatch || visibleOptions[0];
    chosen.click();
    await wait(200);
    return { success: true, valueUsed: chosen.textContent.trim() };
  }

  // If no dropdown menu appears, leave city display as free text
  setNativeValue(el, fallbackDisplay);
  return { success: true, valueUsed: fallbackDisplay };
}

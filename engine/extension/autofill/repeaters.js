/**
 * repeaters.js — Work Experience & Education Card Repeaters
 */

import { setNativeValue, wait } from './reactSet.js';
import { selectNativeOrCustom } from './select.js';

export async function fillExperienceRepeaters(containerEl, experienceList = []) {
  if (!experienceList || experienceList.length === 0) return;

  const addButtons = Array.from(document.querySelectorAll('button, a, [role="button"]')).filter((b) => {
    const text = (b.textContent || '').toLowerCase();
    return text.includes('add work') || text.includes('add experience') || text.includes('add employment') || text.includes('add position');
  });

  const cards = Array.from(document.querySelectorAll('[data-automation-id*="workExperience"], .experience-card, .work-history-item, fieldset'));

  for (let i = 0; i < experienceList.length; i++) {
    const item = experienceList[i];
    let currentCard = cards[i];

    if (!currentCard && addButtons[0]) {
      addButtons[0].click();
      await wait(400);
    }

    // Target inputs within the card or document
    const scope = currentCard || document;
    const inputs = Array.from(scope.querySelectorAll('input, textarea, select'));

    for (const input of inputs) {
      const name = (input.name || input.id || input.getAttribute('data-automation-id') || '').toLowerCase();
      const label = (input.labels?.[0]?.textContent || '').toLowerCase();
      const combined = `${name} ${label}`;

      if (combined.includes('company') || combined.includes('employer')) {
        setNativeValue(input, item.company);
      } else if (combined.includes('title') || combined.includes('role') || combined.includes('position')) {
        setNativeValue(input, item.title);
      } else if (combined.includes('location') || combined.includes('city')) {
        setNativeValue(input, item.location);
      } else if (combined.includes('description') || input.tagName === 'TEXTAREA') {
        const bulletsText = item.bullets.join('\n');
        setNativeValue(input, bulletsText);
      } else if (combined.includes('currently') || combined.includes('present') || combined.includes('current')) {
        if (item.current && !input.checked) {
          input.click();
        }
      }
    }
  }
}

export async function fillEducationRepeaters(containerEl, educationList = []) {
  if (!educationList || educationList.length === 0) return;

  const addButtons = Array.from(document.querySelectorAll('button, a, [role="button"]')).filter((b) => {
    const text = (b.textContent || '').toLowerCase();
    return text.includes('add education') || text.includes('add school') || text.includes('add degree');
  });

  for (let i = 0; i < educationList.length; i++) {
    const item = educationList[i];
    const inputs = Array.from(document.querySelectorAll('input, textarea, select'));

    for (const input of inputs) {
      const name = (input.name || input.id || input.getAttribute('data-automation-id') || '').toLowerCase();
      const label = (input.labels?.[0]?.textContent || '').toLowerCase();
      const combined = `${name} ${label}`;

      if (combined.includes('school') || combined.includes('institution') || combined.includes('university') || combined.includes('college')) {
        setNativeValue(input, item.school);
      } else if (combined.includes('degree')) {
        if (input.tagName === 'SELECT') {
          await selectNativeOrCustom(input, item.degree, item.degree_aliases);
        } else {
          setNativeValue(input, item.degree);
        }
      } else if (combined.includes('discipline') || combined.includes('major') || combined.includes('field of study')) {
        setNativeValue(input, item.discipline);
      }
    }
  }
}

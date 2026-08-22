/**
 * skills.js — Skills Multi-Select & Free-Form Intersection Matcher
 */

export function getRankedSkills(jdText, coreSkills = [], maxCount = 20) {
  if (!coreSkills || coreSkills.length === 0) return [];

  const jdLower = (jdText || '').toLowerCase();
  const overlapping = [];
  const nonOverlapping = [];

  for (const skill of coreSkills) {
    const sLower = skill.toLowerCase();
    if (jdLower.includes(sLower)) {
      overlapping.push(skill);
    } else {
      nonOverlapping.push(skill);
    }
  }

  const combined = [...overlapping, ...nonOverlapping];
  return combined.slice(0, maxCount);
}

export function fillSkillsMultiSelect(containerEl, jdText, coreSkills) {
  if (!containerEl) return 0;
  let clickedCount = 0;

  const checkboxes = Array.from(containerEl.querySelectorAll('input[type="checkbox"], [role="checkbox"]'));
  const coreLower = new Set(coreSkills.map((s) => s.toLowerCase()));
  const jdLower = (jdText || '').toLowerCase();

  // Sort checkboxes: JD-overlapping first
  checkboxes.sort((a, b) => {
    const aText = (a.labels?.[0]?.textContent || a.value || '').toLowerCase();
    const bText = (b.labels?.[0]?.textContent || b.value || '').toLowerCase();
    const aMatch = jdLower.includes(aText) ? 1 : 0;
    const bMatch = jdLower.includes(bText) ? 1 : 0;
    return bMatch - aMatch;
  });

  for (const cb of checkboxes) {
    if (clickedCount >= 25) break;

    const labelText = (cb.labels?.[0]?.textContent || cb.getAttribute('aria-label') || cb.value || '').trim().toLowerCase();
    if (coreLower.has(labelText)) {
      if (!cb.checked && cb.getAttribute('aria-checked') !== 'true') {
        cb.click();
        cb.dispatchEvent(new Event('change', { bubbles: true }));
        clickedCount++;
      }
    }
  }

  return clickedCount;
}

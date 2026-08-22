/**
 * answers.js — Deterministic Candidate Answers & Work-Auth Polarity Resolver
 */

import { calculateTargetCompensation } from './compensation.js';

export function answerWorkAuth(labelText, profile) {
  const text = (labelText || '').toLowerCase().replace(/\s+/g, ' ').trim();

  // 1. Specific to Turkey / Türkiye
  if (text.includes('turkey') || text.includes('türkiye') || text.includes('turkiye')) {
    if (text.includes('authorized') || text.includes('right to work') || text.includes('eligible') || text.includes('citizen')) {
      return 'Yes';
    }
  }

  // 2. Inverse sponsorship: "Can you work without sponsorship?" / "Do you have work authorization without visa support?"
  if (
    text.includes('without sponsorship') ||
    text.includes('without requiring sponsorship') ||
    text.includes('without visa') ||
    text.includes('already have authorization') ||
    text.includes('do not require sponsorship') ||
    text.includes("don't require sponsorship")
  ) {
    return 'No';
  }

  // 3. Will you now or in future require visa / sponsorship? / Need employer to sponsor?
  if (
    text.includes('require visa') ||
    text.includes('require sponsorship') ||
    text.includes('will you require') ||
    text.includes('need sponsorship') ||
    text.includes('need employer to sponsor') ||
    text.includes('future sponsorship') ||
    text.includes('visa sponsorship')
  ) {
    return 'Yes';
  }

  // 4. Legally authorized to work in US / UK / Canada / EU / country of job
  if (
    text.includes('legally authorized') ||
    text.includes('authorized to work') ||
    text.includes('right to work') ||
    text.includes('eligible to work') ||
    text.includes('work authorization') ||
    text.includes('work permit')
  ) {
    return 'No';
  }

  return 'No';
}

export function getDeterministicAnswer(classification, profile, fieldDesc) {
  if (!profile) return null;

  switch (classification) {
    case 'FIRST_NAME':
      return profile.identity.first_name;
    case 'LAST_NAME':
      return profile.identity.last_name;
    case 'FULL_NAME':
      return profile.identity.full_name;
    case 'EMAIL':
      return profile.identity.email;
    case 'PHONE':
      return profile.identity.phone_national || '5437437966';
    case 'PHONE_COUNTRY':
      return profile.identity.phone_country || 'TR';
    case 'LINK_LINKEDIN':
      return profile.identity.linkedin;
    case 'LINK_GITHUB':
      return profile.identity.github;
    case 'LINK_PORTFOLIO':
      return profile.identity.portfolio;
    case 'COUNTRY':
      return profile.address.country;
    case 'LOCATION_CITY':
      return profile.address.city_display || 'Istanbul, Turkey';
    case 'POSTAL_CODE':
      return profile.address.postal_code || '34382';
    case 'ADDRESS_LINE':
      return profile.address.line1 || '';
    case 'LOCATION_PREFERENCE':
      return 'Remote';
    case 'WORK_AUTH':
      return answerWorkAuth(fieldDesc?.labelText || fieldDesc?.combined || '', profile);
    case 'EEO_GENDER':
      return profile.eeo_and_screening.gender || 'Male';
    case 'EEO_ETHNICITY':
      return profile.eeo_and_screening.ethnicity || 'Middle Eastern';
    case 'EEO_VETERAN':
      return profile.eeo_and_screening.veteran || 'No';
    case 'EEO_DISABILITY':
      return profile.eeo_and_screening.disability || 'No';
    case 'EEO_LGBTQ':
      return profile.eeo_and_screening.lgbtq || 'No';
    case 'SALARY_EXPECTATION': {
      const comp = calculateTargetCompensation(fieldDesc?.combined || '', profile);
      return comp.formatted;
    }
    case 'YEARS_EXPERIENCE':
      return '9';
    case 'HOW_HEARD':
      return profile.eeo_and_screening.how_heard_default || 'LinkedIn';
    default:
      return null;
  }
}

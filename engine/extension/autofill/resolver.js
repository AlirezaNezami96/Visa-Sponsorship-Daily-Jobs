/**
 * resolver.js — Candidate Profile Value Resolver & Derived Facts Engine
 */

import { answerWorkAuth } from './answers.js';
import { calculateTargetCompensation } from './compensation.js';

/**
 * Calculate total years of experience deterministically from verified employment history.
 */
export function calculateYearsOfExperience(experience = []) {
  if (!Array.isArray(experience) || experience.length === 0) return 3;

  let totalMonths = 0;
  const now = new Date();

  for (const exp of experience) {
    if (!exp.start) continue;
    const startParts = exp.start.split('-');
    const startYear = parseInt(startParts[0], 10);
    const startMonth = parseInt(startParts[1] || '1', 10);
    const startDate = new Date(startYear, startMonth - 1, 1);

    let endDate = now;
    if (exp.end) {
      const endParts = exp.end.split('-');
      const endYear = parseInt(endParts[0], 10);
      const endMonth = parseInt(endParts[1] || '1', 10);
      endDate = new Date(endYear, endMonth - 1, 1);
    }

    const months = (endDate.getFullYear() - startDate.getFullYear()) * 12 + (endDate.getMonth() - startDate.getMonth());
    if (months > 0) totalMonths += months;
  }

  const years = Math.max(1, Math.round(totalMonths / 12));
  return years;
}

/**
 * Resolves a canonical taxonomy key to a candidate value from profile facts.
 */
export function resolveCandidateValue(canonicalKey, profile, formField = null, jobData = {}) {
  if (!profile) return null;

  const identity = profile.identity || {};
  const address = profile.address || {};
  const workAuth = profile.work_authorization || {};
  const eeo = profile.eeo_and_screening || {};
  const experience = profile.experience || [];
  const education = profile.education || [];

  switch (canonicalKey) {
    // ── Identity ──
    case 'first_name':
      return identity.first_name || identity.preferred_name || '';
    case 'last_name':
      return identity.last_name || '';
    case 'full_name':
      return identity.full_name || `${identity.first_name || ''} ${identity.last_name || ''}`.trim();
    case 'preferred_name':
      return identity.preferred_name || identity.first_name || '';

    // ── Contact ──
    case 'email':
      return identity.email || '';
    case 'phone':
      return identity.phone_display || identity.phone_e164 || identity.phone_national || '';
    case 'phone_country':
      return identity.phone_country || 'TR';

    // ── Address ──
    case 'country':
      return address.country || 'Turkey';
    case 'city':
      return address.city || 'Istanbul';
    case 'state':
      return address.region || address.state || 'Istanbul';
    case 'postal_code':
      return address.postal_code || '34382';
    case 'address_line1':
      return address.line1 || '';
    case 'address_line2':
      return address.line2 || '';
    case 'location_preference':
      return 'Remote';

    // ── Links ──
    case 'linkedin_url':
      return identity.linkedin || '';
    case 'github_url':
      return identity.github || '';
    case 'portfolio_url':
      return identity.portfolio || identity.website || '';
    case 'website_url':
      return identity.website || identity.portfolio || '';

    // ── Work Authorization (Polarity sensitive) ──
    case 'legally_authorized':
    case 'requires_sponsorship':
    case 'visa_status': {
      const labelText = formField?.labelInfo?.raw || formField?.name || '';
      return answerWorkAuth(labelText, profile);
    }

    // ── Compensation ──
    case 'salary_expectation': {
      const labelText = formField?.labelInfo?.raw || '';
      const comp = calculateTargetCompensation(labelText, profile);
      return comp.formatted || '3000';
    }

    // ── Experience & Education ──
    case 'current_company':
      return experience[0]?.company || '';
    case 'current_title':
      return experience[0]?.title || '';
    case 'years_of_experience':
      return String(calculateYearsOfExperience(experience));
    case 'school':
      return education[0]?.school || '';
    case 'degree':
      return education[0]?.degree || "Bachelor's Degree";
    case 'discipline':
      return education[0]?.discipline || 'Computer Science';

    // ── General ──
    case 'how_heard':
      return eeo.how_heard_default || 'LinkedIn';
    case 'start_date':
      return 'Immediately / 2 weeks notice';
    case 'consent_terms':
      return 'Yes';

    // ── Protected Demographics (Local explicit only) ──
    case 'gender':
      return eeo.gender || null;
    case 'ethnicity':
      return eeo.ethnicity || null;
    case 'veteran_status':
      return eeo.veteran || 'No';
    case 'disability_status':
      return eeo.disability || 'No';
    case 'lgbtq_status':
      return eeo.lgbtq || null;

    default:
      return null;
  }
}

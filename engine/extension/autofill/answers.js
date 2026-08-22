/**
 * answers.js — Deterministic Screening Answers & Human-Voice LLM Querying
 */

export function getDeterministicAnswer(classification, profile) {
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
      return profile.identity.phone_display || profile.identity.phone_e164;
    case 'LINK_LINKEDIN':
      return profile.identity.linkedin;
    case 'LINK_GITHUB':
      return profile.identity.github;
    case 'LINK_PORTFOLIO':
      return profile.identity.portfolio || profile.identity.website;
    case 'CITY':
      return profile.address.city;
    case 'COUNTRY':
      return profile.address.country;
    case 'WORK_AUTH_US':
      return profile.work_authorization.authorized_us || 'Yes';
    case 'WORK_AUTH_CA':
      return profile.work_authorization.authorized_canada || 'Yes';
    case 'WORK_AUTH_UK':
      return profile.work_authorization.authorized_uk || 'Yes';
    case 'WORK_AUTH_GENERAL':
      return 'Yes';
    case 'SPONSORSHIP_REQUIRED':
      return profile.work_authorization.requires_sponsorship_now_or_future || 'No';
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
    case 'SALARY_EXPECTATION':
      return String(profile.compensation.min_expected_usd || '2000');
    case 'YEARS_EXPERIENCE':
      return '9';
    case 'HOW_HEARD':
      return profile.eeo_and_screening.how_heard_default || 'LinkedIn';
    default:
      return null;
  }
}

export async function fetchUniqueQuestionAnswer(apiBase, question, jobData) {
  try {
    const res = await fetch(`${apiBase}/api/v1/autofill/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        job_title: jobData?.jobTitle || 'Software Engineer',
        company_name: jobData?.companyName || 'Company',
        jd_text: jobData?.jobDescription || '',
      }),
    });
    if (res.ok) {
      const data = await res.json();
      return data.answer || '';
    }
  } catch (err) {
    console.warn('Failed to generate unique answer:', err);
  }
  return '';
}

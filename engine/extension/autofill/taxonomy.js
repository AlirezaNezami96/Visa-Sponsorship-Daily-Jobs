/**
 * taxonomy.js — Canonical Field Taxonomy, International Synonyms & Protected Categories
 */

export const SENSITIVE_DEMOGRAPHIC_KEYS = new Set([
  'gender',
  'ethnicity',
  'race',
  'veteran_status',
  'disability_status',
  'lgbtq_status',
  'sexual_orientation',
  'transgender_status',
  'religion',
  'health_questions',
]);

export const CANONICAL_FIELD_TAXONOMY = {
  // ── Identity ──
  first_name: {
    label: 'First Name',
    category: 'identity',
    synonyms: ['first name', 'firstname', 'given name', 'forename', 'given-name', 'fname', 'first_name', 'nombre'],
  },
  middle_name: {
    label: 'Middle Name',
    category: 'identity',
    synonyms: ['middle name', 'middlename', 'second name', 'mname', 'middle_name', 'middle initial'],
  },
  last_name: {
    label: 'Last Name',
    category: 'identity',
    synonyms: ['last name', 'lastname', 'surname', 'family name', 'family-name', 'lname', 'last_name', 'apellido'],
  },
  full_name: {
    label: 'Full Name',
    category: 'identity',
    synonyms: ['full name', 'fullname', 'name', 'legal name', 'complete name', 'your name', 'candidate name'],
  },
  preferred_name: {
    label: 'Preferred Name',
    category: 'identity',
    synonyms: ['preferred name', 'nickname', 'chosen name', 'goes by'],
  },

  // ── Contact ──
  email: {
    label: 'Email Address',
    category: 'contact',
    synonyms: ['email', 'email address', 'e-mail', 'electronic mail', 'correo electronico', 'e-mail address'],
  },
  phone: {
    label: 'Phone Number',
    category: 'contact',
    synonyms: ['phone', 'mobile', 'telephone', 'cell phone', 'phone number', 'contact number', 'tel', 'phone_number'],
  },
  phone_country: {
    label: 'Phone Country Code',
    category: 'contact',
    synonyms: ['phone country', 'dial code', 'dialing code', 'country code', 'phone prefix', 'phone code'],
  },

  // ── Address & Location ──
  country: {
    label: 'Country',
    category: 'address',
    synonyms: ['country', 'country/region', 'nation', 'residence country', 'location country', 'nationality'],
  },
  city: {
    label: 'City / Location',
    category: 'address',
    synonyms: ['city', 'location', 'current city', 'town', 'current location', 'where do you live', 'city/state', 'residence'],
  },
  state: {
    label: 'State / Province / Region',
    category: 'address',
    synonyms: ['state', 'province', 'region', 'county', 'prefecture', 'state/province', 'canton'],
  },
  postal_code: {
    label: 'Postal / ZIP Code',
    category: 'address',
    synonyms: ['postal code', 'zip code', 'zip', 'postcode', 'pin code', 'postal_code', 'zipcode'],
  },
  address_line1: {
    label: 'Street Address',
    category: 'address',
    synonyms: ['address', 'street address', 'address line 1', 'street', 'address 1', 'residence address'],
  },
  address_line2: {
    label: 'Address Line 2',
    category: 'address',
    synonyms: ['address line 2', 'apartment', 'suite', 'unit', 'building', 'floor', 'apt'],
  },
  location_preference: {
    label: 'Workplace Preference',
    category: 'address',
    synonyms: ['workplace preference', 'remote preference', 'work location preference', 'willing to relocate', 'relocate', 'hybrid/remote'],
  },

  // ── Links & Social ──
  linkedin_url: {
    label: 'LinkedIn Profile',
    category: 'links',
    synonyms: ['linkedin', 'linkedin profile', 'linkedin url', 'linkedin link'],
  },
  github_url: {
    label: 'GitHub Profile',
    category: 'links',
    synonyms: ['github', 'github profile', 'github url', 'git profile', 'repository url'],
  },
  portfolio_url: {
    label: 'Portfolio Website',
    category: 'links',
    synonyms: ['portfolio', 'personal website', 'portfolio url', 'personal site', 'blog', 'website', 'online portfolio'],
  },
  website_url: {
    label: 'Website',
    category: 'links',
    synonyms: ['website', 'homepage', 'url', 'web url', 'other website'],
  },

  // ── Documents ──
  resume_file: {
    label: 'Resume / CV',
    category: 'documents',
    synonyms: ['resume', 'cv', 'curriculum vitae', 'attach resume', 'upload resume', 'resume/cv', 'lebenslauf'],
  },
  cover_letter_file: {
    label: 'Cover Letter File',
    category: 'documents',
    synonyms: ['cover letter file', 'attach cover letter', 'upload cover letter', 'cover letter attachment'],
  },
  cover_letter_text: {
    label: 'Cover Letter Text',
    category: 'documents',
    synonyms: ['cover letter', 'cover letter text', 'message to hiring manager', 'additional information', 'note to recruiter'],
  },

  // ── Work Authorization & Sponsorship ──
  legally_authorized: {
    label: 'Legally Authorized to Work',
    category: 'work_auth',
    synonyms: [
      'authorized to work',
      'legally authorized',
      'right to work',
      'eligible to work',
      'employment authorization',
      'work authorization',
      'legal right to work',
      'are you legally authorized to work in',
    ],
  },
  requires_sponsorship: {
    label: 'Requires Visa Sponsorship',
    category: 'work_auth',
    synonyms: [
      'require sponsorship',
      'visa sponsorship',
      'require visa sponsorship',
      'sponsorship now or in the future',
      'will you now or in the future require sponsorship',
      'need visa sponsorship',
      'immigration sponsorship',
      'require work authorization sponsorship',
    ],
  },
  visa_status: {
    label: 'Visa Status / Work Permit',
    category: 'work_auth',
    synonyms: ['visa status', 'work permit type', 'current visa', 'immigration status', 'work permit'],
  },

  // ── Compensation ──
  salary_expectation: {
    label: 'Salary Expectation',
    category: 'compensation',
    synonyms: [
      'salary',
      'desired salary',
      'expected salary',
      'salary expectation',
      'compensation',
      'desired compensation',
      'expected compensation',
      'pay expectation',
      'remuneration',
      'ctc',
      'day rate',
      'hourly rate',
      'gross salary',
    ],
  },

  // ── Experience & Education ──
  current_company: {
    label: 'Current Company',
    category: 'experience',
    synonyms: ['current company', 'current employer', 'present employer', 'most recent company', 'employer'],
  },
  current_title: {
    label: 'Current Job Title',
    category: 'experience',
    synonyms: ['current title', 'current job title', 'present title', 'most recent title', 'headline', 'job title'],
  },
  years_of_experience: {
    label: 'Years of Experience',
    category: 'experience',
    synonyms: ['years of experience', 'total experience', 'years of professional experience', 'how many years of experience'],
  },
  school: {
    label: 'School / University',
    category: 'education',
    synonyms: ['school', 'university', 'college', 'institution', 'educational institution'],
  },
  degree: {
    label: 'Degree',
    category: 'education',
    synonyms: ['degree', 'highest degree', 'level of education', 'qualification', 'degree level'],
  },
  discipline: {
    label: 'Field of Study / Major',
    category: 'education',
    synonyms: ['discipline', 'field of study', 'major', 'area of study', 'specialization'],
  },

  // ── General Application Questions ──
  how_heard: {
    label: 'How Did You Hear About Us',
    category: 'general',
    synonyms: ['how did you hear about us', 'how did you hear about this role', 'source', 'referral source', 'how did you find out about this position'],
  },
  start_date: {
    label: 'Earliest Start Date / Notice Period',
    category: 'general',
    synonyms: ['start date', 'earliest start date', 'notice period', 'availability', 'when can you start'],
  },
  consent_terms: {
    label: 'Consent / GDPR / Terms Agreement',
    category: 'general',
    synonyms: [
      'agree to terms',
      'privacy policy',
      'data processing consent',
      'i certify that the information',
      'i acknowledge',
      'gdpr consent',
      'terms and conditions',
    ],
  },

  // ── Sensitive Demographic Categories (Firewalled) ──
  gender: {
    label: 'Gender',
    category: 'demographics',
    isSensitive: true,
    synonyms: ['gender', 'sex', 'gender identity', 'how do you identify your gender'],
  },
  ethnicity: {
    label: 'Race / Ethnicity',
    category: 'demographics',
    isSensitive: true,
    synonyms: ['ethnicity', 'race', 'ethnic origin', 'racial background', 'hispanic or latino'],
  },
  veteran_status: {
    label: 'Veteran Status',
    category: 'demographics',
    isSensitive: true,
    synonyms: ['veteran status', 'military service', 'protected veteran', 'are you a veteran'],
  },
  disability_status: {
    label: 'Disability Status',
    category: 'demographics',
    isSensitive: true,
    synonyms: ['disability', 'disability status', 'do you have a disability', 'handicap', 'physical limitation'],
  },
  lgbtq_status: {
    label: 'LGBTQ+ / Sexual Orientation',
    category: 'demographics',
    isSensitive: true,
    synonyms: ['sexual orientation', 'lgbtq', 'lgbtq+', 'sexual identity'],
  },
};

/**
 * Normalizes text for comparison (lowercase, strips punctuation, decodes whitespace).
 */
export function normalizeSemanticText(text) {
  if (!text) return '';
  return String(text)
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^\w\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

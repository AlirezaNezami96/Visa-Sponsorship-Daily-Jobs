/**
 * classifier.js — Weighted Semantic Scoring & Field Classification Engine
 */

import { CANONICAL_FIELD_TAXONOMY, SENSITIVE_DEMOGRAPHIC_KEYS, normalizeSemanticText } from './taxonomy.js';

export class ClassificationResult {
  constructor({
    canonicalKey = 'unknown',
    confidence = 0,
    confidenceTier = 'UNKNOWN',
    category = 'general',
    isSensitive = false,
    signals = [],
  }) {
    this.canonicalKey = canonicalKey;
    this.confidence = confidence;
    this.confidenceTier = confidenceTier; // 'SAFE_AUTOFILL' | 'PROBABLE_AUTOFILL' | 'AI_REVIEW' | 'UNKNOWN'
    this.category = category;
    this.isSensitive = isSensitive;
    this.signals = signals;
  }
}

/**
 * Classifies a FormField using weighted multi-signal scoring against canonical taxonomy.
 */
export function classifyFormField(formField, customHints = {}) {
  const el = formField.element;
  const name = normalizeSemanticText(formField.name);
  const id = normalizeSemanticText(formField.htmlId);
  const autocomplete = normalizeSemanticText(formField.autocomplete);
  const ariaLabel = normalizeSemanticText(formField.ariaLabel);
  const placeholder = normalizeSemanticText(formField.placeholder);
  const dataAutomationId = normalizeSemanticText(formField.dataAutomationId);
  const labelText = formField.labelInfo ? formField.labelInfo.normalized : '';
  const fieldType = formField.fieldType;

  // 1. Check Custom ATS Hints first (High Priority +120)
  if (customHints && typeof customHints === 'object') {
    for (const [key, hint] of Object.entries(customHints)) {
      if (hint.selectors) {
        for (const sel of hint.selectors) {
          try {
            if (el.matches && el.matches(sel)) {
              return new ClassificationResult({
                canonicalKey: key,
                confidence: 100,
                confidenceTier: 'SAFE_AUTOFILL',
                category: CANONICAL_FIELD_TAXONOMY[key]?.category || 'general',
                isSensitive: SENSITIVE_DEMOGRAPHIC_KEYS.has(key),
                signals: [{ signal: 'ats_selector_hint', weight: 120, detail: sel }],
              });
            }
          } catch (_) {}
        }
      }
    }
  }

  // 2. Special detection: Consent / Terms Checkbox
  if (fieldType === 'checkbox') {
    const combined = `${name} ${id} ${labelText} ${ariaLabel}`;
    if (
      combined.includes('agree') ||
      combined.includes('consent') ||
      combined.includes('terms') ||
      combined.includes('privacy') ||
      combined.includes('certify') ||
      combined.includes('acknowledge') ||
      combined.includes('gdpr')
    ) {
      if (!combined.includes('marketing') && !combined.includes('newsletter') && !combined.includes('sms')) {
        return new ClassificationResult({
          canonicalKey: 'consent_terms',
          confidence: 95,
          confidenceTier: 'SAFE_AUTOFILL',
          category: 'general',
          signals: [{ signal: 'checkbox_consent_keyword', weight: 95 }],
        });
      }
    }
  }

  // 3. Special detection: Resume / Cover Letter Files
  if (fieldType === 'file') {
    const combined = `${name} ${id} ${labelText} ${ariaLabel} ${dataAutomationId}`;
    if (combined.includes('cover') && combined.includes('letter')) {
      return new ClassificationResult({
        canonicalKey: 'cover_letter_file',
        confidence: 95,
        confidenceTier: 'SAFE_AUTOFILL',
        category: 'documents',
        signals: [{ signal: 'file_cover_letter', weight: 95 }],
      });
    }
    if (combined.includes('resume') || combined.includes('cv') || combined.includes('curriculum') || combined.includes('file') || !combined) {
      return new ClassificationResult({
        canonicalKey: 'resume_file',
        confidence: 95,
        confidenceTier: 'SAFE_AUTOFILL',
        category: 'documents',
        signals: [{ signal: 'file_resume', weight: 95 }],
      });
    }
  }

  // 4. Multi-Signal Scoring across all Canonical Taxonomy entries
  let bestKey = 'unknown';
  let bestScore = 0;
  let bestSignals = [];

  for (const [key, tax] of Object.entries(CANONICAL_FIELD_TAXONOMY)) {
    let score = 0;
    const signals = [];

    const synonyms = tax.synonyms || [];

    // Signal A: Autocomplete attribute exact match (+100)
    if (autocomplete) {
      if (
        (key === 'first_name' && autocomplete === 'given-name') ||
        (key === 'last_name' && autocomplete === 'family-name') ||
        (key === 'email' && autocomplete === 'email') ||
        (key === 'phone' && (autocomplete === 'tel' || autocomplete === 'tel-national')) ||
        (key === 'postal_code' && autocomplete === 'postal-code') ||
        (key === 'country' && autocomplete === 'country-name') ||
        (key === 'address_line1' && autocomplete === 'address-line1')
      ) {
        score += 100;
        signals.push({ signal: 'autocomplete_match', weight: 100, detail: autocomplete });
      }
    }

    // Signal B: Exact Label or Synonym Match (+95)
    if (labelText) {
      for (const syn of synonyms) {
        const normSyn = normalizeSemanticText(syn);
        if (labelText === normSyn) {
          score += 95;
          signals.push({ signal: 'exact_label_synonym', weight: 95, detail: syn });
          break;
        } else if (labelText.startsWith(normSyn) || labelText.includes(` ${normSyn} `) || labelText.endsWith(normSyn)) {
          // Exclude false positive substring matches
          if (!(key === 'github_url' && labelText.includes('legitimate')) && !(key === 'website_url' && labelText.includes('hourly'))) {
            score += 85;
            signals.push({ signal: 'partial_label_synonym', weight: 85, detail: syn });
            break;
          }
        }
      }
    }

    // Signal C: aria-label match (+90)
    if (ariaLabel) {
      for (const syn of synonyms) {
        if (ariaLabel.includes(normalizeSemanticText(syn))) {
          score += 90;
          signals.push({ signal: 'aria_label_match', weight: 90, detail: syn });
          break;
        }
      }
    }

    // Signal D: Name attribute match (+85)
    if (name) {
      for (const syn of synonyms) {
        const cleanSyn = syn.replace(/\s+/g, '');
        if (name === cleanSyn || name === syn.replace(/\s+/g, '_') || name === syn.replace(/\s+/g, '-')) {
          score += 85;
          signals.push({ signal: 'exact_name_attribute', weight: 85, detail: syn });
          break;
        } else if (name.includes(cleanSyn) && cleanSyn.length > 3) {
          score += 70;
          signals.push({ signal: 'partial_name_attribute', weight: 70, detail: syn });
          break;
        }
      }
    }

    // Signal E: Placeholder match (+80)
    if (placeholder) {
      for (const syn of synonyms) {
        if (placeholder.includes(normalizeSemanticText(syn))) {
          score += 80;
          signals.push({ signal: 'placeholder_match', weight: 80, detail: syn });
          break;
        }
      }
    }

    // Signal F: data-automation-id or HTML ID match (+75)
    const idCombined = `${id} ${dataAutomationId}`;
    if (idCombined) {
      for (const syn of synonyms) {
        const cleanSyn = syn.replace(/\s+/g, '');
        if (idCombined.includes(cleanSyn) && cleanSyn.length > 3) {
          score += 75;
          signals.push({ signal: 'automation_id_match', weight: 75, detail: syn });
          break;
        }
      }
    }

    // Deduce highest single score category
    if (score > bestScore) {
      bestScore = score;
      bestKey = key;
      bestSignals = signals;
    }
  }

  // Normalize final confidence to 0-100 scale
  const finalConfidence = Math.min(100, bestScore);

  let confidenceTier = 'UNKNOWN';
  if (finalConfidence >= 90) {
    confidenceTier = 'SAFE_AUTOFILL';
  } else if (finalConfidence >= 70) {
    confidenceTier = 'PROBABLE_AUTOFILL';
  } else if (finalConfidence >= 50) {
    confidenceTier = 'AI_REVIEW';
  }

  // Check if classified as sensitive demographic
  const isSensitive = SENSITIVE_DEMOGRAPHIC_KEYS.has(bestKey);

  const result = new ClassificationResult({
    canonicalKey: finalConfidence >= 50 ? bestKey : (fieldType === 'textarea' ? 'custom_essay' : 'unknown'),
    confidence: finalConfidence,
    confidenceTier: finalConfidence >= 50 ? confidenceTier : (fieldType === 'textarea' ? 'AI_REVIEW' : 'UNKNOWN'),
    category: CANONICAL_FIELD_TAXONOMY[bestKey]?.category || (fieldType === 'textarea' ? 'essay' : 'general'),
    isSensitive,
    signals: bestSignals,
  });

  formField.classification = result.canonicalKey;
  formField.confidence = result.confidence;
  formField.confidenceTier = result.confidenceTier;
  formField.scoreSignals = result.signals;

  return result;
}

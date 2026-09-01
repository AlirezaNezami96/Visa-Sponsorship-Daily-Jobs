/**
 * Deterministic, shared ATS scoring module for VisaLane.
 *
 * Implements a reproducible 5-component rubric (0-100, healthy sweet-spot 75-90):
 *   1. Keyword / Skill Coverage:          40 pts (Must-have terms weighted higher)
 *   2. Title / Seniority Match:            15 pts
 *   3. Quantification Density:             15 pts (% of experience bullets with metrics)
 *   4. Section & Format Completeness:      15 pts (Standard structure, contact info)
 *   5. Natural-Language Repetition Penalty: -0 to -15 pts (Penalizes keyword stuffing)
 *
 * Used identically for both ats_score_before (baseline) and ats_score_after (tailored).
 */

export interface AtsScoreInput {
  resumeText: string;
  parsedData?: Record<string, unknown> | null;
  sections?: Array<{ type: string; label?: string; items?: unknown[] }> | null;
  job: {
    title?: string;
    description?: string;
    skills?: string[];
    must_haves?: string[];
    [key: string]: unknown;
  };
  isFresher?: boolean;
}

export interface AtsScoreBreakdown {
  total: number;
  keywordScore: number;
  titleScore: number;
  quantificationScore: number;
  completenessScore: number;
  penaltyScore: number;
  mustHavesFound: string[];
  mustHavesMissing: string[];
}

const STOP_WORDS = new Set([
  "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
  "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
  "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
  "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
  "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
  "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
  "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
  "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
  "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
  "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
  "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
  "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
  "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
  "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
  "they're", "they've", "this", "those", "through", "to", "too", "under",
  "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're",
  "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
  "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with",
  "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've",
  "your", "yours", "yourself", "yourselves", "will", "shall", "may", "might"
]);

/**
 * Extracts normalized technical and professional keywords from text.
 */
export function extractKeywords(text: string): string[] {
  if (!text) return [];
  const matches = text
    .toLowerCase()
    .match(/\b[a-z0-9][a-z0-9_\-\+\#\.]{1,35}\b/g) || [];

  return matches.filter((w) => w.length >= 2 && !STOP_WORDS.has(w));
}

/**
 * Extracts bullets from parsedData or section array.
 */
function extractAllBullets(input: AtsScoreInput): string[] {
  const bullets: string[] = [];

  // Check section list format
  if (Array.isArray(input.sections)) {
    for (const sec of input.sections) {
      if (Array.isArray(sec.items)) {
        for (const item of sec.items) {
          if (typeof item === "string") {
            bullets.push(item);
          } else if (item && typeof item === "object") {
            const obj = item as Record<string, unknown>;
            if (Array.isArray(obj.bullets)) {
              for (const b of obj.bullets) {
                if (typeof b === "string") bullets.push(b);
              }
            }
            if (Array.isArray(obj.highlights)) {
              for (const h of obj.highlights) {
                if (typeof h === "string") bullets.push(h);
              }
            }
          }
        }
      }
    }
  }

  // Check parsedData experience / projects format
  if (bullets.length === 0 && input.parsedData) {
    const exp = input.parsedData.experience;
    if (Array.isArray(exp)) {
      for (const e of exp) {
        if (e && typeof e === "object") {
          const obj = e as Record<string, unknown>;
          const highlights = Array.isArray(obj.highlights)
            ? (obj.highlights as string[])
            : Array.isArray(obj.bullets)
              ? (obj.bullets as string[])
              : [];
          bullets.push(...highlights.filter((h) => typeof h === "string"));
        }
      }
    }
  }

  // Fallback: extract line bullets from resume text
  if (bullets.length === 0 && input.resumeText) {
    const lines = input.resumeText.split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (/^[\u2022\u2023\u25E6\u2043\u2219\*\-\+]\s+/.test(trimmed)) {
        bullets.push(trimmed.replace(/^[\u2022\u2023\u25E6\u2043\u2219\*\-\+]\s+/, ""));
      }
    }
  }

  return bullets;
}

/**
 * Computes deterministic ATS score across 5 components.
 */
export function computeAtsScore(input: AtsScoreInput): AtsScoreBreakdown {
  const resumeText = input.resumeText || "";
  const resumeLower = resumeText.toLowerCase();
  const resumeKeywords = extractKeywords(resumeText);
  const resumeKwSet = new Set(resumeKeywords);

  const jobDesc = String(input.job.description || "");
  const jobTitle = String(input.job.title || "");
  const jobSkills = Array.isArray(input.job.skills) ? (input.job.skills as string[]) : [];
  const explicitMustHaves = Array.isArray(input.job.must_haves)
    ? (input.job.must_haves as string[])
    : jobSkills.slice(0, 5);

  // ── 1. Keyword / Skill Coverage (40 pts) ──────────────────────────────────
  const jdKeywords = extractKeywords(jobDesc);
  const jdKwSet = new Set(jdKeywords);

  // Must-have overlap (25 pts)
  const mustHavesFound: string[] = [];
  const mustHavesMissing: string[] = [];
  let mustHaveScore = 20;

  if (explicitMustHaves.length > 0) {
    for (const mh of explicitMustHaves) {
      const mhNorm = mh.toLowerCase().trim();
      if (resumeLower.includes(mhNorm) || resumeKwSet.has(mhNorm)) {
        mustHavesFound.push(mh);
      } else {
        mustHavesMissing.push(mh);
      }
    }
    mustHaveScore = Math.round((mustHavesFound.length / explicitMustHaves.length) * 25);
  }

  // General JD keyword overlap (15 pts)
  let generalKwScore = 10;
  if (jdKwSet.size > 0) {
    let matchCount = 0;
    for (const kw of jdKwSet) {
      if (resumeKwSet.has(kw)) matchCount++;
    }
    generalKwScore = Math.round((matchCount / jdKwSet.size) * 15);
  }

  const keywordScore = Math.min(40, mustHaveScore + generalKwScore);

  // ── 2. Title / Seniority Match (15 pts) ───────────────────────────────────
  let titleScore = 5;
  const candidateTitles: string[] = [];
  if (input.parsedData && Array.isArray(input.parsedData.job_titles)) {
    candidateTitles.push(...(input.parsedData.job_titles as string[]));
  }
  if (input.parsedData && Array.isArray(input.parsedData.experience)) {
    for (const e of input.parsedData.experience as Array<Record<string, unknown>>) {
      if (typeof e?.title === "string") candidateTitles.push(e.title);
    }
  }

  const jt = jobTitle.toLowerCase().trim();
  const jtTokens = extractKeywords(jt);

  if (jt && candidateTitles.length > 0) {
    for (const t of candidateTitles) {
      const tNorm = t.toLowerCase().trim();
      if (tNorm === jt) {
        titleScore = 15;
        break;
      }
      const tTokens = new Set(extractKeywords(tNorm));
      if (jtTokens.length > 0) {
        const overlap = jtTokens.filter((tok) => tTokens.has(tok)).length;
        const ratio = overlap / jtTokens.length;
        const currentScore = Math.round(ratio * 14);
        if (currentScore > titleScore) titleScore = currentScore;
      }
    }
  } else if (resumeLower.includes(jt)) {
    titleScore = 12;
  }

  // ── 3. Quantification Density (15 pts) ────────────────────────────────────
  // Checks % of experience bullets containing numbers, multipliers, or dollar figures
  const bullets = extractAllBullets(input);
  const metricRegex = /\b\d+%|\b\d+x\b|\$\d+|\b\d{2,}\b|\b\d+\s*(?:k|m|million|billion|users|clients|requests|ms|seconds|minutes|hours|days|engineers|team members|developers)\b/i;

  let quantificationScore = 8;
  if (bullets.length > 0) {
    let quantifiedCount = 0;
    for (const b of bullets) {
      if (metricRegex.test(b)) quantifiedCount++;
    }
    const ratio = quantifiedCount / bullets.length;
    // 50%+ of bullets with metrics yields max 15 pts
    quantificationScore = Math.min(15, Math.round(ratio * 30));
  }

  // ── 4. Section & Format Completeness (15 pts) ─────────────────────────────
  let completenessScore = 0;
  const hasContact = Boolean(
    resumeText.match(/[\w.-]+@[\w.-]+\.\w+/) ||
    resumeText.match(/(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}/)
  );
  if (hasContact) completenessScore += 4;

  const hasSummary = Boolean(
    input.parsedData?.summary ||
    resumeLower.includes("summary") ||
    resumeLower.includes("profile")
  );
  if (hasSummary) completenessScore += 3;

  const hasSkills = Boolean(
    (input.parsedData?.skills as string[] | undefined)?.length ||
    resumeLower.includes("skills") ||
    resumeLower.includes("technologies")
  );
  if (hasSkills) completenessScore += 4;

  const hasEdu = Boolean(
    (input.parsedData?.education as unknown[] | undefined)?.length ||
    resumeLower.includes("education") ||
    resumeLower.includes("university") ||
    resumeLower.includes("degree")
  );
  if (hasEdu) completenessScore += 4;

  completenessScore = Math.min(15, completenessScore);

  // ── 5. Natural-Language Repetition Penalty (0 to -15 pts) ─────────────────
  // Penalizes exact-phrase keyword stuffing (keywords appearing 6+ times)
  const kwCounts: Record<string, number> = {};
  for (const kw of resumeKeywords) {
    if (kw.length >= 3) {
      kwCounts[kw] = (kwCounts[kw] || 0) + 1;
    }
  }

  let penaltyScore = 0;
  for (const [kw, count] of Object.entries(kwCounts)) {
    // If a non-trivial keyword appears 7+ times in a standard resume, penalize
    if (count >= 7 && !["development", "software", "system", "engineer", "team", "project"].includes(kw)) {
      penaltyScore -= Math.min(5, count - 6);
    }
  }
  penaltyScore = Math.max(-15, penaltyScore);

  const rawTotal = keywordScore + titleScore + quantificationScore + completenessScore + penaltyScore;
  const total = Math.max(0, Math.min(100, rawTotal));

  return {
    total,
    keywordScore,
    titleScore,
    quantificationScore,
    completenessScore,
    penaltyScore,
    mustHavesFound,
    mustHavesMissing,
  };
}

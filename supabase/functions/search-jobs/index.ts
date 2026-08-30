/**
 * GET /functions/v1/search-jobs
 * Auth required (optional — unauthenticated users get unscored results).
 *
 * Full-featured job search with:
 *   - Cursor-based pagination (posted_at + id) for stable, infinite scroll
 *   - Multi-field filtering: country, work_mode, visa_verified, keyword, salary
 *   - Per-user match scoring when a profile with skills is present
 *   - Signed-URL safe (no secrets returned, job data only)
 *
 * Query params:
 *   cursor        string    — opaque cursor from previous response.next_cursor
 *   offset        number    — offset-based pagination (alternative to cursor)
 *   limit         number    — page size, 1–50, default 20
 *   country       string    — ISO code or country name filter
 *   work_mode     string    — remote|hybrid|onsite
 *   visa_verified boolean   — true = only visa-verified jobs
 *   keyword       string    — full-text search in title + description
 *   min_salary    number    — minimum annual salary (USD)
 *   sort          string    — match_score|posted_at (default: posted_at when no profile, match_score otherwise)
 *
 * Response:
 * {
 *   jobs: Job[],
 *   next_cursor: string|null,  // null = end of results
 *   next_offset: number|null,  // offset mode: index of the next page
 *   has_more: boolean,
 *   total_in_filter: number,   // approximate count (for UI indicator)
 *   scored: boolean,           // true if match scores are meaningful
 * }
 */
import { createUserClient, createAdminClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, serverError } from "../_shared/http.ts";

const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 50;
const FIRST_PAGE_CACHE_TTL_MS = 5 * 60 * 1000; // spec §8.2: 5 minutes

// In-instance first-page cache: key = filter signature, value = first-page
// rows + timestamp. New jobs appear within the TTL refresh. Per-isolate,
// so it only accelerates hot filter combinations on warm instances.
const firstPageCache = new Map<string, { at: number; rows: unknown[] }>();

function cacheKey(params: URLSearchParams, sort: string): string {
  return ["country", "work_mode", "visa_verified", "keyword", "min_salary", "sort"]
    .map((k) => `${k}=${params.get(k) ?? ""}`)
    .join("&") + `|${sort}`;
}

const JOB_COLUMNS = [
  "id", "title", "company", "company_id", "country", "country_code",
  "work_mode", "location", "posted_at", "apply_url", "url",
  "visa_sponsorship_verified", "visa_sponsorship_confidence",
  "skills", "description", "salary_min", "salary_max", "salary_currency",
  "work_type", "seniority", "created_at",
].join(", ");

interface Cursor {
  posted_at: string;
  id: string;
}

export function parseCursor(raw: string | null): Cursor | null {
  if (!raw) return null;
  try {
    const decoded = atob(raw);
    const parsed = JSON.parse(decoded);
    if (parsed.posted_at && parsed.id) return parsed as Cursor;
  } catch {
    // invalid cursor — treat as first page
  }
  return null;
}

export function encodeCursor(postedAt: string, id: string): string {
  return btoa(JSON.stringify({ posted_at: postedAt, id }));
}

export function parseLimit(raw: string | null): number {
  const n = parseInt(raw ?? "", 10);
  if (Number.isNaN(n) || n < 1) return DEFAULT_LIMIT;
  return Math.min(n, MAX_LIMIT);
}

export function parseOffset(raw: string | null): number | null {
  if (raw === null) return null;
  const n = parseInt(raw, 10);
  if (Number.isNaN(n) || n < 0) return 0;
  return n;
}

function applyFilters(
  // deno-lint-ignore no-explicit-any
  query: any,
  params: URLSearchParams,
  cursor: Cursor | null,
  // deno-lint-ignore no-explicit-any
): any {
  // Active jobs only
  query = query.eq("status", "active");

  // Cursor pagination with full (posted_at, id) tie-break: rows sharing the
  // same posted_at are excluded via OR so no page skips or repeats them.
  if (cursor) {
    query = query.or(
      `posted_at.lt.${cursor.posted_at},` +
        `and(posted_at.eq.${cursor.posted_at},id.lt.${cursor.id})`,
    );
  }

  // Country filter
  const country = params.get("country");
  if (country) {
    const upperCountry = country.toUpperCase();
    query = query.or(
      `country_code.eq.${upperCountry},country.ilike.%${country}%`
    );
  }

  // Work mode filter
  const workMode = params.get("work_mode");
  if (workMode) {
    query = query.eq("work_mode", workMode);
  }

  // Visa verified filter
  const visaVerified = params.get("visa_verified");
  if (visaVerified === "true") {
    query = query.eq("visa_sponsorship_verified", true);
  }

  // Min salary filter
  const minSalary = params.get("min_salary");
  if (minSalary) {
    const sal = parseInt(minSalary, 10);
    if (!Number.isNaN(sal)) {
      query = query.gte("salary_min", sal);
    }
  }

  // Keyword filter (title or description)
  const keyword = params.get("keyword")?.trim();
  if (keyword) {
    const safe = keyword.replace(/[%_']/g, "\\$&");
    query = query.or(
      `title.ilike.%${safe}%,description.ilike.%${safe}%`
    );
  }

  return query;
}

Deno.serve(async (req) => {
  const preflight = handleOptions(req);
  if (preflight) return preflight;
  if (req.method !== "GET") {
    return json({ error: { code: "method_not_allowed", message: "GET only" } }, { status: 405 });
  }

  const url = new URL(req.url);
  const params = url.searchParams;
  const limit = parseLimit(params.get("limit"));
  const cursor = parseCursor(params.get("cursor"));
  const offset = parseOffset(params.get("offset"));
  const sortParam = params.get("sort");
  const useOffsetMode = offset !== null && !cursor;

  try {
    // ── Load profile (optional auth) ───────────────────────────────────────
    let profile: Record<string, unknown> | null = null;
    let scored = false;
    let userId: string | null = null;

    if (hasAuthHeader(req)) {
      const userClient = createUserClient(req);
      const user = await getAuthUser(userClient);
      if (user) {
        userId = user.id;
        const { data } = await userClient
          .from("profiles")
          .select("id, skills_cache, job_titles, preferred_countries, preferred_work_modes, experience_years")
          .eq("id", user.id)
          .maybeSingle();
        profile = data as Record<string, unknown> | null;
        const profileSkills = (profile?.skills_cache as string[] | null) ?? [];
        scored = profileSkills.length > 0;
      }
    }

    // ── Fetch jobs ─────────────────────────────────────────────────────────
    const admin = createAdminClient();

    const wantsDefaultSort = sortParam === "match_score" ||
      (!sortParam && scored);
    const effectiveSort = sortParam ?? (scored ? "match_score" : "posted_at");
    const cacheK = cacheKey(params, effectiveSort);
    const isCacheablePage = !cursor && !useOffsetMode && limit === DEFAULT_LIMIT;

    // First-page cache (spec §8.2): only the default-size, unfiltered-by-page
    // first page of each filter combination is cached for 5 minutes.
    let cachedRows: unknown[] | null = null;
    if (isCacheablePage) {
      const hit = firstPageCache.get(cacheK);
      if (hit && Date.now() - hit.at < FIRST_PAGE_CACHE_TTL_MS) {
        cachedRows = hit.rows;
      }
    }

    let allRows: Array<Record<string, unknown>>;
    if (cachedRows) {
      allRows = cachedRows as Array<Record<string, unknown>>;
    } else {
      // deno-lint-ignore no-explicit-any
      let query: any = admin.from("jobs").select(JOB_COLUMNS);
      query = applyFilters(query, params, cursor);

      if (useOffsetMode) {
        query = query.range(offset!, offset! + limit);
      } else {
        // Fetch limit+1 to know if there's a next page
        query = query.limit(limit + 1);
      }

      // Always order deterministically by posted_at DESC, id DESC for tie-breaking
      query = query
        .order("posted_at", { ascending: false })
        .order("id", { ascending: false });

      const { data: rows, error: fetchError } = await query;
      if (fetchError) {
        console.error("search-jobs fetch error:", fetchError.message);
        return serverError("Failed to fetch jobs");
      }
      allRows = ((rows ?? []) as unknown) as Array<Record<string, unknown>>;

      if (isCacheablePage) {
        firstPageCache.set(cacheK, { at: Date.now(), rows: allRows });
        // Bound the cache so a hostile variety of filters can't grow it
        if (firstPageCache.size > 200) {
          const oldest = firstPageCache.keys().next().value;
          if (oldest !== undefined) firstPageCache.delete(oldest);
        }
      }
    }

    const hasMore = allRows.length > limit;
    const jobs = allRows.slice(0, limit);

    // ── Match scoring & user_job_scores cache read ───────────────────────────
    let scoredJobs = jobs;
    if (scored && profile) {
      // Check pre-calculated scores in user_job_scores table
      const jobIds = jobs.map((j) => String(j.id));
      const scoreMap = new Map<string, { score: number; match_label: string }>();

      if (userId && jobIds.length > 0) {
        try {
          const { data: cachedScores } = await admin
            .from("user_job_scores")
            .select("job_id, score, match_label")
            .eq("user_id", userId)
            .in("job_id", jobIds);

          if (cachedScores) {
            for (const cs of cachedScores) {
              scoreMap.set(String(cs.job_id), {
                score: Number(cs.score),
                match_label: String(cs.match_label),
              });
            }
          }
        } catch {
          // DB score cache read failure is non-fatal; fall back to on-the-fly calculation
        }
      }

      scoredJobs = jobs.map((job) => {
        const jid = String(job.id);
        const fromDb = scoreMap.get(jid);
        if (fromDb) {
          return {
            ...job,
            resume_match_score: fromDb.score,
            match_label: fromDb.match_label,
          };
        }
        const matchScore = computeMatchScoreEdge(profile, job);
        return {
          ...job,
          resume_match_score: matchScore,
          match_label: matchLabel(matchScore),
        };
      });

      // Sort by match score if requested or if no cursor (first page with match sort)
      const wantsMatchSort = wantsDefaultSort;
      if (wantsMatchSort) {
        scoredJobs = [...scoredJobs].sort(
          (a, b) => ((b.resume_match_score as number) ?? 0) - ((a.resume_match_score as number) ?? 0),
        );
      }
    }

    // ── Next cursor / offset ────────────────────────────────────────────────
    let nextCursor: string | null = null;
    if (!useOffsetMode && hasMore && jobs.length > 0) {
      const last = jobs[jobs.length - 1];
      const lastPostedAt = String(last.posted_at ?? "");
      const lastId = String(last.id ?? "");
      if (lastPostedAt && lastId) {
        nextCursor = encodeCursor(lastPostedAt, lastId);
      }
    }
    const nextOffset = useOffsetMode && hasMore ? offset! + limit : null;

    // ── Approximate count (for UI "Showing N of ~M jobs") ─────────────────
    let totalInFilter = 0;
    try {
      // deno-lint-ignore no-explicit-any
      let countQuery: any = admin.from("jobs").select("*", { count: "estimated", head: true });
      countQuery = applyFilters(countQuery, params, null);
      const { count } = await countQuery;
      totalInFilter = count ?? 0;
    } catch {
      // Count failure is non-fatal
    }

    const headers = !userId
      ? { "Cache-Control": "public, max-age=300, stale-while-revalidate=60" }
      : undefined;

    return json({
      jobs: scoredJobs,
      next_cursor: nextCursor,
      next_offset: nextOffset,
      has_more: hasMore,
      total_in_filter: totalInFilter,
      scored,
      user_id: userId,
    }, { headers });
  } catch (err) {
    console.error("search-jobs error:", err);
    return serverError();
  }
});

// ── Inline match scoring (no Python engine call for performance) ───────────
// Weights mirror src/job_radar/jobs/scorer.py exactly (spec §3.2):
// title 40 + skills 50 + experience 10 (base 100), location +10 bonus,
// visa +5 bonus, capped at 100. Rare-skill matches weigh 1.5x inside the
// skills component (both runtimes use the same COMMON_SKILLS set).

const COMMON_SKILLS = new Set([
  "git", "agile", "sql", "rest api", "communication", "docker",
  "javascript", "python", "aws", "leadership", "mentoring",
  "teamwork", "collaboration", "problem solving", "time management",
  "scrum", "project management",
]);

const SKILL_SYNONYMS: Record<string, string> = {
  js: "javascript",
  ts: "typescript",
  node: "nodejs",
  "node js": "nodejs",
  nodejs: "nodejs",
  reactjs: "react",
  "react js": "react",
  vuejs: "vue",
  "vue js": "vue",
  angularjs: "angular",
  "angular js": "angular",
  nextjs: "nextjs",
  "next js": "nextjs",
  nuxtjs: "nuxtjs",
  "nuxt js": "nuxtjs",
  k8s: "kubernetes",
  kube: "kubernetes",
  postgres: "postgresql",
  psql: "postgresql",
  aws: "aws",
  "amazon web services": "aws",
  gcp: "gcp",
  "google cloud": "gcp",
  "google cloud platform": "gcp",
  golang: "go",
  cpp: "cpp",
  csharp: "csharp",
  dotnet: "dotnet",
  ml: "machine learning",
  ai: "artificial intelligence",
  nlp: "natural language processing",
  cicd: "cicd",
  "ci cd": "cicd",
};

function normToken(s: string): string {
  const cleaned = s.toLowerCase().replace(/[^a-z0-9\s]/g, "").trim();
  const base = cleaned.replace(/\s*v?\d+(\.\d+)*\b/, "").trim();
  const target = base || cleaned;
  return SKILL_SYNONYMS[target] ?? SKILL_SYNONYMS[cleaned] ?? target;
}

function normSet(items: string[]): Set<string> {
  return new Set(items.map(normToken).filter(Boolean));
}

export function computeMatchScoreEdge(profile: Record<string, unknown>, job: Record<string, unknown>): number {
  const userSkills = normSet((profile.skills_cache ?? []) as string[]);
  const jobSkills = normSet((job.skills ?? []) as string[]);
  const userTitles = ((profile.job_titles ?? []) as string[]).map((t) => t.toLowerCase());
  const jobTitle = String(job.title ?? "").toLowerCase();
  const userYears = (profile.experience_years as number | null) ?? null;

  let score = 0;

  // Skills (50 pts, rarity-weighted)
  if (jobSkills.size > 0 && userSkills.size > 0) {
    let matchedWeight = 0;
    let totalWeight = 0;
    for (const s of jobSkills) {
      const w = COMMON_SKILLS.has(s) ? 1.0 : 1.5;
      totalWeight += w;
      if (userSkills.has(s)) matchedWeight += w;
    }
    score += Math.round((matchedWeight / totalWeight) * 50);
  } else if (jobSkills.size === 0) {
    score += 25; // neutral when job has no skills listed
  }

  // Title (40 pts)
  if (userTitles.length > 0 && jobTitle) {
    const titleWords = new Set(jobTitle.split(/\s+/));
    let titleScore = 0;
    for (const t of userTitles) {
      if (t === jobTitle) { titleScore = 40; break; }
      if (t.includes(jobTitle) || jobTitle.includes(t)) { titleScore = Math.max(titleScore, 36); }
      const tWords = new Set(t.split(/\s+/));
      const tOverlap = [...tWords].filter((w) => titleWords.has(w)).length;
      if (tOverlap > 0) titleScore = Math.max(titleScore, Math.round((tOverlap / Math.max(tWords.size, titleWords.size)) * 32));
    }
    score += titleScore;
  } else {
    score += 10; // neutral
  }

  // Experience (10 pts) — mirrors Python score_experience_level
  const minYears = (job.min_experience_years as number | null) ?? null;
  if (userYears === null || (minYears === null)) {
    score += 5; // neutral when unknown
  } else {
    const maxYears = (job.max_experience_years as number | null) ?? 20;
    if (minYears <= userYears && userYears <= maxYears) score += 10;
    else if (userYears < minYears) {
      const gap = minYears - userYears;
      score += gap <= 1 ? 8 : gap <= 2 ? 5 : 0;
    } else {
      const gap = userYears - maxYears;
      score += gap <= 2 ? 9 : Math.max(10 - gap, 0);
    }
  }

  // Work mode (5 of the +10 location bonus)
  const preferredModes = ((profile.preferred_work_modes ?? []) as string[]).map((m) => m.toLowerCase());
  const jobMode = String(job.work_mode ?? "").toLowerCase();
  if (preferredModes.length === 0 || preferredModes.includes(jobMode)) score += 5;
  else if (preferredModes.includes("remote") && jobMode === "hybrid") score += 3;

  // Country (other 5 of the +10 location bonus)
  const preferredCountries = ((profile.preferred_countries ?? []) as string[]).map((c) => c.toUpperCase());
  const jobCountry = String(job.country_code ?? job.country ?? "").toUpperCase();
  if (preferredCountries.length === 0 || preferredCountries.includes(jobCountry)) score += 5;

  // Visa (+5 bonus)
  if (job.visa_sponsorship_verified === true) score += 5;
  else if ((job.visa_sponsorship_confidence as number ?? 0) >= 70) score += 4;
  else if ((job.visa_sponsorship_confidence as number ?? 0) >= 50) score += 2;

  return Math.min(100, score);
}

export function matchLabel(score: number): string {
  if (score >= 80) return "great_match";
  if (score >= 60) return "good_match";
  if (score >= 40) return "fair_match";
  return "low_match";
}

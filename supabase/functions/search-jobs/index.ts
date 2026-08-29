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

function parseCursor(raw: string | null): Cursor | null {
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

function encodeCursor(postedAt: string, id: string): string {
  return btoa(JSON.stringify({ posted_at: postedAt, id }));
}

function parseLimit(raw: string | null): number {
  const n = parseInt(raw ?? "", 10);
  if (Number.isNaN(n) || n < 1) return DEFAULT_LIMIT;
  return Math.min(n, MAX_LIMIT);
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

  // Cursor pagination (posted_at DESC, id DESC for stability)
  if (cursor) {
    query = query.lt("posted_at", cursor.posted_at);
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
  const sortParam = params.get("sort");

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
    // deno-lint-ignore no-explicit-any
    let query: any = admin.from("jobs").select(JOB_COLUMNS);
    query = applyFilters(query, params, cursor);

    // Fetch limit+1 to know if there's a next page
    const fetchLimit = limit + 1;
    query = query
      .order("posted_at", { ascending: false })
      .order("id", { ascending: false })
      .limit(fetchLimit);

    const { data: rows, error: fetchError } = await query;
    if (fetchError) {
      console.error("search-jobs fetch error:", fetchError.message);
      return serverError("Failed to fetch jobs");
    }

    const allRows = ((rows ?? []) as unknown) as Array<Record<string, unknown>>;
    const hasMore = allRows.length > limit;
    const jobs = allRows.slice(0, limit);

    // ── Match scoring ──────────────────────────────────────────────────────
    let scoredJobs = jobs;
    if (scored && profile) {
      scoredJobs = jobs.map((job) => {
        const matchScore = computeMatchScoreEdge(profile, job);
        return {
          ...job,
          resume_match_score: matchScore,
          match_label: matchLabel(matchScore),
        };
      });

      // Sort by match score if requested or if no cursor (first page with match sort)
      const wantsMatchSort = sortParam === "match_score" || (!sortParam && !cursor && scored);
      if (wantsMatchSort) {
        scoredJobs = [...scoredJobs].sort(
          (a, b) => ((b.resume_match_score as number) ?? 0) - ((a.resume_match_score as number) ?? 0),
        );
      }
    }

    // ── Next cursor ────────────────────────────────────────────────────────
    let nextCursor: string | null = null;
    if (hasMore && jobs.length > 0) {
      const last = jobs[jobs.length - 1];
      const lastPostedAt = String(last.posted_at ?? "");
      const lastId = String(last.id ?? "");
      if (lastPostedAt && lastId) {
        nextCursor = encodeCursor(lastPostedAt, lastId);
      }
    }

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

    return json({
      jobs: scoredJobs,
      next_cursor: nextCursor,
      has_more: hasMore,
      total_in_filter: totalInFilter,
      scored,
      user_id: userId,
    });
  } catch (err) {
    console.error("search-jobs error:", err);
    return serverError();
  }
});

// ── Inline match scoring (no Python engine call for performance) ───────────

function computeMatchScoreEdge(profile: Record<string, unknown>, job: Record<string, unknown>): number {
  const userSkills = normSet((profile.skills_cache ?? []) as string[]);
  const jobSkills = normSet((job.skills ?? []) as string[]);
  const userTitles = ((profile.job_titles ?? []) as string[]).map((t) => t.toLowerCase());
  const jobTitle = String(job.title ?? "").toLowerCase();

  let score = 0;

  // Skills (50 pts)
  if (jobSkills.size > 0 && userSkills.size > 0) {
    const intersection = new Set([...userSkills].filter((s) => jobSkills.has(s)));
    const coverage = intersection.size / jobSkills.size;
    score += Math.round(coverage * 50);
  } else if (jobSkills.size === 0) {
    score += 25; // neutral when job has no skills listed
  }

  // Title (20 pts)
  if (userTitles.length > 0 && jobTitle) {
    const titleWords = new Set(jobTitle.split(/\s+/));
    let titleScore = 0;
    for (const t of userTitles) {
      if (t === jobTitle) { titleScore = 20; break; }
      if (t.includes(jobTitle) || jobTitle.includes(t)) { titleScore = Math.max(titleScore, 17); }
      const tWords = new Set(t.split(/\s+/));
      const tOverlap = [...tWords].filter((w) => titleWords.has(w)).length;
      if (tOverlap > 0) titleScore = Math.max(titleScore, Math.round((tOverlap / Math.max(tWords.size, titleWords.size)) * 18));
    }
    score += titleScore;
  } else {
    score += 10; // neutral
  }

  // Visa (10 pts)
  if (job.visa_sponsorship_verified === true) score += 10;
  else if ((job.visa_sponsorship_confidence as number ?? 0) >= 70) score += 8;
  else if ((job.visa_sponsorship_confidence as number ?? 0) >= 50) score += 5;

  // Work mode (10 pts)
  const preferredModes = ((profile.preferred_work_modes ?? []) as string[]).map((m) => m.toLowerCase());
  const jobMode = String(job.work_mode ?? "").toLowerCase();
  if (preferredModes.length === 0 || preferredModes.includes(jobMode)) score += 10;
  else if (preferredModes.includes("remote") && jobMode === "hybrid") score += 5;

  // Location (10 pts)
  const preferredCountries = ((profile.preferred_countries ?? []) as string[]).map((c) => c.toUpperCase());
  const jobCountry = String(job.country_code ?? job.country ?? "").toUpperCase();
  if (preferredCountries.length === 0 || preferredCountries.includes(jobCountry)) score += 10;

  return Math.min(100, score);
}

function normSet(items: string[]): Set<string> {
  return new Set(items.map((s) => s.toLowerCase().replace(/[^a-z0-9\s]/g, "").trim()));
}

function matchLabel(score: number): string {
  if (score >= 80) return "great_match";
  if (score >= 60) return "good_match";
  if (score >= 40) return "fair_match";
  return "low_match";
}

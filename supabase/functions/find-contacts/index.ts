/**
 * POST /functions/v1/find-contacts
 * Auth required. User-facing endpoint to trigger contact finding for a
 * specific job. Calls the Python engine to run the enrichment chain:
 *   Apollo People Search → posting email extraction → pattern guesses
 *   → LinkedIn search deep-links.
 *
 * Body: { job_id: string }
 *
 * Response:
 * {
 *   contacts: Array<{
 *     name: string|null,
 *     title: string|null,
 *     email: string|null,
 *     email_status: "verified"|"generic"|"pattern_guess"|"not_found",
 *     email_confidence: number|null,
 *     linkedin_search_url: string|null,
 *     source_type: string,
 *   }>,
 *   count: number,
 *   from_cache: boolean,
 * }
 */
import { createUserClient, createAdminClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, badRequest, unauthorized, serverError, notFound } from "../_shared/http.ts";
import { getEnv } from "../_shared/env.ts";

const CACHE_STALENESS_HOURS = 24;

function buildSearchLinks(company: string, title: string) {
  const encComp = encodeURIComponent(company.trim());
  const encTitle = encodeURIComponent(`${company.trim()} ${title.trim()} manager`);
  return {
    recruiter_search: `https://www.linkedin.com/search/results/people/?keywords=${encComp}%20recruiter`,
    talent_acquisition_search: `https://www.linkedin.com/search/results/people/?keywords=${encComp}%20talent%20acquisition`,
    hiring_manager_search: `https://www.linkedin.com/search/results/people/?keywords=${encTitle}`,
    department_lead_search: `https://www.linkedin.com/search/results/people/?keywords=${encComp}%20engineering%20manager`,
  };
}

function buildFallbackInstructions(
  companyName: string,
  companyDomain: string,
  jobTitle: string,
  jobUrl: string,
) {
  const links = buildSearchLinks(companyName, jobTitle);
  const domain = companyDomain.replace(/^https?:\/\//, "").split("/")[0].trim();
  const genericEmails = domain
    ? [`careers@${domain}`, `talent@${domain}`, `recruiting@${domain}`, `jobs@${domain}`]
    : [];

  return [
    {
      step: 1,
      title: "Search LinkedIn for Recruiters",
      instruction: `Search for talent acquisition specialists and recruiters at ${companyName}.`,
      action_url: links.recruiter_search,
      action_label: `Find Recruiters at ${companyName}`,
    },
    {
      step: 2,
      title: "Search for Hiring Manager",
      instruction: `Search for the hiring manager or department lead for ${jobTitle} at ${companyName}.`,
      action_url: links.hiring_manager_search,
      action_label: `Find ${jobTitle} Managers`,
    },
    {
      step: 3,
      title: "Check Original Job Posting",
      instruction: "Review the full job listing on the company careers site for direct contact emails or application instructions.",
      action_url: jobUrl,
      action_label: "View Original Job Posting",
    },
    {
      step: 4,
      title: "Try General Department Mailboxes",
      instruction: "If no personal contact is available, reach out directly to the company's hiring inbox.",
      suggested_emails: genericEmails,
      action_label: "Copy Email Addresses",
    },
  ];
}

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
  const preflight = handleOptions(req);
  if (preflight) return preflight;
  if (req.method !== "POST") {
    return json({ error: { code: "method_not_allowed", message: "POST only" } }, { status: 405 });
  }
  if (!hasAuthHeader(req)) return unauthorized();

  try {
    const userClient = createUserClient(req);
    const user = await getAuthUser(userClient);
    if (!user) return unauthorized();

    const body = await req.json().catch(() => ({}));
    const jobId: string = typeof body.job_id === "string" ? body.job_id : "";
    if (!jobId) return badRequest("job_id is required");

    // Verify job exists and user has access (via RLS)
    const { data: job, error: jobErr } = await userClient
      .from("jobs")
      .select("id, company, company_id, company_domain, title, description, url, apply_url")
      .eq("id", jobId)
      .maybeSingle();

    if (jobErr || !job) return notFound("Job not found");

    const companyName = String(job.company ?? "Unknown Company");
    const companyDomain = String(job.company_domain ?? "");
    const jobTitle = String(job.title ?? "Open Position");
    const jobUrl = String(job.apply_url ?? job.url ?? "");

    const searchLinks = buildSearchLinks(companyName, jobTitle);
    const fallbackInstructions = buildFallbackInstructions(
      companyName,
      companyDomain,
      jobTitle,
      jobUrl,
    );

    const admin = createAdminClient();

    // ── Check cache: return existing contacts if fresh ─────────────────────
    const cacheThreshold = new Date(Date.now() - CACHE_STALENESS_HOURS * 60 * 60 * 1000).toISOString();
    const { data: cached } = await admin
      .from("job_people")
      .select("id, name, title, email, email_status, email_confidence, linkedin_search_url, source_type, confidence_score, found_at")
      .eq("job_id", jobId)
      .gte("found_at", cacheThreshold)
      .order("confidence_score", { ascending: false })
      .limit(20);

    if (cached && (cached as unknown[]).length > 0) {
      return json({
        contacts: cached,
        count: (cached as unknown[]).length,
        from_cache: true,
        search_links: searchLinks,
        fallback_instructions: fallbackInstructions,
      });
    }

    // ── Call Python engine for enrichment ──────────────────────────────────
    const engineUrl = (getEnv("ENGINE_URL") ?? "").replace(/\/$/, "");
    const internalKey = getEnv("INTERNAL_API_KEY") ?? "";

    if (engineUrl && internalKey) {
      try {
        const engineResp = await fetch(`${engineUrl}/internal/contacts/enrich`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-internal-key": internalKey,
          },
          body: JSON.stringify({
            job_id: jobId,
            company: companyName,
            company_id: (job as Record<string, unknown>).company_id,
            company_domain: companyDomain,
            title: jobTitle,
            description: (job as Record<string, unknown>).description,
            url: (job as Record<string, unknown>).url,
            apply_url: (job as Record<string, unknown>).apply_url,
          }),
          signal: AbortSignal.timeout(15_000),
        });

        if (engineResp.ok) {
          const enriched = (await engineResp.json()) as {
            contacts?: unknown[];
            count?: number;
            search_links?: Record<string, string>;
            fallback_instructions?: unknown[];
          };
          return json({
            contacts: enriched.contacts ?? [],
            count: enriched.count ?? (enriched.contacts ?? []).length,
            from_cache: false,
            search_links: enriched.search_links ?? searchLinks,
            fallback_instructions: enriched.fallback_instructions ?? fallbackInstructions,
          });
        }
      } catch (engineErr) {
        console.warn("Engine contact enrichment failed:", engineErr);
        // Fall through to inline fallback
      }
    }

    // ── Inline fallback: return cached (possibly stale) or fallback guide ─
    const { data: fallbackCached } = await admin
      .from("job_people")
      .select("id, name, title, email, email_status, email_confidence, linkedin_search_url, source_type, confidence_score, found_at")
      .eq("job_id", jobId)
      .order("confidence_score", { ascending: false })
      .limit(20);

    if (fallbackCached && (fallbackCached as unknown[]).length > 0) {
      return json({
        contacts: fallbackCached,
        count: (fallbackCached as unknown[]).length,
        from_cache: true,
        search_links: searchLinks,
        fallback_instructions: fallbackInstructions,
      });
    }

    // No direct contacts found: return empty contacts list with 4 actionable fallback steps
    return json({
      contacts: [],
      count: 0,
      from_cache: false,
      search_links: searchLinks,
      fallback_instructions: fallbackInstructions,
      message: "No direct contacts found for this company. Use the 4 fallback steps to connect directly with recruiters and hiring managers.",
    });
  } catch (err) {
    console.error("find-contacts error:", err);
    return serverError();
  }
  });
}

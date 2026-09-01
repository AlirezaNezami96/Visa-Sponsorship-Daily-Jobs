/**
 * Loaders for job / resume / contact context used by generation endpoints.
 * Jobs, companies, and job_people are public-read tables, so they can be read
 * with the user client (RLS allows SELECT). Resumes are owner-only.
 */
import type { SupabaseClient } from "@supabase/supabase-js";
import type { JobContext } from "./prompts.ts";

export interface JobRow extends JobContext {
  id: string;
  location_raw?: string | null;
}

/** Load a job (public-read) joined with its company + any contact people. */
export async function loadJob(client: SupabaseClient, jobId: string): Promise<JobRow | null> {
  const { data, error } = await client
    .from("jobs")
    .select("id, title, company_id, location_raw, description_text, requirements, apply_url, companies(name), job_people(name,title,email,email_status,linkedin_search_url)")
    .eq("id", jobId)
    .maybeSingle();
  if (error || !data) return null;

  const row = data as Record<string, unknown>;
  const company = (row.companies as { name?: string } | null)?.name || (row.company_name as string) || "Company";
  const reqs = Array.isArray(row.requirements) ? (row.requirements as string[]) : [];
  return {
    id: jobId,
    title: String(row.title ?? ""),
    company,
    company_id: (row.company_id as string | null) ?? null,
    location: (row.location_raw as string | null) ?? null,
    description: (row.description_text as string | null) ?? null,
    apply_url: (row.apply_url as string | null) ?? null,
    requirements: reqs,
    // contacts carried alongside for outreach generation
    contacts: (row.job_people as Array<Record<string, unknown>> | null) ?? [],
  } as JobRow & { company_id: string | null; apply_url: string | null; contacts: Array<Record<string, unknown>> };
}

export async function loadResume(client: SupabaseClient, userId: string, resumeId: string) {
  const { data, error } = await client
    .from("resumes")
    .select("*")
    .eq("id", resumeId)
    .eq("user_id", userId)
    .maybeSingle();
  if (error) return null;
  return data as Record<string, unknown> | null;
}

/** Best-effort company/intel text used to ground cover-letter hooks. */
export async function loadCompanyIntel(client: SupabaseClient, companyId: string): Promise<string | null> {
  const { data, error } = await client.from("companies").select("name, website, funding_info").eq("id", companyId).maybeSingle();
  if (error || !data) return null;
  const row = data as Record<string, unknown>;
  const funding = row.funding_info ? ` Funding: ${JSON.stringify(row.funding_info)}` : "";
  return `${row.name}${row.website ? ` (${row.website})` : ""}.${funding}`;
}

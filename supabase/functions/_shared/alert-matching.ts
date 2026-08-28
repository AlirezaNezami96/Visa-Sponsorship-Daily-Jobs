/**
 * TypeScript port of src/job_radar/visalane/alert_matching.py.
 *
 * The semantics MUST stay identical across runtimes; both sides share the
 * documented filter vocabulary (docs/api/README.md) and have matching test
 * fixtures. The Python side handles daily/weekly cron batches; this module
 * serves low-latency instant/hourly dispatch from process-new-jobs.
 */

export type JobLike = Record<string, unknown>;
export interface AlertFilters {
  keywords?: string[];
  countries?: string[];
  work_modes?: string[];
  exclude_companies?: string[];
  min_confidence?: number;
  verified_only?: boolean;
  min_match?: number;
}

function normCompany(text: string): string {
  return (text ?? "").toLowerCase().replace(/[^a-z0-9 ]/g, "").trim();
}

function jobWorkModes(job: JobLike): Set<string> {
  const modes = new Set<string>();
  const mode = (job.work_mode ?? job.workplace_type) as string | undefined;
  if (mode) modes.add(String(mode).toLowerCase());
  if (job.remote || job.is_remote) modes.add("remote");
  if (job.is_hybrid) modes.add("hybrid");
  if (modes.size === 0) modes.add("unspecified");
  return modes;
}

export function jobMatchesAlert(job: JobLike, filters: AlertFilters | null | undefined): boolean {
  if (!filters) return true;

  const haystack = `${job.title ?? ""}\n${job.description ?? job.description_text ?? job.snippet ?? ""}`.toLowerCase();
  if (filters.keywords?.length && !filters.keywords.some((kw) => haystack.includes(String(kw).toLowerCase()))) {
    return false;
  }

  if (filters.countries?.length) {
    const jobCc = String(job.country_code ?? "").toUpperCase();
    const jobCountry = String(job.country ?? "").toLowerCase();
    const jobLoc = String(job.location_raw ?? job.location ?? "").toLowerCase();
    const matched = filters.countries.some((c) => {
      const clean = String(c).trim();
      if (clean.length === 2) return clean.toUpperCase() === jobCc;
      return jobCountry.includes(clean.toLowerCase()) || jobLoc.includes(clean.toLowerCase());
    });
    if (!matched) return false;
  }

  if (filters.work_modes?.length) {
    const wanted = new Set(filters.work_modes.map((m) => String(m).toLowerCase()));
    const modes = jobWorkModes(job);
    if (![...wanted].some((m) => modes.has(m))) return false;
  }

  if (filters.exclude_companies?.length) {
    const excluded = new Set(filters.exclude_companies.map((x) => normCompany(String(x))));
    if (excluded.has(normCompany(String(job.company ?? "")))) return false;
  }

  if (filters.min_confidence != null) {
    const conf = job.visa_sponsorship_confidence;
    if (conf == null || Number(conf) < Number(filters.min_confidence)) return false;
  }

  if (filters.verified_only && !job.visa_sponsorship_verified) return false;

  if (filters.min_match != null) {
    let score = job.resume_match_score;
    if (score == null) {
      const rm = job.resume_match as Record<string, unknown> | undefined;
      score = rm && typeof rm === "object" ? (rm.ats_score as number | undefined) : undefined;
    }
    if (score == null || Number(score) < Number(filters.min_match)) return false;
  }

  return true;
}

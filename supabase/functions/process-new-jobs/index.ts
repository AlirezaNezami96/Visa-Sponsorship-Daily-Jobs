/**
 * POST /functions/v1/process-new-jobs
 * INTERNAL / CRON only (not user-facing). Protected by PROCESS_JOBS_SECRET.
 *
 * Orchestrates post-scrape staging in the DB, mirroring the Python
 * dispatch_pending stage but callable on-demand for instant/hourly alert
 * latency (master plan section 8):
 *   1. alert matching  -> alert_sent_jobs (idempotent) + mark processed_alerts
 *   2. social staging  -> social_post_queue (linkedin/x => manual_review)
 *   3. enrichment trigger (left for the Python enrichment worker)
 *
 * Delivery of matched alerts over email/telegram/discord/slack is owned by
 * the Python notification layer, which dedups against alert_sent_jobs.
 */
import { createAdminClient } from "../_shared/supabase-clients.ts";
import { handleOptions, json, unauthorized, serverError, error } from "../_shared/http.ts";
import { jobMatchesAlert, type AlertFilters, type JobLike } from "../_shared/alert-matching.ts";
import { getEnv } from "../_shared/env.ts";

const AUTO_PLATFORMS = ["telegram", "discord", "slack", "bluesky", "mastodon"];
const MANUAL_PLATFORMS = ["linkedin", "x"];
const ALL_PLATFORMS = [...AUTO_PLATFORMS, ...MANUAL_PLATFORMS];
const JOBS_PER_POST = 5;

function authorized(req: Request): boolean {
  const secret = getEnv("PROCESS_JOBS_SECRET") ?? getEnv("CRON_SECRET");
  if (!secret) return false;
  const header = req.headers.get("x-cron-secret");
  if (header && header === secret) return true;
  const auth = req.headers.get("Authorization") ?? "";
  return auth === `Bearer ${secret}`;
}

function buildCaption(jobs: JobLike[]): string {
  const lines = ["Visa-sponsoring roles worth a look today:"];
  for (const job of jobs.slice(0, JOBS_PER_POST)) {
    let line = `- ${job.title ?? "Role"} @ ${job.company ?? "Unknown"}`;
    if (job.location_raw || job.location) line += ` (${job.location_raw ?? job.location})`;
    if (job.visa_sponsorship_verified) line += " [verified sponsor]";
    const apply = String(job.apply_url ?? job.source_url ?? "");
    if (apply) line += `\n  Apply: ${apply}`;
    lines.push(line);
  }
  lines.push("\nMore verified visa-sponsoring jobs: visalane.app");
  return lines.join("\n");
}

Deno.serve(async (req) => {
  const preflight = handleOptions(req);
  if (preflight) return preflight;
  if (req.method !== "POST") return error(405, "method_not_allowed", "POST only");
  if (!authorized(req)) return unauthorized("Invalid or missing cron secret");

  try {
    const admin = createAdminClient();

    // 1. Fetch active, not-yet-alert-processed jobs with company + country.
    const { data: jobRows, error: jobsErr } = await admin
      .from("jobs")
      .select("id, title, source_url, apply_url, location_raw, country, country_code, work_mode, visa_sponsorship_confidence, visa_sponsorship_verified, raw_payload, companies(name)")
      .eq("status", "active")
      .eq("processed_alerts", false)
      .limit(500);
    if (jobsErr) return serverError(jobsErr.message);

    const jobs: JobLike[] = ((jobRows ?? []) as Array<Record<string, unknown>>).map((r) => ({
      ...r,
      company: (r.companies as { name?: string } | null)?.name ?? "",
      resume_match_score: (r.raw_payload as { resume_match_score?: number } | null)?.resume_match_score,
    }));

    // 2. Match against active alerts.
    const { data: alertRows } = await admin.from("alerts").select("*").eq("is_active", true);
    const alerts = ((alertRows ?? []) as Array<Record<string, unknown>>).filter((a) => {
      const freq = String(a.frequency ?? "");
      return freq === "instant" || freq === "hourly";
    });

    let matchedPairs = 0;
    for (const alert of alerts) {
      const filters = (alert.filters ?? {}) as AlertFilters;
      const hits = jobs.filter((j) => jobMatchesAlert(j, filters));
      if (!hits.length) continue;
      const rows = hits.map((j) => ({ alert_id: alert.id as string, job_id: j.id as string }));
      const { data: inserted } = await admin
        .from("alert_sent_jobs")
        .upsert(rows, { onConflict: "alert_id,job_id", ignoreDuplicates: true })
        .select("id");
      matchedPairs += inserted?.length ?? 0;
      await admin.from("analytics_events").insert(
        hits.map((j) => ({
          event_name: "alert_sent",
          user_id: alert.user_id as string,
          job_id: j.id as string,
          metadata: { alert_id: alert.id, delivery: "deferred_to_notification_layer" },
        })),
      ).then(() => undefined, () => undefined);
    }

    // Mark alert stage processed.
    if (jobs.length) {
      await admin.from("jobs").update({ processed_alerts: true }).in("id", jobs.map((j) => j.id as string));
    }

    // 3. Social staging for jobs not yet social-processed.
    const { data: socialRows } = await admin
      .from("jobs")
      .select("id, title, apply_url, source_url, location_raw, visa_sponsorship_verified")
      .eq("status", "active")
      .eq("processed_social", false)
      .limit(250);
    const socialJobs = (socialRows ?? []) as Array<Record<string, unknown>>;

    let queued = 0;
    if (socialJobs.length) {
      const queueRows: Array<Record<string, unknown>> = [];
      for (let i = 0; i < socialJobs.length; i += JOBS_PER_POST) {
        const batch = socialJobs.slice(i, i + JOBS_PER_POST);
        const jobIds = batch.map((j) => j.id as string);
        const caption = buildCaption(batch as JobLike[]);
        for (const platform of ALL_PLATFORMS) {
          queueRows.push({
            job_ids: jobIds,
            platform,
            status: MANUAL_PLATFORMS.includes(platform) ? "manual_review" : "pending",
            caption,
          });
        }
      }
      const { data: ins } = await admin.from("social_post_queue").insert(queueRows).select("id");
      queued = ins?.length ?? 0;
      await admin.from("jobs").update({ processed_social: true }).in("id", socialJobs.map((j) => j.id as string));
    }

    // 4. Enrichment trigger: leave processed_enrichment=false for the Python
    // enrichment worker; just surface how many await enrichment.
    const { count: pendingEnrichment } = await admin
      .from("jobs")
      .select("id", { count: "exact", head: true })
      .eq("status", "active")
      .eq("processed_enrichment", false);

    await admin.from("analytics_events").insert({
      event_name: "scrape_completed",
      metadata: { alerts_matched: matchedPairs, social_queued: queued, enrichment_pending: pendingEnrichment ?? 0 },
    }).then(() => undefined, () => undefined);

    return json({
      jobs_processed: jobs.length,
      alerts_matched: matchedPairs,
      social_queued: queued,
      enrichment_pending: pendingEnrichment ?? 0,
    });
  } catch (err) {
    console.error("process-new-jobs error:", err);
    return serverError();
  }
});

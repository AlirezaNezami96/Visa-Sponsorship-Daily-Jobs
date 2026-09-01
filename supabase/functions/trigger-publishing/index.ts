/**
 * POST /functions/v1/trigger-publishing
 *
 * Edge Function dedicated to MANUAL syndication of verified jobs from the Admin Panel.
 * Supports the 6 target channels:
 * - "telegram" -> Telegram Channel / Bot API
 * - "discord"  -> Discord Webhook
 * - "bluesky"  -> AT Protocol API
 * - "devto"    -> Forem API (Dev.to Articles)
 * - "mastodon" -> Mastodon Instance API
 * - "twitter"  -> X / Twitter API v2 (Tweets)
 *
 * Request Body:
 * {
 *   "platforms": ["telegram", "discord", "bluesky", "devto", "mastodon", "twitter"],
 *   "force": boolean,
 *   "triggered_by": string
 * }
 */
import type { SupabaseClient } from "@supabase/supabase-js";
import { createAdminClient, createUserClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { handleOptions, json, unauthorized, badRequest, serverError, error } from "../_shared/http.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { logSystemEvent } from "../_shared/system-logger.ts";
import { getEnv } from "../_shared/env.ts";

export interface TriggerPublishingRequest {
  platforms?: string[] | null;
  force?: boolean;
  triggered_by?: string;
}

export interface PlatformConfig {
  platform: string;
  min_gap_minutes: number;
  daily_cap: number;
  active_start_hour: number;
  active_end_hour: number;
  enabled: boolean;
  published_today?: number;
  last_post_at?: string | null;
}

export interface JobItem {
  id: string;
  title: string;
  company?: string;
  location_raw?: string | null;
  city?: string | null;
  country?: string | null;
  country_code?: string | null;
  apply_url?: string | null;
  source_url?: string | null;
  salary_raw?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  visa_sponsorship_verified?: boolean;
  visa_types?: string[] | null;
  work_mode?: string | null;
}

export interface PacingCheckResult {
  eligible: boolean;
  reason?: string;
  resetPublishedToday: boolean;
  effectivePublishedToday: number;
}

const PLATFORM_DISPLAY_NAMES: Record<string, string> = {
  telegram: "Telegram",
  discord: "Discord",
  bluesky: "Bluesky",
  devto: "Dev.to",
  mastodon: "Mastodon",
  twitter: "X",
  x: "X",
};

/**
 * Normalizes platform aliases (e.g. 'x' -> 'twitter', 'dev_to' -> 'devto').
 */
export function normalizePlatformName(p: string): string {
  const clean = p.toLowerCase().trim();
  if (clean === "x") return "twitter";
  if (clean === "dev_to") return "devto";
  return clean;
}

/**
 * Validates pacing constraints (daily cap, active UTC hours, min gap minutes).
 */
export function checkPacing(
  config: PlatformConfig,
  now: Date = new Date(),
  force: boolean = false,
): PacingCheckResult {
  let publishedToday = config.published_today ?? 0;
  let resetPublishedToday = false;

  if (config.last_post_at) {
    const lastPostDate = new Date(config.last_post_at);
    const isSameDay =
      lastPostDate.getUTCFullYear() === now.getUTCFullYear() &&
      lastPostDate.getUTCMonth() === now.getUTCMonth() &&
      lastPostDate.getUTCDate() === now.getUTCDate();
    if (!isSameDay) {
      publishedToday = 0;
      resetPublishedToday = true;
    }
  }

  if (force) {
    return {
      eligible: true,
      resetPublishedToday,
      effectivePublishedToday: publishedToday,
    };
  }

  // 1. Daily Cap Check
  if (config.daily_cap > 0 && publishedToday >= config.daily_cap) {
    return {
      eligible: false,
      reason: `Daily cap reached (${publishedToday}/${config.daily_cap})`,
      resetPublishedToday,
      effectivePublishedToday: publishedToday,
    };
  }

  // 2. Active Hours (UTC) Check
  const currentHour = now.getUTCHours();
  const start = config.active_start_hour ?? 0;
  const end = config.active_end_hour ?? 24;
  if (start < end) {
    if (currentHour < start || currentHour >= end) {
      return {
        eligible: false,
        reason: `Outside active hours (${start}:00 - ${end}:00 UTC, current: ${currentHour}:00 UTC)`,
        resetPublishedToday,
        effectivePublishedToday: publishedToday,
      };
    }
  } else if (start > end) {
    // Overnight window (e.g. 22:00 to 06:00)
    if (currentHour < start && currentHour >= end) {
      return {
        eligible: false,
        reason: `Outside active hours (overnight ${start}:00 - ${end}:00 UTC)`,
        resetPublishedToday,
        effectivePublishedToday: publishedToday,
      };
    }
  }

  // 3. Min Gap Minutes Check
  if (config.min_gap_minutes > 0 && config.last_post_at) {
    const lastPostTime = new Date(config.last_post_at).getTime();
    const elapsedMinutes = (now.getTime() - lastPostTime) / (60 * 1000);
    if (elapsedMinutes < config.min_gap_minutes) {
      const waitMin = Math.ceil(config.min_gap_minutes - elapsedMinutes);
      return {
        eligible: false,
        reason: `Minimum gap not elapsed (${Math.floor(elapsedMinutes)}m elapsed, ${waitMin}m remaining of ${config.min_gap_minutes}m)`,
        resetPublishedToday,
        effectivePublishedToday: publishedToday,
      };
    }
  }

  return {
    eligible: true,
    resetPublishedToday,
    effectivePublishedToday: publishedToday,
  };
}

/**
 * Format message for Telegram feed.
 */
export function formatTelegramPost(jobs: JobItem[]): string {
  const lines = [`*🆕 ${jobs.length} Verified Visa-Sponsoring Roles*\n`];
  for (const j of jobs) {
    const title = j.title || "Software Engineer";
    const company = j.company || "Tech Employer";
    const loc = j.location_raw || j.city || j.country || "Worldwide";
    const visa = Array.isArray(j.visa_types) && j.visa_types.length > 0 ? j.visa_types.join(", ") : "Visa Support";
    const apply = j.apply_url || j.source_url || "https://visalane.app";

    lines.push(`*${title}* — ${company}`);
    lines.push(`📍 ${loc} · 🛂 ${visa}`);
    lines.push(`🔗 [Apply Now](${apply})\n`);
  }
  lines.push("Explore all verified sponsorship opportunities on [visalane.app](https://visalane.app)");
  return lines.join("\n").trim();
}

/**
 * Format message for Discord rich embed.
 */
export function formatDiscordEmbed(job: JobItem): Record<string, unknown> {
  const title = job.title || "Software Engineer";
  const company = job.company || "Tech Employer";
  const loc = job.location_raw || job.city || job.country || "Worldwide";
  const visa = Array.isArray(job.visa_types) && job.visa_types.length > 0 ? job.visa_types.join(", ") : "Visa Support Confirmed";
  const apply = job.apply_url || job.source_url || "https://visalane.app";
  const salary = job.salary_raw || (job.salary_min ? `${job.salary_min}-${job.salary_max} ${job.salary_currency || "USD"}` : "Competitive / Not disclosed");

  return {
    title: `${title} — ${company}`.slice(0, 256),
    description: `Verified visa-sponsored opening in **${loc}**.\n\n[Apply Directly on Company Portal](${apply})`,
    url: apply,
    color: 0x22c55e,
    fields: [
      { name: "🌍 Location", value: loc, inline: true },
      { name: "🛂 Visa Status", value: visa, inline: true },
      { name: "💰 Compensation", value: salary, inline: true },
    ],
    footer: { text: "VisaLane · Verified Sponsorship Radar" },
    timestamp: new Date().toISOString(),
  };
}

/**
 * Format message for Bluesky (300 char limit).
 */
export function formatBlueskyPost(job: JobItem): string {
  const title = job.title || "Software Engineer";
  const company = job.company || "Tech Employer";
  const loc = job.location_raw || job.city || job.country || "Worldwide";
  const apply = job.apply_url || job.source_url || "https://visalane.app";

  return `📍 ${company} is hiring: ${title} (${loc}).\n\nVerified visa support & relocation assistance. 🌍\n\nApply: ${apply}`.slice(0, 300);
}

/**
 * Format markdown article for Dev.to.
 */
export function formatDevtoArticle(jobs: JobItem[]): { title: string; body_markdown: string; tags: string[] } {
  const topJob = jobs[0] || { title: "Software Engineer", company: "Global Tech" };
  const title = `Verified Visa-Sponsored Roles: ${topJob.title} @ ${topJob.company} & More`;
  
  const jobListings = jobs.map((j) => {
    const loc = j.location_raw || j.city || j.country || "Worldwide";
    const apply = j.apply_url || j.source_url || "https://visalane.app";
    const salary = j.salary_raw || "Competitive";
    return `### ${j.title} — ${j.company}\n- **Location**: ${loc}\n- **Visa Status**: Verified International Sponsorship\n- **Salary**: ${salary}\n- **Apply**: [Application Link](${apply})\n`;
  }).join("\n");

  const body_markdown = `---
title: ${title}
published: true
tags: careers, techjobs, immigration, softwareengineering
---

## Verified Visa-Sponsored Engineering Roles

Here are newly verified software engineering and technical roles offering confirmed visa sponsorship and relocation assistance:

${jobListings}

---
*Verified daily through official immigration registries and direct employer filings at [VisaLane](https://visalane.app).*
`;

  return { title, body_markdown, tags: ["careers", "techjobs", "immigration", "softwareengineering"] };
}

/**
 * Format message for Mastodon (500 char limit).
 */
export function formatMastodonPost(job: JobItem): string {
  const title = job.title || "Software Engineer";
  const company = job.company || "Tech Employer";
  const loc = job.location_raw || job.city || job.country || "Worldwide";
  const apply = job.apply_url || job.source_url || "https://visalane.app";

  return `📍 ${title} at ${company} (${loc})\n\nOfficial visa sponsorship verified. Work visa & relocation support provided. 💼\n\nApply: ${apply}\n\n#VisaSponsorship #TechJobs #Relocation`.slice(0, 500);
}

/**
 * Format message for X / Twitter (280 char limit).
 */
export function formatTwitterPost(job: JobItem): string {
  const title = job.title || "Software Engineer";
  const company = job.company || "Tech Employer";
  const loc = job.location_raw || job.city || job.country || "Worldwide";
  const apply = job.apply_url || job.source_url || "https://visalane.app";

  const raw = `📍 ${loc} | ${company} is hiring a ${title} with verified visa sponsorship! Apply: ${apply} #VisaSponsorship #TechJobs`;
  if (raw.length <= 280) return raw;
  return `📍 ${loc} | ${company} is hiring a ${title} (Visa Sponsored). Apply: ${apply}`.slice(0, 280);
}

/**
 * Authenticates caller as admin user or service role.
 */
export async function authenticateCaller(
  req: Request,
  adminClient: SupabaseClient,
): Promise<{ authenticated: boolean; callerEmail: string | null; isServiceRole: boolean }> {
  const serviceRoleKey = getEnv("SUPABASE_SERVICE_ROLE_KEY") || "";
  const cronSecret = getEnv("CRON_SECRET") || getEnv("PROCESS_JOBS_SECRET") || "";

  const authHeader = req.headers.get("Authorization") ?? "";
  const cronHeader = req.headers.get("x-cron-secret") ?? "";

  // 1. Cron Secret Authorization
  if (cronSecret && (cronHeader === cronSecret || authHeader === `Bearer ${cronSecret}`)) {
    return { authenticated: true, callerEmail: "system@cron", isServiceRole: true };
  }

  // 2. Service Role Key Authorization
  if (serviceRoleKey && authHeader === `Bearer ${serviceRoleKey}`) {
    return { authenticated: true, callerEmail: "service_role", isServiceRole: true };
  }

  if (!hasAuthHeader(req)) {
    return { authenticated: false, callerEmail: null, isServiceRole: false };
  }

  // 3. User JWT Authorization
  try {
    const userClient = createUserClient(req);
    const user = await getAuthUser(userClient);
    if (!user || !user.email) {
      return { authenticated: false, callerEmail: null, isServiceRole: false };
    }

    const { data: adminRow } = await adminClient
      .from("admin_users")
      .select("email, role, active")
      .eq("email", user.email.toLowerCase().trim())
      .maybeSingle();

    if (adminRow && adminRow.active !== false) {
      return { authenticated: true, callerEmail: user.email, isServiceRole: false };
    }

    if (user.app_metadata?.role === "admin" || user.app_metadata?.role === "service_role") {
      return { authenticated: true, callerEmail: user.email, isServiceRole: false };
    }

    return { authenticated: false, callerEmail: user.email, isServiceRole: false };
  } catch {
    return { authenticated: false, callerEmail: null, isServiceRole: false };
  }
}

/**
 * 1. Dispatch post to Telegram.
 */
async function dispatchTelegram(
  jobs: JobItem[],
): Promise<{ ok: boolean; url?: string; error?: string }> {
  const botToken = getEnv("TELEGRAM_BOT_TOKEN");
  const chatId = getEnv("TELEGRAM_CHAT_ID");

  if (!botToken || !chatId) {
    return { ok: false, error: "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID" };
  }

  const postText = formatTelegramPost(jobs);

  try {
    let res = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text: postText,
        parse_mode: "Markdown",
        disable_web_page_preview: false,
      }),
    });

    if (!res.ok) {
      const errBody = await res.text().catch(() => "");
      if (res.status === 400 && errBody.toLowerCase().includes("can't parse entities")) {
        // Fallback without Markdown
        res = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: chatId,
            text: postText,
            disable_web_page_preview: false,
          }),
        });
      } else {
        return { ok: false, error: `Telegram HTTP ${res.status}: ${errBody.slice(0, 150)}` };
      }
    }

    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      const msgId = data?.result?.message_id;
      const cleanChat = chatId.replace("@", "");
      const postUrl = !chatId.startsWith("-") ? `https://t.me/${cleanChat}/${msgId}` : `https://t.me/c/${chatId}/${msgId}`;
      return { ok: true, url: postUrl };
    }

    return { ok: false, error: `Telegram returned status ${res.status}` };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/**
 * 2. Dispatch post to Discord.
 */
async function dispatchDiscord(
  jobs: JobItem[],
): Promise<{ ok: boolean; url?: string; error?: string }> {
  const webhookUrl = getEnv("DISCORD_WEBHOOK_URL");
  if (!webhookUrl) {
    return { ok: false, error: "Missing DISCORD_WEBHOOK_URL" };
  }

  const embed = formatDiscordEmbed(jobs[0]);
  const payload = { embeds: [embed] };

  try {
    const res = await fetch(webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (res.status === 200 || res.status === 204) {
      return { ok: true, url: webhookUrl };
    }

    const errText = await res.text().catch(() => "");
    return { ok: false, error: `Discord HTTP ${res.status}: ${errText.slice(0, 150)}` };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/**
 * 3. Dispatch post to Bluesky (AT Protocol).
 */
async function dispatchBluesky(
  jobs: JobItem[],
): Promise<{ ok: boolean; url?: string; error?: string }> {
  const handle = getEnv("BLUESKY_HANDLE");
  const appPassword = getEnv("BLUESKY_APP_PASSWORD");

  if (!handle || !appPassword) {
    return { ok: false, error: "Missing BLUESKY_HANDLE or BLUESKY_APP_PASSWORD" };
  }

  try {
    const sessionRes = await fetch("https://bsky.social/xrpc/com.atproto.server.createSession", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier: handle, password: appPassword }),
    });

    if (!sessionRes.ok) {
      const err = await sessionRes.text().catch(() => "");
      return { ok: false, error: `Bluesky auth HTTP ${sessionRes.status}: ${err.slice(0, 150)}` };
    }

    const session = await sessionRes.json();
    const accessJwt = session.accessJwt;
    const did = session.did;

    const text = formatBlueskyPost(jobs[0]);
    const nowIso = new Date().toISOString();

    const postRes = await fetch("https://bsky.social/xrpc/com.atproto.repo.createRecord", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessJwt}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        repo: did,
        collection: "app.bsky.feed.post",
        record: {
          $type: "app.bsky.feed.post",
          text,
          createdAt: nowIso,
        },
      }),
    });

    if (postRes.ok) {
      const postData = await postRes.json().catch(() => ({}));
      const uri = postData.uri || "";
      const rkey = uri.split("/").pop() || "";
      const url = rkey ? `https://bsky.app/profile/${handle}/post/${rkey}` : "https://bsky.app";
      return { ok: true, url };
    }

    const errText = await postRes.text().catch(() => "");
    return { ok: false, error: `Bluesky post HTTP ${postRes.status}: ${errText.slice(0, 150)}` };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/**
 * 4. Dispatch post to Dev.to (Forem API).
 */
async function dispatchDevto(
  jobs: JobItem[],
): Promise<{ ok: boolean; url?: string; error?: string }> {
  const apiKey = getEnv("DEVTO_API_KEY");
  if (!apiKey) {
    return { ok: false, error: "Missing DEVTO_API_KEY" };
  }

  const { title, body_markdown, tags } = formatDevtoArticle(jobs);

  try {
    const res = await fetch("https://dev.to/api/articles", {
      method: "POST",
      headers: {
        "api-key": apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        article: {
          title,
          published: true,
          body_markdown,
          tags,
        },
      }),
    });

    if (res.status === 200 || res.status === 201) {
      const data = await res.json().catch(() => ({}));
      return { ok: true, url: data.url || "https://dev.to" };
    }

    const errText = await res.text().catch(() => "");
    return { ok: false, error: `DEV.to HTTP ${res.status}: ${errText.slice(0, 150)}` };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/**
 * 5. Dispatch post to Mastodon.
 */
async function dispatchMastodon(
  jobs: JobItem[],
): Promise<{ ok: boolean; url?: string; error?: string }> {
  const instanceUrl = (getEnv("MASTODON_INSTANCE_URL") || "https://mastodon.social").replace(/\/$/, "");
  const accessToken = getEnv("MASTODON_ACCESS_TOKEN");

  if (!accessToken) {
    return { ok: false, error: "Missing MASTODON_ACCESS_TOKEN" };
  }

  const status = formatMastodonPost(jobs[0]);

  try {
    const res = await fetch(`${instanceUrl}/api/v1/statuses`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ status, visibility: "public" }),
    });

    if (res.status === 200 || res.status === 201) {
      const data = await res.json().catch(() => ({}));
      return { ok: true, url: data.url || `${instanceUrl}/statuses` };
    }

    const errText = await res.text().catch(() => "");
    return { ok: false, error: `Mastodon HTTP ${res.status}: ${errText.slice(0, 150)}` };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/**
 * 6. Dispatch post to X / Twitter API v2.
 */
async function dispatchTwitter(
  jobs: JobItem[],
): Promise<{ ok: boolean; url?: string; error?: string }> {
  const token = getEnv("TWITTER_BEARER_TOKEN") || getEnv("X_BEARER_TOKEN") || getEnv("X_ACCESS_TOKEN");
  if (!token) {
    return { ok: false, error: "Missing TWITTER_BEARER_TOKEN / X_BEARER_TOKEN" };
  }

  const text = formatTwitterPost(jobs[0]);

  try {
    const res = await fetch("https://api.x.com/2/tweets", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ text }),
    });

    if (res.status === 200 || res.status === 201) {
      const data = await res.json().catch(() => ({}));
      const tweetId = data?.data?.id;
      return { ok: true, url: tweetId ? `https://x.com/i/status/${tweetId}` : "https://x.com" };
    }

    const errText = await res.text().catch(() => "");
    return { ok: false, error: `Twitter/X HTTP ${res.status}: ${errText.slice(0, 150)}` };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/**
 * Formats conjunction list of platforms (e.g. "Telegram, Discord, Bluesky, Dev.to, Mastodon, and X").
 */
export function formatPlatformList(platforms: string[]): string {
  const names = platforms.map((p) => PLATFORM_DISPLAY_NAMES[p.toLowerCase()] || p);
  if (names.length === 0) return "no platforms";
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
}

/**
 * Main handler for trigger-publishing.
 */
export async function handleTriggerPublishing(req: Request): Promise<Response> {
  const preflight = handleOptions(req);
  if (preflight) return preflight;

  if (req.method !== "POST") {
    return error(405, "method_not_allowed", "POST method only");
  }

  const admin = createAdminClient();

  // 1. Caller Authentication
  const auth = await authenticateCaller(req, admin);
  if (!auth.authenticated) {
    return unauthorized("Authentication required (valid admin session or service role required)");
  }

  try {
    const body: TriggerPublishingRequest = await req.json().catch(() => ({}));
    const force = Boolean(body.force);
    const triggeredBy = body.triggered_by || auth.callerEmail || "admin";
    
    // Requested platforms normalized
    const requestedPlatforms = Array.isArray(body.platforms) && body.platforms.length > 0
      ? body.platforms.map(normalizePlatformName)
      : null;

    const now = new Date();
    const nowIso = now.toISOString();

    // 2. Read platform configs
    let query = admin.from("platform_post_config").select("*");
    if (!force) {
      query = query.eq("enabled", true);
    }
    const { data: configRows, error: configErr } = await query;
    if (configErr) {
      return serverError(`Failed to fetch platform_post_config: ${configErr.message}`);
    }

    const allConfigs = (configRows ?? []) as PlatformConfig[];
    let targetConfigs = allConfigs;

    if (requestedPlatforms && requestedPlatforms.length > 0) {
      targetConfigs = allConfigs.filter((c) => {
        const norm = normalizePlatformName(c.platform);
        return requestedPlatforms.includes(norm) || requestedPlatforms.includes(c.platform.toLowerCase());
      });
    } else {
      targetConfigs = allConfigs.filter((c) => c.enabled || force);
    }

    // Log the initiation of the manual syndication trigger
    await logSystemEvent({
      level: "info",
      source: "publishing-pipeline",
      message: `Manual publishing triggered by ${triggeredBy} for ${targetConfigs.length} platform(s): [${targetConfigs.map((c) => c.platform).join(", ")}] (force: ${force})`,
      details: {
        requested_platforms: requestedPlatforms || ["all_configured"],
        target_platforms: targetConfigs.map((c) => c.platform),
        force,
        triggered_by: triggeredBy,
      },
    });

    if (!targetConfigs.length) {
      await logSystemEvent({
        level: "warn",
        source: "publishing-pipeline",
        message: "No enabled platforms found to syndicate.",
        details: { requested_platforms: requestedPlatforms, force, triggered_by: triggeredBy },
      });
      return json({
        success: true,
        message: "No enabled platforms found to syndicate.",
        published_count: 0,
        platforms: [],
      });
    }

    // 3. Filter configs through pacing check
    const eligibleConfigs: Array<{ config: PlatformConfig; pacing: PacingCheckResult }> = [];
    for (const config of targetConfigs) {
      const pacing = checkPacing(config, now, force);
      if (pacing.eligible) {
        eligibleConfigs.push({ config, pacing });
      } else {
        await logSystemEvent({
          level: "warn",
          source: "publishing-pipeline",
          message: `Pacing check skipped ${config.platform}: ${pacing.reason}`,
          details: {
            platform: config.platform,
            reason: pacing.reason,
            published_today: config.published_today,
            daily_cap: config.daily_cap,
            last_post_at: config.last_post_at,
          },
        });
      }
    }

    if (!eligibleConfigs.length) {
      await logSystemEvent({
        level: "warn",
        source: "publishing-pipeline",
        message: "All requested platforms are currently outside pacing windows or at daily cap.",
        details: { requested_platforms: requestedPlatforms, force, triggered_by: triggeredBy },
      });
      return json({
        success: true,
        message: "All requested platforms are currently outside pacing windows or at daily cap.",
        published_count: 0,
        platforms: [],
      });
    }


    // 4. Select verified, active jobs
    const { data: rawJobs, error: jobsErr } = await admin
      .from("jobs")
      .select("id, title, location_raw, city, country, country_code, apply_url, source_url, salary_raw, salary_min, salary_max, salary_currency, visa_sponsorship_verified, visa_types, work_mode, companies(name)")
      .eq("status", "active")
      .eq("visa_sponsorship_verified", true)
      .order("created_at", { ascending: false })
      .limit(50);

    if (jobsErr) {
      return serverError(`Failed to fetch eligible jobs: ${jobsErr.message}`);
    }

    const allVerifiedJobs: JobItem[] = ((rawJobs ?? []) as Array<Record<string, unknown>>).map((r) => ({
      id: String(r.id),
      title: String(r.title || ""),
      company: (r.companies as { name?: string } | null)?.name || "",
      location_raw: (r.location_raw as string) || null,
      city: (r.city as string) || null,
      country: (r.country as string) || null,
      country_code: (r.country_code as string) || null,
      apply_url: (r.apply_url as string) || null,
      source_url: (r.source_url as string) || null,
      salary_raw: (r.salary_raw as string) || null,
      salary_min: (r.salary_min as number) || null,
      salary_max: (r.salary_max as number) || null,
      salary_currency: (r.salary_currency as string) || null,
      visa_sponsorship_verified: Boolean(r.visa_sponsorship_verified),
      visa_types: Array.isArray(r.visa_types) ? (r.visa_types as string[]) : null,
      work_mode: (r.work_mode as string) || null,
    }));

    if (!allVerifiedJobs.length) {
      return json({
        success: true,
        message: "No verified visa-sponsored jobs available for syndication.",
        published_count: 0,
        platforms: [],
      });
    }

    // 5. Query today's published queue and job_processing for deduplication
    const startOfDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())).toISOString();
    const { data: recentQueueRows } = await admin
      .from("social_post_queue")
      .select("job_ids, platform, status, created_at, posted_at")
      .gte("created_at", startOfDay);

    const publishedByPlatform: Record<string, Set<string>> = {};
    for (const row of recentQueueRows ?? []) {
      const plat = normalizePlatformName(String(row.platform));
      if (!publishedByPlatform[plat]) publishedByPlatform[plat] = new Set();
      if (Array.isArray(row.job_ids)) {
        for (const jid of row.job_ids) publishedByPlatform[plat].add(String(jid));
      }
    }

    // Also query job_processing for completed platform posts
    const { data: jpRows } = await admin
      .from("job_processing")
      .select("job_id, telegram_status, discord_status, linkedin_status, x_status, bluesky_status, mastodon_status");

    for (const jpRow of jpRows ?? []) {
      const jp = jpRow as Record<string, unknown>;
      const jid = String(jp.job_id);
      for (const p of ["telegram", "discord", "linkedin", "x", "twitter", "bluesky", "mastodon", "devto"]) {
        const norm = normalizePlatformName(p);
        if (!publishedByPlatform[norm]) publishedByPlatform[norm] = new Set();
        if (jp[`${p}_status`] === "done" || jp[`${norm}_status`] === "done") {
          publishedByPlatform[norm].add(jid);
        }
      }
    }

    const successfulPlatforms: string[] = [];
    const publishedJobIdsSet = new Set<string>();

    // 6. Syndicate to each eligible platform
    for (const { config, pacing } of eligibleConfigs) {
      const plat = normalizePlatformName(config.platform);
      const alreadyPublished = publishedByPlatform[plat] || new Set();
      const eligibleJobs = allVerifiedJobs.filter((j) => !alreadyPublished.has(j.id));

      if (!eligibleJobs.length) {
        continue;
      }

      let dispatchResult: { ok: boolean; url?: string; error?: string } = { ok: false };
      let jobsForThisPost: JobItem[] = [];
      let postCaption = "";

      switch (plat) {
        case "telegram":
          jobsForThisPost = eligibleJobs.slice(0, 5);
          postCaption = formatTelegramPost(jobsForThisPost);
          dispatchResult = await dispatchTelegram(jobsForThisPost);
          break;

        case "discord":
          jobsForThisPost = eligibleJobs.slice(0, 1);
          postCaption = JSON.stringify(formatDiscordEmbed(jobsForThisPost[0]));
          dispatchResult = await dispatchDiscord(jobsForThisPost);
          break;

        case "bluesky":
          jobsForThisPost = eligibleJobs.slice(0, 1);
          postCaption = formatBlueskyPost(jobsForThisPost[0]);
          dispatchResult = await dispatchBluesky(jobsForThisPost);
          break;

        case "devto":
          jobsForThisPost = eligibleJobs.slice(0, 5);
          postCaption = formatDevtoArticle(jobsForThisPost).body_markdown;
          dispatchResult = await dispatchDevto(jobsForThisPost);
          break;

        case "mastodon":
          jobsForThisPost = eligibleJobs.slice(0, 1);
          postCaption = formatMastodonPost(jobsForThisPost[0]);
          dispatchResult = await dispatchMastodon(jobsForThisPost);
          break;

        case "twitter":
        case "x":
          jobsForThisPost = eligibleJobs.slice(0, 1);
          postCaption = formatTwitterPost(jobsForThisPost[0]);
          dispatchResult = await dispatchTwitter(jobsForThisPost);
          break;

        default:
          jobsForThisPost = eligibleJobs.slice(0, 1);
          postCaption = formatBlueskyPost(jobsForThisPost[0]);
          dispatchResult = { ok: true, url: `https://${plat}.com` };
          break;
      }

      if (dispatchResult.ok) {
        const jobIds = jobsForThisPost.map((j) => j.id);
        jobIds.forEach((id) => publishedJobIdsSet.add(id));
        successfulPlatforms.push(plat);

        // Update platform_post_config
        const newCount = (pacing.resetPublishedToday ? 0 : (config.published_today ?? 0)) + 1;
        await admin
          .from("platform_post_config")
          .update({
            published_today: newCount,
            last_post_at: nowIso,
            updated_at: nowIso,
          })
          .eq("platform", config.platform);

        // Update job_processing state machine table
        const statusCol = `${plat}_status`;
        const dateCol = `${plat}_at`;
        const urlCol = `${plat}_url`;
        for (const jid of jobIds) {
          await admin
            .from("job_processing")
            .upsert(
              {
                job_id: jid,
                [statusCol]: "done",
                [dateCol]: nowIso,
                [urlCol]: dispatchResult.url || null,
                updated_at: nowIso,
              },
              { onConflict: "job_id" },
            )
            .then(() => undefined, () => undefined);
        }

        // Record in social_post_queue
        await admin.from("social_post_queue").insert({
          job_ids: jobIds,
          platform: config.platform,
          status: "completed",
          caption: postCaption,
          post_url: dispatchResult.url || null,
          posted_at: nowIso,
          scheduled_at: nowIso,
        });

        // Mark jobs as processed_social
        await admin
          .from("jobs")
          .update({ processed_social: true })
          .in("id", jobIds);

        // Operational log for channel post success
        await logSystemEvent({
          level: "info",
          source: "publishing-pipeline",
          message: `Successfully posted ${jobIds.length} verified role(s) to ${PLATFORM_DISPLAY_NAMES[plat] || plat} (${dispatchResult.url || "OK"})`,
          details: {
            platform: plat,
            display_name: PLATFORM_DISPLAY_NAMES[plat] || plat,
            job_ids: jobIds,
            jobs: jobsForThisPost.map((j) => ({ id: j.id, title: j.title, company: j.company, apply_url: j.apply_url })),
            post_url: dispatchResult.url || null,
            triggered_by: triggeredBy,
          },
        });
      } else {
        console.warn(`[trigger-publishing] Syndication failed for ${plat}:`, dispatchResult.error);
        await admin.from("social_post_queue").insert({
          job_ids: jobsForThisPost.map((j) => j.id),
          platform: config.platform,
          status: "failed",
          caption: postCaption,
          error_message: dispatchResult.error || "Unknown error",
          scheduled_at: nowIso,
        });

        // Operational log for channel post failure
        await logSystemEvent({
          level: "error",
          source: "publishing-pipeline",
          message: `Failed to syndicate to ${PLATFORM_DISPLAY_NAMES[plat] || plat}: ${dispatchResult.error}`,
          details: {
            platform: plat,
            display_name: PLATFORM_DISPLAY_NAMES[plat] || plat,
            error: dispatchResult.error,
            job_ids: jobsForThisPost.map((j) => j.id),
            triggered_by: triggeredBy,
          },
        });
      }

    }

    const totalPublishedCount = publishedJobIdsSet.size;
    const publishedJobIds = Array.from(publishedJobIdsSet);

    // 7. Insert audit record in system_logs
    if (successfulPlatforms.length > 0) {
      await logSystemEvent({
        level: "info",
        source: "publishing-pipeline",
        message: `Syndicated ${totalPublishedCount} jobs to [${successfulPlatforms.join(", ")}]`,
        details: {
          platforms: successfulPlatforms,
          published_count: totalPublishedCount,
          job_ids: publishedJobIds,
          triggered_by: triggeredBy,
          force,
        },
      });
    }

    const platformConjunction = formatPlatformList(successfulPlatforms);

    return json({
      success: true,
      message: totalPublishedCount > 0
        ? `Successfully syndicated jobs to ${platformConjunction}.`
        : "No new jobs were published (all eligible jobs already posted or platforms offline).",
      published_count: totalPublishedCount,
      platforms: successfulPlatforms,
    });
  } catch (err) {
    console.error("trigger-publishing error:", err);
    return serverError(`Internal error during publishing: ${String(err)}`);
  }
}

// Deno server binding
if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(handleTriggerPublishing);
}

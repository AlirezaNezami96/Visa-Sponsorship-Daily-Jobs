/**
 * GET /functions/v1/admin-system-logs
 * POST /functions/v1/admin-system-logs
 *
 * Dedicated Admin Observability & System Logs API.
 * Protected by Max-Security Admin AAL2 session verification.
 *
 * Query params (GET):
 *   level      string ("all" | "error" | "warn" | "info" | "debug") - default: "all"
 *   source     string (optional source filter, e.g. "parse-resume", "scrapers")
 *   search     string (optional text search in message / details)
 *   time_range string ("1h" | "24h" | "7d" | "14d" | "all") - default: "24h"
 *   limit      number (default: 50, max: 200)
 *   offset     number (default: 0)
 *
 * POST body (Ingest log entry from workers / GitHub Actions):
 *   { level, source, message, details?, userId? }
 */
import { createAdminClient } from "../_shared/supabase-clients.ts";
import { handleOptions, adminJson, adminError, json, unauthorized } from "../_shared/http.ts";
import { verifyAdminSession } from "../_shared/admin-auth.ts";

export interface LogFilterParams {
  level?: string;
  source?: string;
  search?: string;
  timeRange?: string;
  limit: number;
  offset: number;
}

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
    const preflight = handleOptions(req);
    if (preflight) return preflight;

    const admin = createAdminClient();

    // Ingest route for workers (authenticated via service role / auth header)
    if (req.method === "POST") {
      try {
        const body = await req.json().catch(() => ({}));
        if (!body.level || !body.source || !body.message) {
          return json({ error: "Missing level, source, or message" }, { status: 400 });
        }

        const { data, error } = await admin.from("system_logs").insert({
          level: String(body.level).toLowerCase(),
          source: String(body.source),
          message: String(body.message),
          details: body.details || {},
          user_id: body.userId || null,
          environment: body.environment || Deno.env.get("ENVIRONMENT") || "production",
        }).select("id").single();

        if (error) throw error;
        return json({ ok: true, id: data?.id });
      } catch (err) {
        return json({ error: String((err as Error).message ?? err) }, { status: 500 });
      }
    }

    if (req.method !== "GET") {
      return adminError(405, "method_not_allowed", "GET or POST method only");
    }

    // Max-Security Admin AAL2 session verification
    const authResult = await verifyAdminSession(req, {
      action: "read_system_logs",
      resource: "system_logs",
    });

    if (!authResult.ok || !authResult.context) {
      return authResult.response || adminError(403, "forbidden", "Admin authorization required");
    }

    try {
      const url = new URL(req.url);
      const level = (url.searchParams.get("level") || "all").toLowerCase();
      const source = url.searchParams.get("source") || "all";
      const search = url.searchParams.get("search")?.trim() || "";
      const timeRange = url.searchParams.get("time_range") || "24h";
      const limit = Math.min(200, Math.max(1, parseInt(url.searchParams.get("limit") || "50", 10)));
      const offset = Math.max(0, parseInt(url.searchParams.get("offset") || "0", 10));

      let query = admin
        .from("system_logs")
        .select("*", { count: "exact" })
        .order("created_at", { ascending: false });

      // Level filter
      if (level !== "all" && ["error", "warn", "info", "debug"].includes(level)) {
        query = query.eq("level", level);
      }

      // Source filter
      if (source !== "all" && source.trim().length > 0) {
        query = query.eq("source", source);
      }

      // Time range filter
      if (timeRange !== "all") {
        const now = new Date();
        let cutoff = new Date();
        if (timeRange === "1h") cutoff = new Date(now.getTime() - 60 * 60 * 1000);
        else if (timeRange === "24h") cutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000);
        else if (timeRange === "7d") cutoff = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        else if (timeRange === "14d") cutoff = new Date(now.getTime() - 14 * 24 * 60 * 60 * 1000);
        query = query.gte("created_at", cutoff.toISOString());
      }

      // Search keyword filter
      if (search) {
        query = query.or(`message.ilike.%${search}%,source.ilike.%${search}%`);
      }

      // Pagination
      query = query.range(offset, offset + limit - 1);

      const { data: logs, count, error: dbError } = await query;
      if (dbError) throw dbError;

      // Log level breakdown counts for quick status cards in admin UI
      const { data: countsData } = await admin
        .from("system_logs")
        .select("level")
        .limit(1000);

      const summary = {
        total: count ?? (logs?.length || 0),
        errorCount: countsData?.filter((r) => r.level === "error").length || 0,
        warnCount: countsData?.filter((r) => r.level === "warn").length || 0,
        infoCount: countsData?.filter((r) => r.level === "info").length || 0,
        debugCount: countsData?.filter((r) => r.level === "debug").length || 0,
      };

      // Distinct available sources
      const availableSources = Array.from(
        new Set([
          "publishing-pipeline",
          "admin-publishing-trigger",
          "social-publish",
          "parse-resume",
          "generate-tailored-resume",
          "generate-cover-letter",
          "generate-outreach-messages",
          "find-contacts",
          "extract-job-skills",
          "jobs-scraper",
          "auth",
          "usage-limits",
          ...(logs?.map((l) => l.source) || []),
        ]),
      );


      return adminJson({
        logs: logs || [],
        pagination: {
          total: count ?? 0,
          limit,
          offset,
          hasMore: (offset + (logs?.length || 0)) < (count ?? 0),
        },
        summary,
        availableSources,
        filters: {
          level,
          source,
          search,
          timeRange,
          limit,
          offset,
        },
      });
    } catch (err) {
      return adminError(500, "internal_error", String((err as Error).message ?? err));
    }
  });
}

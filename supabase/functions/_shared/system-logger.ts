/**
 * Centralized system logger for Supabase Edge Functions and VisaLane backend.
 *
 * Captures operational errors, warnings, AI waterfall fallbacks, scraper telemetry,
 * and security alerts into public.system_logs for the Admin Panel Log Viewer.
 *
 * Designed to be non-blocking and safe: logging failures are caught and never
 * interfere with the primary request response.
 */
import { createAdminClient } from "./supabase-clients.ts";

export type LogLevel = "error" | "warn" | "info" | "debug";

export interface SystemLogEntry {
  level: LogLevel;
  source: string;
  message: string;
  details?: Record<string, unknown>;
  userId?: string | null;
  environment?: string;
}

export async function logSystemEvent(entry: SystemLogEntry): Promise<void> {
  // Always output structured JSON to Deno stdout for native Supabase log stream
  const payload = {
    timestamp: new Date().toISOString(),
    level: entry.level,
    source: entry.source,
    message: entry.message,
    details: entry.details || {},
    userId: entry.userId || null,
    environment: entry.environment || Deno.env.get("ENVIRONMENT") || "production",
  };

  if (entry.level === "error") {
    console.error(`[SYSTEM_LOG][${entry.level.toUpperCase()}][${entry.source}] ${entry.message}`, JSON.stringify(payload));
  } else if (entry.level === "warn") {
    console.warn(`[SYSTEM_LOG][${entry.level.toUpperCase()}][${entry.source}] ${entry.message}`, JSON.stringify(payload));
  } else {
    console.log(`[SYSTEM_LOG][${entry.level.toUpperCase()}][${entry.source}] ${entry.message}`, JSON.stringify(payload));
  }

  // Non-blocking asynchronous write to system_logs table for admin panel visibility
  try {
    const admin = createAdminClient();
    await admin.from("system_logs").insert({
      level: entry.level,
      source: entry.source,
      message: entry.message,
      details: entry.details || {},
      user_id: entry.userId || null,
      environment: payload.environment,
    });
  } catch (err) {
    // Non-fatal fallback so logging never breaks business logic
    console.error("[SYSTEM_LOG_INSERT_ERROR]", err);
  }
}

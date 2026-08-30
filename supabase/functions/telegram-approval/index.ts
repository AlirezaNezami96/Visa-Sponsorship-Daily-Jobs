/**
 * Telegram Webhook Handler for Manual Review Approvals.
 *
 * Receives inline keyboard callback queries (approve_linkedin_<uuid>, reject_x_<uuid>),
 * validates admin sender, updates job_processing and jobs tables, and responds to Telegram.
 */
import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.0";
import { jsonResponse, errorResponse } from "../_shared/http.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") || "";
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || Deno.env.get("SUPABASE_KEY") || "";
const TELEGRAM_BOT_TOKEN = Deno.env.get("TELEGRAM_BOT_TOKEN") || "";
const TELEGRAM_ADMIN_CHAT_ID = Deno.env.get("TELEGRAM_ADMIN_CHAT_ID") || Deno.env.get("TELEGRAM_CHAT_ID") || "";

serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: { "Access-Control-Allow-Origin": "*" } });
  }

  if (req.method !== "POST") {
    return errorResponse("METHOD_NOT_ALLOWED", "Method not allowed", 405);
  }

  try {
    const update = await req.json();
    const callbackQuery = update?.callback_query;

    if (!callbackQuery) {
      return jsonResponse({ ok: true, status: "ignored_no_callback" });
    }

    const callbackId = callbackQuery.id;
    const data = callbackQuery.data || "";
    const fromId = String(callbackQuery.from?.id || "");
    const messageId = callbackQuery.message?.message_id;
    const chatId = callbackQuery.message?.chat?.id;

    // Optional admin chat validation if configured
    if (TELEGRAM_ADMIN_CHAT_ID && fromId !== TELEGRAM_ADMIN_CHAT_ID && String(chatId) !== TELEGRAM_ADMIN_CHAT_ID) {
      if (TELEGRAM_BOT_TOKEN && callbackId) {
        await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ callback_query_id: callbackId, text: "Unauthorized admin", show_alert: true }),
        });
      }
      return errorResponse("UNAUTHORIZED", "Unauthorized user", 403);
    }

    const parts = data.split("_");
    if (parts.length < 3) {
      return jsonResponse({ ok: false, error: "invalid_format" });
    }

    const action = parts[0];
    const platform = parts[1];
    const jobId = parts.slice(2).join("_");

    const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

    if (action === "approve") {
      const statusCol = `${platform}_status`;
      const mirrorCol = `${platform}_post_published`;

      // 1. Update job_processing
      await supabase
        .from("job_processing")
        .update({ [statusCol]: "done" })
        .eq("job_id", jobId);

      // 2. Mirror to jobs table
      await supabase
        .from("jobs")
        .update({ [mirrorCol]: true })
        .eq("id", jobId);

      // 3. Answer Telegram callback
      if (TELEGRAM_BOT_TOKEN && callbackId) {
        await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ callback_query_id: callbackId, text: `✅ Approved for ${platform.toUpperCase()}` }),
        });
      }

      return jsonResponse({ ok: true, action: "approved", platform, job_id: jobId });
    } else if (action === "reject") {
      const statusCol = `${platform}_status`;
      const errorCol = `${platform}_last_error`;

      await supabase
        .from("job_processing")
        .update({ [statusCol]: "failed", [errorCol]: "manually rejected by admin" })
        .eq("job_id", jobId);

      if (TELEGRAM_BOT_TOKEN && callbackId) {
        await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ callback_query_id: callbackId, text: `❌ Rejected for ${platform.toUpperCase()}` }),
        });
      }

      return jsonResponse({ ok: true, action: "rejected", platform, job_id: jobId });
    }

    return jsonResponse({ ok: false, error: "unknown_action" });
  } catch (err: any) {
    return errorResponse("INTERNAL_ERROR", err.message || "Internal error", 500);
  }
});

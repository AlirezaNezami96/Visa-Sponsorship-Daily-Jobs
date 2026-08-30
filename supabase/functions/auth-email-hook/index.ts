import { badRequest, error, handleOptions, json, serverError, unauthorized } from "../_shared/http.ts";
import { getEnv } from "../_shared/env.ts";
import { renderOtpEmailHtml, sendEmailViaResendApi } from "../_shared/auth-otp.ts";

/**
 * Supabase Auth Custom Email Hook.
 * Called automatically by Supabase Auth (GoTrue) when sending auth emails.
 *
 * Payload received from Supabase:
 * {
 *   user: { id, email, user_metadata },
 *   email_data: {
 *     token: string,
 *     token_hash: string,
 *     redirect_to: string,
 *     email_action_type: "signup" | "magiclink" | "recovery" | "invite" | "reauthentication"
 *   }
 * }
 */
export async function handleEmailHookRequest(req: Request): Promise<Response> {
  const opt = handleOptions(req);
  if (opt) return opt;

  if (req.method !== "POST") {
    return error(405, "method_not_allowed", "Only POST requests are accepted.");
  }

  // Verify auth hook shared secret if configured
  const authHookSecret = getEnv("AUTH_HOOK_SECRET");
  if (authHookSecret) {
    const signature = req.headers.get("x-supabase-auth-signature") || req.headers.get("authorization");
    if (!signature || !signature.includes(authHookSecret)) {
      return unauthorized("Invalid or missing auth hook secret.");
    }
  }

  let body: {
    user?: { id?: string; email?: string; user_metadata?: Record<string, unknown> };
    email_data?: {
      token?: string;
      token_hash?: string;
      redirect_to?: string;
      email_action_type?: string;
    };
  } = {};

  try {
    body = await req.json();
  } catch {
    return badRequest("Invalid JSON payload.");
  }

  const userEmail = body.user?.email;
  const token = body.email_data?.token;

  if (!userEmail) {
    return badRequest("Recipient user email is missing from hook payload.");
  }

  if (!token) {
    return badRequest("OTP token is missing from hook payload.");
  }

  const resendApiKey = getEnv("RESEND_API_KEY");
  if (resendApiKey) {
    const dispatch = await sendEmailViaResendApi({
      apiKey: resendApiKey,
      to: userEmail,
      token,
      subject: `Your VisaLane Verification Code: ${token}`,
    });

    if (!dispatch.ok) {
      return serverError(`Failed to send email via Resend: ${dispatch.error}`);
    }

    return json({ ok: true, email_id: dispatch.id });
  }

  // If no external SMTP/Resend API key is configured, return the rendered HTML for Supabase internal SMTP delivery
  const renderedHtml = renderOtpEmailHtml(token);
  return json({
    ok: true,
    html: renderedHtml,
    subject: `Your VisaLane Verification Code: ${token}`,
  });
}

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(handleEmailHookRequest);
}

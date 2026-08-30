import { badRequest, error, handleOptions, json, serverError } from "../_shared/http.ts";
import { createAdminClient } from "../_shared/supabase-clients.ts";
import { getEnv } from "../_shared/env.ts";
import {
  globalOtpRateLimiter,
  hashOtp,
  isValidEmail,
  normalizeEmail,
  sendEmailViaResendApi,
} from "../_shared/auth-otp.ts";

export async function handleSendOtpRequest(req: Request): Promise<Response> {
  const opt = handleOptions(req);
  if (opt) return opt;

  if (req.method !== "POST") {
    return error(405, "method_not_allowed", "Only POST requests are accepted.");
  }

  let body: { email?: string; redirect_to?: string } = {};
  try {
    body = await req.json();
  } catch {
    return badRequest("Invalid JSON payload.");
  }

  const rawEmail = body.email;
  if (!rawEmail || typeof rawEmail !== "string") {
    return badRequest("Email address is required.", "Please provide a valid email address.");
  }

  const email = normalizeEmail(rawEmail);
  if (!isValidEmail(email)) {
    return badRequest("Invalid email address format.", "Please enter a valid email (e.g. user@example.com).");
  }

  // Rate Limiting Check (by normalized email and client IP)
  const rateLimitKey = `email:${email}`;

  const rateCheck = globalOtpRateLimiter.checkRequestLimit(rateLimitKey);
  if (!rateCheck.allowed) {
    if (rateCheck.reason === "cooldown") {
      return error(
        429,
        "rate_limited_cooldown",
        `Please wait ${rateCheck.retryAfterSeconds} seconds before requesting a new code.`,
        `You can request another verification code in ${rateCheck.retryAfterSeconds}s.`,
      );
    }
    if (rateCheck.reason === "locked") {
      return error(
        429,
        "too_many_failed_attempts",
        "Too many failed verification attempts. Please try again later.",
        "Your account is temporarily locked for security. Please try again in 10 minutes.",
      );
    }
    return error(
      429,
      "rate_limit_exceeded",
      "Too many code requests. Please wait a few minutes before trying again.",
      "Maximum hourly verification attempts reached. Please wait a few minutes.",
    );
  }

  try {
    const supabase = createAdminClient();
    const redirectTo = body.redirect_to || "https://visalane.online";

    // Trigger Supabase Auth OTP sending
    const { error: otpError } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: redirectTo,
        shouldCreateUser: true,
      },
    });

    if (otpError) {
      // Check if Resend API key is available as direct fallback
      const resendApiKey = getEnv("RESEND_API_KEY");
      if (resendApiKey) {
        const fallbackCode = Math.floor(100000 + Math.random() * 900000).toString();
        const sendResult = await sendEmailViaResendApi({
          apiKey: resendApiKey,
          to: email,
          token: fallbackCode,
        });
        if (sendResult.ok) {
          const tokenHash = await hashOtp(fallbackCode);
          globalOtpRateLimiter.recordRequest(rateLimitKey, tokenHash);
          return json({
            ok: true,
            email,
            expires_in: 600,
            cooldown: 60,
            message: "Verification code sent to your email.",
          });
        }
      }

      return error(400, "auth_send_failed", otpError.message);
    }

    // Record successful dispatch in rate limiter
    const placeholderHash = await hashOtp(`${Date.now()}-${email}`);
    globalOtpRateLimiter.recordRequest(rateLimitKey, placeholderHash);

    return json({
      ok: true,
      email,
      expires_in: 600,
      cooldown: 60,
      message: "Verification code sent to your email.",
    });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Failed to dispatch verification email";
    return serverError(msg);
  }
}

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(handleSendOtpRequest);
}

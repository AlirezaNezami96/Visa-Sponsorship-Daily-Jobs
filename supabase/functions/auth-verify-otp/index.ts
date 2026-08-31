import { badRequest, error, handleOptions, json, serverError, unauthorized } from "../_shared/http.ts";
import { createAdminClient } from "../_shared/supabase-clients.ts";
import {
  globalOtpRateLimiter,
  isValidEmail,
  isValidOtp,
  normalizeEmail,
} from "../_shared/auth-otp.ts";

export async function handleVerifyOtpRequest(req: Request): Promise<Response> {
  const opt = handleOptions(req);
  if (opt) return opt;

  if (req.method !== "POST") {
    return error(405, "method_not_allowed", "Only POST requests are accepted.");
  }

  let body: { email?: string; token?: string } = {};
  try {
    body = await req.json();
  } catch {
    return badRequest("Invalid JSON payload.");
  }

  const rawEmail = body.email;
  const rawToken = body.token;

  if (!rawEmail || typeof rawEmail !== "string") {
    return badRequest("Email address is required.");
  }

  const email = normalizeEmail(rawEmail);
  if (!isValidEmail(email)) {
    return badRequest("Invalid email address format.");
  }

  if (!rawToken || typeof rawToken !== "string") {
    return badRequest("Verification token is required.", "Please enter the confirmation code.");
  }

  const token = rawToken.trim().replace(/\s+/g, "");
  if (!isValidOtp(token)) {
    return badRequest(
      "Invalid confirmation code format. The code must be 6 to 8 digits.",
      "Please enter the verification code sent to your email.",
    );
  }

  // Brute-force protection: check if account is locked
  const rateLimitKey = `email:${email}`;
  const session = globalOtpRateLimiter.getSession(rateLimitKey);
  if (session?.lockedUntil && Date.now() < session.lockedUntil) {
    const remainingSeconds = Math.ceil((session.lockedUntil - Date.now()) / 1000);
    return error(
      429,
      "too_many_failed_attempts",
      "Too many failed verification attempts. Please wait before trying again.",
      `Verification temporarily locked for security. Try again in ${remainingSeconds}s.`,
    );
  }

  try {
    const supabase = createAdminClient();

    // 1. Attempt verification with type: "email" (magic link / OTP)
    let { data, error: verifyError } = await supabase.auth.verifyOtp({
      email,
      token,
      type: "email",
    });

    // 2. If not found or failed, attempt type: "signup"
    if (verifyError) {
      const signupAttempt = await supabase.auth.verifyOtp({
        email,
        token,
        type: "signup",
      });
      if (!signupAttempt.error && signupAttempt.data.user) {
        data = signupAttempt.data;
        verifyError = null;
      }
    }

    // 3. Handle verification failure
    if (verifyError || !data?.user) {
      const failure = globalOtpRateLimiter.recordVerifyFailure(rateLimitKey);
      if (failure.locked) {
        return error(
          429,
          "too_many_failed_attempts",
          "Too many failed attempts. This confirmation code has been invalidated.",
          "Please request a new confirmation code.",
        );
      }

      return unauthorized(
        verifyError?.message || "Invalid or expired confirmation code. Please check your email and try again."
      );
    }

    const authUser = data.user;
    const sessionData = data.session;

    // Reset failed verification attempts on success
    globalOtpRateLimiter.clearSession(rateLimitKey);

    // Auto-create or ensure profile row exists in public.profiles
    const fullName = (authUser.user_metadata?.full_name as string) || email.split("@")[0];
    await supabase.from("profiles").upsert(
      {
        id: authUser.id,
        email: authUser.email || email,
        full_name: fullName,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "id" }
    );

    return json({
      ok: true,
      user: {
        id: authUser.id,
        email: authUser.email || email,
        name: fullName,
        avatar_url: authUser.user_metadata?.avatar_url || null,
      },
      session: sessionData
        ? {
            access_token: sessionData.access_token,
            refresh_token: sessionData.refresh_token,
            expires_in: sessionData.expires_in,
            token_type: sessionData.token_type,
          }
        : null,
    });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Internal verification error";
    return serverError(msg);
  }
}

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(handleVerifyOtpRequest);
}

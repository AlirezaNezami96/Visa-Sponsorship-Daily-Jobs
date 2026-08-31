/**
 * Core Auth & OTP utilities for VisaLane backend.
 * Provides validation, cryptographic OTP generation, rate limiting,
 * branded template rendering, and email dispatching with edge case handling.
 */

export interface RateLimitConfig {
  cooldownSeconds: number;       // min interval between consecutive OTP requests (e.g. 60s)
  maxRequestsPerWindow: number;  // max OTP requests in window (e.g. 5 in 10 mins)
  windowSeconds: number;         // window duration (e.g. 600s = 10 mins)
  maxVerifyAttempts: number;     // max wrong verification tries before token is locked (e.g. 5)
}

export const DEFAULT_RATE_LIMITS: RateLimitConfig = {
  cooldownSeconds: 60,
  maxRequestsPerWindow: 5,
  windowSeconds: 600,
  maxVerifyAttempts: 5,
};

export interface OtpSessionState {
  lastRequestAt: number;
  requestCount: number;
  failedAttempts: number;
  lockedUntil?: number;
  tokenHash?: string;
  expiresAt?: number;
}

// RFC 5322 compliant email validator (simplified & robust)
const EMAIL_REGEX = /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/;

/**
 * Normalizes email by trimming whitespace and converting to lowercase.
 */
export function normalizeEmail(email: string | null | undefined): string {
  if (!email || typeof email !== "string") return "";
  return email.trim().toLowerCase();
}

/**
 * Validates email format according to standard web rules:
 * - Must not be empty
 * - Max length 254 chars
 * - Contains single @
 * - Valid domain with TLD (at least 2 chars)
 * - No forbidden characters/spaces
 */
export function isValidEmail(email: string | null | undefined): boolean {
  const clean = normalizeEmail(email);
  if (!clean || clean.length > 254) return false;
  if (!clean.includes("@")) return false;

  const parts = clean.split("@");
  if (parts.length !== 2) return false;
  const [local, domain] = parts;
  if (!local || local.length > 64 || !domain || domain.length > 255) return false;

  // Domain must contain a valid TLD
  const domainParts = domain.split(".");
  if (domainParts.length < 2) return false;
  const tld = domainParts[domainParts.length - 1];
  if (!tld || tld.length < 2) return false;

  return EMAIL_REGEX.test(clean);
}

/**
 * Validates OTP format:
 * - 6 to 8 numeric digits (e.g. 123456 or 12345678).
 */
export function isValidOtp(token: string | null | undefined): boolean {
  if (!token || typeof token !== "string") return false;
  const clean = token.trim();
  return /^[0-9]{6,8}$/.test(clean);
}

/**
 * Generates a cryptographically secure 6-digit numeric OTP token.
 */
export function generateSecureOtp(): string {
  const array = new Uint32Array(1);
  crypto.getRandomValues(array);
  // Guarantee 6 digits with leading zeros (000000 to 999999)
  const code = (array[0] % 1000000).toString().padStart(6, "0");
  return code;
}

/**
 * Computes SHA-256 hash of the OTP token for safe storage / comparison.
 */
export async function hashOtp(token: string): Promise<string> {
  const clean = token.trim();
  const encoder = new TextEncoder();
  const data = encoder.encode(clean);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * In-memory / cache rate limiter helper.
 */
export class OtpRateLimiter {
  private sessions = new Map<string, OtpSessionState>();

  checkRequestLimit(
    key: string,
    now = Date.now(),
    config: RateLimitConfig = DEFAULT_RATE_LIMITS,
  ): { allowed: boolean; reason?: "cooldown" | "window_limit" | "locked"; retryAfterSeconds?: number } {
    const session = this.sessions.get(key);
    if (!session) {
      return { allowed: true };
    }

    // Check temporary lockout
    if (session.lockedUntil && now < session.lockedUntil) {
      const retryAfter = Math.ceil((session.lockedUntil - now) / 1000);
      return { allowed: false, reason: "locked", retryAfterSeconds: retryAfter };
    }

    // Check cooldown between requests
    const timeSinceLast = (now - session.lastRequestAt) / 1000;
    if (timeSinceLast < config.cooldownSeconds) {
      const retryAfter = Math.ceil(config.cooldownSeconds - timeSinceLast);
      return { allowed: false, reason: "cooldown", retryAfterSeconds: retryAfter };
    }

    // Check window rate limit
    if (session.requestCount >= config.maxRequestsPerWindow) {
      const windowElapsed = (now - (session.lastRequestAt - (config.maxRequestsPerWindow - 1) * config.cooldownSeconds * 1000)) / 1000;
      if (windowElapsed < config.windowSeconds) {
        const retryAfter = Math.max(1, Math.ceil(config.windowSeconds - windowElapsed));
        return { allowed: false, reason: "window_limit", retryAfterSeconds: retryAfter };
      }
    }

    return { allowed: true };
  }

  recordRequest(
    key: string,
    tokenHash: string,
    now = Date.now(),
    expiresInSeconds = 600,
    config: RateLimitConfig = DEFAULT_RATE_LIMITS,
  ): void {
    const session = this.sessions.get(key) || {
      lastRequestAt: now,
      requestCount: 0,
      failedAttempts: 0,
    };

    // Reset window count if expired
    if (now - session.lastRequestAt > config.windowSeconds * 1000) {
      session.requestCount = 0;
    }

    session.lastRequestAt = now;
    session.requestCount += 1;
    session.failedAttempts = 0; // reset verify failures on new token
    session.tokenHash = tokenHash;
    session.expiresAt = now + expiresInSeconds * 1000;
    session.lockedUntil = undefined;

    this.sessions.set(key, session);
  }

  recordVerifyFailure(
    key: string,
    now = Date.now(),
    config: RateLimitConfig = DEFAULT_RATE_LIMITS,
  ): { locked: boolean; remainingAttempts: number } {
    let session = this.sessions.get(key);
    if (!session) {
      session = {
        lastRequestAt: now,
        requestCount: 0,
        failedAttempts: 0,
      };
      this.sessions.set(key, session);
    }

    session.failedAttempts += 1;
    const remaining = Math.max(0, config.maxVerifyAttempts - session.failedAttempts);

    if (session.failedAttempts >= config.maxVerifyAttempts) {
      session.lockedUntil = now + config.windowSeconds * 1000;
      session.tokenHash = undefined; // invalidate current token
      return { locked: true, remainingAttempts: 0 };
    }

    return { locked: false, remainingAttempts: remaining };
  }

  getSession(key: string): OtpSessionState | undefined {
    return this.sessions.get(key);
  }

  clearSession(key: string): void {
    this.sessions.delete(key);
  }

  reset(): void {
    this.sessions.clear();
  }
}

export const globalOtpRateLimiter = new OtpRateLimiter();

/**
 * Renders the custom VisaLane branded email HTML template for OTP verification.
 */
export function renderOtpEmailHtml(
  token: string,
  options?: {
    siteUrl?: string;
    expiresInMinutes?: number;
    appName?: string;
  },
): string {
  const cleanToken = token.trim();
  const siteUrl = options?.siteUrl || "https://visalane.online";
  const appName = options?.appName || "VisaLane";
  const expiresIn = options?.expiresInMinutes || 10;

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Your ${appName} Verification Code</title>
  <style>
    body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
    table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
    img { -ms-interpolation-mode: bicubic; border: 0; outline: none; text-decoration: none; }
    body { margin: 0; padding: 0; width: 100% !important; background-color: #0b0f19; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
    @media screen and (max-width: 600px) {
      .container-table { width: 100% !important; padding: 12px !important; }
      .otp-slot { font-size: 32px !important; letter-spacing: 6px !important; padding: 14px 18px !important; }
      .card-content { padding: 28px 20px !important; }
    }
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: #0b0f19; color: #f1f5f9;">
  <div style="display: none; max-height: 0px; overflow: hidden;">
    Your ${appName} verification code is ${cleanToken}. Use this code to sign in.
  </div>
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #0b0f19; min-height: 100vh; padding: 40px 10px;">
    <tr>
      <td align="center" valign="top">
        <table role="presentation" class="container-table" border="0" cellpadding="0" cellspacing="0" width="560" style="max-width: 560px; width: 100%;">
          <tr>
            <td align="center" style="padding-bottom: 28px;">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <div style="display: inline-block; background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1px solid #334155; border-radius: 16px; padding: 10px 18px; box-shadow: 0 4px 20px rgba(59, 130, 246, 0.15);">
                      <table role="presentation" border="0" cellpadding="0" cellspacing="0">
                        <tr>
                          <td style="vertical-align: middle; padding-right: 10px;">
                            <div style="width: 28px; height: 28px; background: linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%); border-radius: 8px; text-align: center; line-height: 28px; color: #ffffff; font-weight: 800; font-size: 16px; box-shadow: 0 2px 10px rgba(59, 130, 246, 0.5);">
                              ✈
                            </div>
                          </td>
                          <td style="vertical-align: middle;">
                            <span style="font-size: 18px; font-weight: 700; letter-spacing: 1px; color: #ffffff; text-transform: uppercase;">Visa<span style="color: #38bdf8;">Lane</span></span>
                          </td>
                        </tr>
                      </table>
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td>
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background: linear-gradient(180deg, #111827 0%, #0f172a 100%); border: 1px solid #1e293b; border-radius: 20px; box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6); overflow: hidden;">
                <tr>
                  <td height="4" style="background: linear-gradient(90deg, #3b82f6 0%, #06b6d4 50%, #8b5cf6 100%); font-size: 0; line-height: 0;">&nbsp;</td>
                </tr>
                <tr>
                  <td class="card-content" style="padding: 40px 36px;">
                    <h1 style="margin: 0 0 12px 0; font-size: 24px; font-weight: 700; color: #ffffff; text-align: center; letter-spacing: -0.5px;">
                      Confirm Your Email
                    </h1>
                    <p style="margin: 0 0 28px 0; font-size: 15px; line-height: 24px; color: #94a3b8; text-align: center;">
                      Enter the confirmation code below to verify your account on <span style="color: #e2e8f0; font-weight: 600;">${appName}</span>.
                    </p>
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 28px;">
                      <tr>
                        <td align="center">
                          <div style="background: #090d16; border: 1.5px solid #2563eb; border-radius: 14px; padding: 18px 28px; display: inline-block; box-shadow: 0 0 24px rgba(37, 99, 235, 0.25);">
                            <span class="otp-slot" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 40px; font-weight: 800; letter-spacing: 8px; color: #38bdf8; display: block; text-align: center; margin-right: -8px;">
                              ${cleanToken}
                            </span>
                          </div>
                        </td>
                      </tr>
                    </table>
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 24px; background: rgba(30, 41, 59, 0.5); border: 1px solid rgba(51, 65, 85, 0.6); border-radius: 10px;">
                      <tr>
                        <td style="padding: 12px 16px; text-align: center; font-size: 13px; color: #94a3b8;">
                          ⏱ This code is valid for <strong style="color: #f1f5f9;">${expiresIn} minutes</strong> and can only be used once.
                        </td>
                      </tr>
                    </table>
                    <p style="margin: 0; font-size: 12px; line-height: 18px; color: #64748b; text-align: center;">
                      If you did not request this verification code, no action is needed — you can safely ignore this email.
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-top: 28px;">
              <p style="margin: 0 0 6px 0; font-size: 12px; color: #64748b; text-align: center;">
                ${appName} &bull; Verified Visa-Sponsored Careers &bull; <a href="${siteUrl}" style="color: #38bdf8; text-decoration: none;">${siteUrl.replace(/^https?:\/\//, "")}</a>
              </p>
              <p style="margin: 0; font-size: 11px; color: #475569; text-align: center;">
                Connecting top talent worldwide with verified visa-sponsoring employers.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>`;
}

/**
 * Sends OTP Email directly via Resend REST API if RESEND_API_KEY is configured.
 */
export async function sendEmailViaResendApi(params: {
  apiKey: string;
  to: string;
  token: string;
  from?: string;
  subject?: string;
}): Promise<{ ok: boolean; id?: string; error?: string }> {
  try {
    const fromAddress = params.from || "VisaLane <auth@visalane.online>";
    const subject = params.subject || `Your VisaLane Verification Code: ${params.token}`;
    const html = renderOtpEmailHtml(params.token);

    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${params.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: fromAddress,
        to: [params.to],
        subject,
        html,
      }),
    });

    if (!res.ok) {
      const errJson = await res.json().catch(() => ({}));
      return { ok: false, error: (errJson as { message?: string }).message || `Resend API error ${res.status}` };
    }

    const data = await res.json().catch(() => ({}));
    return { ok: true, id: (data as { id?: string }).id };
  } catch (err: unknown) {
    return { ok: false, error: err instanceof Error ? err.message : "Network error" };
  }
}

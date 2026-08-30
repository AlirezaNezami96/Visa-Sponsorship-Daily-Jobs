/**
 * Admin endpoint rate limiting & threat detection.
 *
 * Layer 7: Endpoint protection (10 req/min/IP)
 * Layer 6: Threat detection (alert owner on 5 failed attempts from 1 IP in 10 min)
 */

interface RateLimitBucket {
  timestamps: number[];
}

interface FailureBucket {
  failures: Array<{ timestamp: number; email?: string; reason?: string }>;
}

const rateLimitMap = new Map<string, RateLimitBucket>();
const failureMap = new Map<string, FailureBucket>();

const DEFAULT_RATE_LIMIT = 10; // 10 requests
const DEFAULT_RATE_WINDOW_MS = 60 * 1000; // 1 minute
const THREAT_FAILURE_THRESHOLD = 5; // 5 failures
const THREAT_WINDOW_MS = 10 * 60 * 1000; // 10 minutes

/**
 * Check if the IP is within the rate limit.
 */
export function checkAdminRateLimit(
  ip: string,
  limit: number = DEFAULT_RATE_LIMIT,
  windowMs: number = DEFAULT_RATE_WINDOW_MS,
): { allowed: boolean; remaining: number; resetMs: number } {
  const now = Date.now();
  let bucket = rateLimitMap.get(ip);

  if (!bucket) {
    bucket = { timestamps: [] };
    rateLimitMap.set(ip, bucket);
  }

  // Prune timestamps older than window
  bucket.timestamps = bucket.timestamps.filter((ts) => now - ts < windowMs);

  if (bucket.timestamps.length >= limit) {
    const oldest = bucket.timestamps[0];
    const resetMs = Math.max(0, windowMs - (now - oldest));
    return { allowed: false, remaining: 0, resetMs };
  }

  bucket.timestamps.push(now);
  return {
    allowed: true,
    remaining: limit - bucket.timestamps.length,
    resetMs: windowMs,
  };
}

/**
 * Record a failed admin authentication attempt.
 * If 5 failed attempts occur within 10 minutes from the same IP, trigger an alert.
 */
export async function recordAdminAuthFailure(
  ip: string,
  email?: string,
  reason?: string,
): Promise<{ alertTriggered: boolean; failureCount: number }> {
  const now = Date.now();
  let bucket = failureMap.get(ip);

  if (!bucket) {
    bucket = { failures: [] };
    failureMap.set(ip, bucket);
  }

  // Prune failures older than threat window
  bucket.failures = bucket.failures.filter((f) => now - f.timestamp < THREAT_WINDOW_MS);
  bucket.failures.push({ timestamp: now, email, reason });

  const failureCount = bucket.failures.length;

  if (failureCount >= THREAT_FAILURE_THRESHOLD) {
    // Trigger security alert
    await sendAdminSecurityAlert("🚨 High-Risk Admin Auth Threat Detected", {
      ip,
      attempted_email: email || "unknown",
      failure_count: failureCount,
      window_minutes: 10,
      reason: reason || "multiple failed auth attempts",
      timestamp: new Date().toISOString(),
    });
    return { alertTriggered: true, failureCount };
  }

  return { alertTriggered: false, failureCount };
}

/**
 * Reset failure counter on successful auth.
 */
export function recordAdminAuthSuccess(ip: string, email: string): void {
  failureMap.delete(ip);
}

/**
 * Send security notification via Telegram / Webhook if configured.
 */
export async function sendAdminSecurityAlert(
  title: string,
  details: Record<string, unknown>,
): Promise<void> {
  const botToken = typeof Deno !== "undefined" ? Deno.env.get("TELEGRAM_BOT_TOKEN") : process?.env?.TELEGRAM_BOT_TOKEN;
  const adminChatId = typeof Deno !== "undefined"
    ? Deno.env.get("TELEGRAM_ADMIN_CHAT_ID") || Deno.env.get("TELEGRAM_CHAT_ID")
    : process?.env?.TELEGRAM_ADMIN_CHAT_ID || process?.env?.TELEGRAM_CHAT_ID;

  if (!botToken || !adminChatId) {
    console.warn("[Admin Security Alert]", title, details);
    return;
  }

  const lines = [
    `⚠️ *${title}*`,
    "",
    ...Object.entries(details).map(([k, v]) => `• *${k}*: \`${String(v)}\``),
    "",
    `Time: \`${new Date().toISOString()}\``,
  ];

  try {
    await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: adminChatId,
        text: lines.join("\n"),
        parse_mode: "Markdown",
      }),
    });
  } catch (err) {
    console.error("Failed to send admin security Telegram alert:", err);
  }
}

/**
 * Reset rate limiter memory (useful for unit tests).
 */
export function _resetRateLimiterState(): void {
  rateLimitMap.clear;
  rateLimitMap.clear();
  failureMap.clear();
}

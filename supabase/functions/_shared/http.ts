/**
 * HTTP helpers shared by all Edge Functions.
 * Error codes are stable and documented in docs/api/README.md.
 */

export const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
};

export function json(body: unknown, init: ResponseInit = { status: 200 }): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...CORS_HEADERS,
      ...(init.headers as Record<string, string> | undefined),
    },
  });
}

export function error(status: number, code: string, message: string): Response {
  return json({ error: { code, message } }, { status });
}

export function unauthorized(message = "Missing or invalid Authorization header"): Response {
  return error(401, "unauthorized", message);
}

export function badRequest(message: string): Response {
  return error(400, "bad_request", message);
}

export function forbidden(message: string): Response {
  return error(403, "forbidden", message);
}

/** 402 = usage limit reached (distinct from 429 rate limiting). */
export function paymentRequired(message: string): Response {
  return error(402, "usage_limit_reached", message);
}

export function serverError(message = "Internal error"): Response {
  return error(500, "internal_error", message);
}

export function handleOptions(req: Request): Response | null {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: CORS_HEADERS });
  }
  return null;
}

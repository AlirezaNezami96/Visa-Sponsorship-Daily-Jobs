/**
 * HTTP helpers shared by all Edge Functions.
 * Error codes are stable and documented in docs/api/README.md.
 *
 * Error shape (Phase 4 unified format):
 * {
 *   error: {
 *     code: string,       // machine-readable stable code
 *     message: string,    // developer message
 *     user_action?: string, // optional human-facing guidance
 *     request_id: string, // crypto.randomUUID() for tracing
 *     timestamp: string,  // ISO 8601
 *   }
 * }
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

export function structuredError(
  status: number,
  code: string,
  message: string,
  userAction?: string,
): Response {
  const body: Record<string, unknown> = {
    error: {
      code,
      message,
      request_id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
    },
  };
  if (userAction) {
    (body.error as Record<string, unknown>).user_action = userAction;
  }
  return json(body, { status });
}

export function error(status: number, code: string, message: string, userAction?: string): Response {
  return structuredError(status, code, message, userAction);
}

export function unauthorized(message = "Missing or invalid Authorization header"): Response {
  return error(401, "unauthorized", message, "Please sign in and try again.");
}

export function badRequest(message: string, userAction?: string): Response {
  return error(400, "bad_request", message, userAction);
}

export function forbidden(message: string): Response {
  return error(403, "forbidden", message, "You do not have permission to perform this action.");
}

/** 402 = usage limit reached (distinct from 429 rate limiting). */
export function paymentRequired(message: string): Response {
  return error(402, "usage_limit_reached", message, "Upgrade your plan to continue using this feature.");
}

export function notFound(message: string): Response {
  return error(404, "not_found", message);
}

export function serverError(message = "Internal error"): Response {
  return error(500, "internal_error", message, "An unexpected error occurred. Please try again in a few moments.");
}

export function handleOptions(req: Request): Response | null {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: CORS_HEADERS });
  }
  return null;
}

export const jsonResponse = json;

export function errorResponse(code: string, message: string, status = 400): Response {
  return error(status, code.toLowerCase(), message);
}


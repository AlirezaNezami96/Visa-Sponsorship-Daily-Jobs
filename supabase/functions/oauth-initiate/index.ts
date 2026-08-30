/**
 * POST /functions/v1/oauth-initiate
 * Initiates an OAuth flow for Google or GitHub.
 * Returns the authorization URL and a secure state parameter.
 *
 * Body: { provider: "google"|"github", redirect_uri?: string, client_state?: string }
 * Response: { authorization_url: string, state: string, provider: string }
 */
import { handleOptions, json, badRequest, serverError } from "../_shared/http.ts";
import { getEnv } from "../_shared/env.ts";

const GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize";

const GOOGLE_SCOPES = ["openid", "email", "profile"].join(" ");
const GITHUB_SCOPES = ["read:user", "user:email"].join(" ");

export function buildOAuthUrl(
  provider: string,
  clientId: string,
  redirectUri: string,
  state: string,
): string {
  const norm = provider.toLowerCase().trim();
  if (norm === "google") {
    const params = new URLSearchParams({
      client_id: clientId,
      redirect_uri: redirectUri,
      response_type: "code",
      scope: GOOGLE_SCOPES,
      state,
      access_type: "offline",
      prompt: "select_account",
    });
    return `${GOOGLE_AUTH_URL}?${params.toString()}`;
  }
  if (norm === "github") {
    const params = new URLSearchParams({
      client_id: clientId,
      redirect_uri: redirectUri,
      scope: GITHUB_SCOPES,
      state,
      allow_signup: "true",
    });
    return `${GITHUB_AUTH_URL}?${params.toString()}`;
  }
  throw new Error(`Unsupported provider: ${provider}`);
}

export function generateStateToken(provider: string, clientState = ""): string {
  const nonce = crypto.randomUUID();
  const timestamp = Date.now();
  const payload = JSON.stringify({ provider, nonce, timestamp, client_state: clientState });
  return btoa(payload);
}

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
  const preflight = handleOptions(req);
  if (preflight) return preflight;

  if (req.method !== "POST" && req.method !== "GET") {
    return json({ error: { code: "method_not_allowed", message: "POST or GET only" } }, { status: 405 });
  }

  try {
    let provider = "";
    let redirectUri = "";
    let clientState = "";

    if (req.method === "POST") {
      const body = await req.json().catch(() => ({}));
      provider = typeof body.provider === "string" ? body.provider : "";
      redirectUri = typeof body.redirect_uri === "string" ? body.redirect_uri : "";
      clientState = typeof body.client_state === "string" ? body.client_state : "";
    } else {
      const url = new URL(req.url);
      provider = url.searchParams.get("provider") ?? "";
      redirectUri = url.searchParams.get("redirect_uri") ?? "";
      clientState = url.searchParams.get("client_state") ?? "";
    }

    if (!provider) {
      return badRequest("provider is required ('google' or 'github')", "Please select a login provider.");
    }

    const normProvider = provider.toLowerCase().trim();
    if (normProvider !== "google" && normProvider !== "github") {
      return badRequest(`Unsupported provider '${provider}'. Supported: google, github`);
    }

    const supabaseUrl = getEnv("SUPABASE_URL") ?? "";
    const defaultRedirect = `${supabaseUrl.replace(/\/$/, "")}/functions/v1/oauth-callback`;
    const finalRedirect = redirectUri || defaultRedirect;

    let clientId = "";
    if (normProvider === "google") {
      clientId = getEnv("GOOGLE_CLIENT_ID") ?? "";
      if (!clientId) {
        return serverError("Google Client ID is not configured in Supabase secrets");
      }
    } else if (normProvider === "github") {
      clientId = getEnv("GITHUB_CLIENT_ID") ?? "";
      if (!clientId) {
        return serverError("GitHub Client ID is not configured in Supabase secrets");
      }
    }

    const stateToken = generateStateToken(normProvider, clientState);
    const authUrl = buildOAuthUrl(normProvider, clientId, finalRedirect, stateToken);

    return json({
      authorization_url: authUrl,
      state: stateToken,
      provider: normProvider,
    });
  } catch (err) {
    console.error("oauth-initiate error:", err);
    return serverError();
  }
  });
}

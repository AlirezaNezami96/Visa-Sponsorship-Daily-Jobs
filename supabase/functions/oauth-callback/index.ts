/**
 * GET/POST /functions/v1/oauth-callback
 * OAuth callback handler for Google and GitHub.
 *
 * Exchanges authorization code, fetches user profile, syncs avatar and metadata,
 * and redirects to frontend application or returns profile JSON.
 */
import { createAdminClient } from "../_shared/supabase-clients.ts";
import { handleOptions, json, badRequest, serverError, CORS_HEADERS } from "../_shared/http.ts";
import { getEnv } from "../_shared/env.ts";

export interface DecodedState {
  provider: string;
  nonce: string;
  timestamp: number;
  client_state?: string;
}

export function decodeState(raw: string | null): DecodedState | null {
  if (!raw) return null;
  try {
    const decoded = atob(raw);
    const parsed = JSON.parse(decoded);
    if (parsed.provider && parsed.timestamp) {
      return parsed as DecodedState;
    }
  } catch {
    // Malformed state
  }
  return null;
}

export async function exchangeGoogleCode(
  code: string,
  clientId: string,
  clientSecret: string,
  redirectUri: string,
): Promise<{ access_token: string; id_token?: string }> {
  const resp = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      code,
      client_id: clientId,
      client_secret: clientSecret,
      redirect_uri: redirectUri,
      grant_type: "authorization_code",
    }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Google token exchange failed (${resp.status}): ${text}`);
  }
  return await resp.json();
}

export async function fetchGoogleProfile(accessToken: string): Promise<{
  id: string;
  email: string;
  name?: string;
  picture?: string;
}> {
  const resp = await fetch("https://www.googleapis.com/oauth2/v2/userinfo", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!resp.ok) {
    throw new Error(`Google userinfo failed (${resp.status})`);
  }
  return await resp.json();
}

export async function exchangeGitHubCode(
  code: string,
  clientId: string,
  clientSecret: string,
  redirectUri: string,
): Promise<{ access_token: string }> {
  const resp = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
    },
    body: new URLSearchParams({
      code,
      client_id: clientId,
      client_secret: clientSecret,
      redirect_uri: redirectUri,
    }),
  });
  if (!resp.ok) {
    throw new Error(`GitHub token exchange failed (${resp.status})`);
  }
  const data = await resp.json();
  if (data.error) {
    throw new Error(`GitHub token error: ${data.error_description || data.error}`);
  }
  return data;
}

export async function fetchGitHubProfile(accessToken: string): Promise<{
  id: string;
  email: string;
  name?: string;
  avatar_url?: string;
}> {
  const headers = {
    Authorization: `Bearer ${accessToken}`,
    Accept: "application/vnd.github.v3+json",
    "User-Agent": "VisaLane-OAuth",
  };
  const resp = await fetch("https://api.github.com/user", { headers });
  if (!resp.ok) {
    throw new Error(`GitHub userinfo failed (${resp.status})`);
  }
  const user = await resp.json();
  let email = user.email;

  if (!email) {
    try {
      const emailResp = await fetch("https://api.github.com/user/emails", { headers });
      if (emailResp.ok) {
        const emails: Array<{ email: string; primary: boolean; verified: boolean }> = await emailResp.json();
        const primary = emails.find((e) => e.primary && e.verified) || emails.find((e) => e.verified) || emails[0];
        if (primary) email = primary.email;
      }
    } catch {
      // ignore
    }
  }

  return {
    id: String(user.id),
    email: email || `${user.login}@users.noreply.github.com`,
    name: user.name || user.login,
    avatar_url: user.avatar_url,
  };
}

if (typeof Deno !== "undefined" && typeof Deno.serve === "function") {
  Deno.serve(async (req) => {
  const preflight = handleOptions(req);
  if (preflight) return preflight;

  const url = new URL(req.url);
  const isGet = req.method === "GET";

  let code = "";
  let state = "";
  let errorParam = "";
  let errorDesc = "";

  if (isGet) {
    code = url.searchParams.get("code") ?? "";
    state = url.searchParams.get("state") ?? "";
    errorParam = url.searchParams.get("error") ?? "";
    errorDesc = url.searchParams.get("error_description") ?? "";
  } else {
    const body = await req.json().catch(() => ({}));
    code = typeof body.code === "string" ? body.code : "";
    state = typeof body.state === "string" ? body.state : "";
    errorParam = typeof body.error === "string" ? body.error : "";
    errorDesc = typeof body.error_description === "string" ? body.error_description : "";
  }

  // Handle provider cancellations
  if (errorParam) {
    const msg = errorDesc || errorParam;
    if (isGet) {
      const frontendUrl = getEnv("FRONTEND_URL") || "https://visalane.online";
      return Response.redirect(`${frontendUrl}/auth/login?error=${encodeURIComponent(msg)}`, 302);
    }
    return json({ error: { code: "oauth_cancelled", message: msg } }, { status: 400 });
  }

  if (!code || !state) {
    return badRequest("Both 'code' and 'state' parameters are required for OAuth callback");
  }

  const decoded = decodeState(state);
  if (!decoded) {
    return badRequest("Invalid or expired OAuth state parameter (CSRF verification failed)");
  }

  // Check state expiration (15 minutes)
  if (Date.now() - decoded.timestamp > 15 * 60 * 1000) {
    return badRequest("OAuth state parameter has expired. Please restart login.");
  }

  const provider = decoded.provider.toLowerCase().trim();
  const supabaseUrl = getEnv("SUPABASE_URL") ?? "";
  const redirectUri = `${supabaseUrl.replace(/\/$/, "")}/functions/v1/oauth-callback`;

  try {
    let profileData: { id: string; email: string; name?: string; picture?: string; avatar_url?: string };

    if (provider === "google") {
      const clientId = getEnv("GOOGLE_CLIENT_ID") ?? "";
      const clientSecret = getEnv("GOOGLE_CLIENT_SECRET") ?? "";
      const token = await exchangeGoogleCode(code, clientId, clientSecret, redirectUri);
      profileData = await fetchGoogleProfile(token.access_token);
    } else if (provider === "github") {
      const clientId = getEnv("GITHUB_CLIENT_ID") ?? "";
      const clientSecret = getEnv("GITHUB_CLIENT_SECRET") ?? "";
      const token = await exchangeGitHubCode(code, clientId, clientSecret, redirectUri);
      profileData = await fetchGitHubProfile(token.access_token);
    } else {
      return badRequest(`Unsupported provider in callback: ${provider}`);
    }

    const email = profileData.email.toLowerCase().trim();
    const providerId = profileData.id;
    const avatarUrl = profileData.picture || profileData.avatar_url || null;
    const fullName = profileData.name || null;

    // Database Sync via Admin Client
    const admin = createAdminClient();
    const nowIso = new Date().toISOString();

    // Check if user exists with matching email
    const { data: existingUser } = await admin
      .from("profiles")
      .select("id, email, login_count, oauth_provider")
      .eq("email", email)
      .maybeSingle();

    let userId = existingUser?.id;
    let loginCount = (existingUser?.login_count ?? 0) + 1;

    if (existingUser) {
      // Update existing user profile
      await admin
        .from("profiles")
        .update({
          oauth_provider: provider,
          oauth_provider_id: providerId,
          oauth_profile_image: avatarUrl,
          oauth_metadata: { provider, provider_id: providerId, synced_at: nowIso },
          last_login_at: nowIso,
          login_count: loginCount,
          full_name: fullName || undefined,
        })
        .eq("id", userId);
    } else {
      // Create new profile record if auth user id exists or generate
      const newId = crypto.randomUUID();
      userId = newId;
      await admin
        .from("profiles")
        .insert({
          id: newId,
          email,
          full_name: fullName,
          oauth_provider: provider,
          oauth_provider_id: providerId,
          oauth_profile_image: avatarUrl,
          oauth_metadata: { provider, provider_id: providerId, synced_at: nowIso },
          last_login_at: nowIso,
          login_count: 1,
        });
    }

    // Log analytics event
    await admin.from("analytics_events").insert({
      event_name: "oauth_login_complete",
      user_id: userId,
      metadata: { provider, email_domain: email.split("@")[1] },
    }).then(() => undefined, () => undefined);

    if (isGet) {
      const frontendUrl = getEnv("FRONTEND_URL") || "https://visalane.online";
      return Response.redirect(`${frontendUrl}/auth/callback?provider=${provider}&email=${encodeURIComponent(email)}`, 302);
    }

    return json({
      success: true,
      user_id: userId,
      email,
      provider,
      avatar_url: avatarUrl,
      full_name: fullName,
    });
  } catch (err) {
    console.error("oauth-callback error:", err);
    if (isGet) {
      const frontendUrl = getEnv("FRONTEND_URL") || "https://visalane.online";
      return Response.redirect(`${frontendUrl}/auth/login?error=oauth_failed`, 302);
    }
    return serverError();
  }
  });
}

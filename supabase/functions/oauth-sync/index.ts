/**
 * POST /functions/v1/oauth-sync
 * Auth required. Called by the frontend immediately after a successful
 * Supabase OAuth callback (Google or GitHub) to sync the provider's
 * avatar_url / profile image into the profiles table and record login
 * metadata.
 *
 * Why a dedicated function rather than a DB trigger on auth.users?
 *   - auth.* tables are not directly writable by user code.
 *   - raw_user_meta_data differs per provider (avatar_url vs picture).
 *   - This keeps the sync logic versioned, testable, and auditable.
 *
 * Body: {} (empty — all data read from the caller's JWT claims)
 *
 * Response: { ok: true, profile_image: string|null, provider: string|null }
 */
import { createUserClient, createAdminClient, hasAuthHeader } from "../_shared/supabase-clients.ts";
import { getAuthUser } from "../_shared/auth.ts";
import { handleOptions, json, unauthorized, serverError } from "../_shared/http.ts";

/** Extract avatar URL from provider-specific metadata shapes. */
function extractAvatarUrl(meta: Record<string, unknown> | null | undefined): string | null {
  if (!meta) return null;
  // Google: picture, avatar_url; GitHub: avatar_url
  const candidates = [meta.picture, meta.avatar_url, meta.photo_url];
  for (const c of candidates) {
    if (typeof c === "string" && c.startsWith("http")) return c;
  }
  return null;
}

/** Extract OAuth provider from app_metadata (set by Supabase auth). */
function extractProvider(appMeta: Record<string, unknown> | null | undefined): string | null {
  if (!appMeta) return null;
  return typeof appMeta.provider === "string" ? appMeta.provider : null;
}

/** Extract provider sub/id from user_metadata or identities. */
function extractProviderId(
  meta: Record<string, unknown> | null | undefined,
  user: { id: string },
): string {
  if (meta?.sub && typeof meta.sub === "string") return meta.sub;
  if (meta?.provider_id && typeof meta.provider_id === "string") return meta.provider_id;
  return user.id; // fallback: use Supabase user id
}

Deno.serve(async (req) => {
  const preflight = handleOptions(req);
  if (preflight) return preflight;
  if (req.method !== "POST") {
    return json({ error: { code: "method_not_allowed", message: "POST only" } }, { status: 405 });
  }
  if (!hasAuthHeader(req)) return unauthorized();

  try {
    const userClient = createUserClient(req);
    const user = await getAuthUser(userClient);
    if (!user) return unauthorized();

    const rawMeta = (user.user_metadata ?? {}) as Record<string, unknown>;
    const appMeta = (user.app_metadata ?? {}) as Record<string, unknown>;

    const provider = extractProvider(appMeta);
    const providerId = extractProviderId(rawMeta, user);
    const profileImage = extractAvatarUrl(rawMeta);

    // Use admin client for the RPC (SECURITY DEFINER, needs service-role).
    const admin = createAdminClient();
    await admin.rpc("record_oauth_login", {
      p_user_id: user.id,
      p_provider: provider ?? "unknown",
      p_provider_id: providerId,
      p_profile_image: profileImage,
    });

    // Also ensure the profile row exists (created on first signup via DB trigger
    // or handle-new-user; this is a safety net).
    const { data: profile } = await userClient
      .from("profiles")
      .select("id, email, oauth_profile_image")
      .eq("id", user.id)
      .maybeSingle();

    if (!profile) {
      // First-time OAuth user: create minimal profile row.
      const email = user.email ?? rawMeta.email ?? "";
      await userClient.from("profiles").insert({
        id: user.id,
        email: String(email),
        oauth_provider: provider,
        oauth_provider_id: providerId,
        oauth_profile_image: profileImage,
        last_login_at: new Date().toISOString(),
        login_count: 1,
      });
    }

    await userClient.from("analytics_events").insert({
      event_name: "oauth_login",
      user_id: user.id,
      metadata: { provider, cached_image: profileImage != null },
    }).then(() => undefined, () => undefined);

    return json({
      ok: true,
      provider,
      profile_image: profileImage,
    });
  } catch (err) {
    console.error("oauth-sync error:", err);
    return serverError();
  }
});

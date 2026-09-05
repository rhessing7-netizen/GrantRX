import { NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

/**
 * OAuth callback route handler.
 *
 * After Google/LinkedIn OAuth redirects back to /auth/callback with a `code`
 * query param, this route:
 *   1. Exchanges the code for a Supabase session (server-side).
 *   2. Extracts user identity metadata (full_name, email, avatar_url).
 *   3. Upserts the backend profile via POST /profiles with consent timestamps.
 *   4. Redirects to / (Discovery Feed) if onboarding is complete, or
 *      /?onboarding=open if the user still needs clinical onboarding.
 */
export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const code = requestUrl.searchParams.get("code");
  const errorParam = requestUrl.searchParams.get("error");

  // OAuth provider returned an error
  if (errorParam) {
    return NextResponse.redirect(
      `${requestUrl.origin}/?auth_error=${encodeURIComponent(errorParam)}`,
    );
  }

  if (!code) {
    return NextResponse.redirect(
      `${requestUrl.origin}/?auth_error=missing_code`,
    );
  }

  const rawSupabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  // Validate the URL is a proper HTTP/HTTPS URL (not just truthy)
  let supabaseUrl: string | null = null;
  if (rawSupabaseUrl) {
    try {
      const parsed = new URL(rawSupabaseUrl);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") {
        supabaseUrl = rawSupabaseUrl;
      }
    } catch {
      // invalid URL — leave as null
    }
  }

  if (!supabaseUrl || !supabaseAnonKey) {
    return NextResponse.redirect(
      `${requestUrl.origin}/?auth_error=supabase_not_configured`,
    );
  }

  const cookieStore = await cookies();

  const supabase = createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options),
          );
        } catch {
          // The setAll method was called from a Server Component.
          // This can be ignored if you have middleware refreshing sessions.
        }
      },
    },
  });

  // Exchange the OAuth code for a session
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);
  if (error || !data.session) {
    return NextResponse.redirect(
      `${requestUrl.origin}/?auth_error=${encodeURIComponent(error?.message ?? "session_failed")}`,
    );
  }

  const session = data.session;
  const user = session.user;

  // Extract identity metadata from OAuth payload
  const fullName =
    (user.user_metadata?.full_name as string | undefined) ??
    (user.user_metadata?.name as string | undefined) ??
    null;
  const email = user.email ?? null;

  // Read consent flags from the cookie set by AuthModal before OAuth redirect.
  // These survive the OAuth round-trip (queryParams to the provider do not).
  let marketingOptIn = false;
  let consentFullName: string | null = null;
  const consentCookie = cookieStore.get("grantrx_consent");
  if (consentCookie?.value) {
    try {
      const consent = JSON.parse(consentCookie.value);
      marketingOptIn = consent.marketing_opt_in === true;
      consentFullName = consent.full_name ?? null;
    } catch {
      // Malformed cookie — fall back to defaults
    }
  }

  // Use the consent-stored full_name if the OAuth payload didn't provide one
  const effectiveFullName = fullName ?? consentFullName;

  // Upsert the backend profile with consent timestamps.
  // Sanitize the access token to prevent Headers.append exceptions from
  // stray whitespace, newlines, or malformed JWT strings.
  const accessToken = session?.access_token
    ? session.access_token.trim().replace(/[\r\n]/g, "")
    : "";

  let profileExists = false;
  try {
    const resp = await fetch(`${apiUrl}/profiles`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify({
        full_name: effectiveFullName,
        email,
        terms_accepted: true,
        privacy_accepted: true,
        marketing_opt_in: marketingOptIn,
      }),
    });

    if (resp.ok) {
      const profile = await resp.json();
      // If the user has a primary_discipline set, they've completed onboarding
      if (profile.primary_discipline) {
        profileExists = true;
      }
    } else if (resp.status === 409) {
      // Profile already exists (e.g. returning user) — they've onboarded
      profileExists = true;
    }
  } catch (err) {
    // Profile upsert failed (network error, header rejection, timeout, etc.)
    // Do NOT block the user with an auth_error redirect — the Supabase session
    // cookies are already established, so fall through to the normal redirect
    // flow. The client-side app will retry profile initialization on the
    // onboarding screen if needed.
    console.warn("Backend profile upsert skipped during callback:", err);
  }

  // Clear the consent cookie now that it's been consumed
  cookieStore.set("grantrx_consent", "", { maxAge: 0, path: "/" });

  // Route returning users to "/" and new users to "/?onboarding=open"
  if (profileExists) {
    return NextResponse.redirect(`${requestUrl.origin}/`);
  }
  return NextResponse.redirect(`${requestUrl.origin}/?onboarding=open`);
}

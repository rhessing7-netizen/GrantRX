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

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  const marketingOptIn =
    (user.user_metadata?.marketing_opt_in as boolean | undefined) ?? false;

  // Upsert the backend profile with consent timestamps
  try {
    const resp = await fetch(`${apiUrl}/profiles`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({
        full_name: fullName,
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
        return NextResponse.redirect(`${requestUrl.origin}/`);
      }
    }
  } catch {
    // Profile upsert failed — fall through to onboarding redirect
  }

  // No primary_discipline or profile creation failed — send to onboarding
  return NextResponse.redirect(`${requestUrl.origin}/?onboarding=open`);
}

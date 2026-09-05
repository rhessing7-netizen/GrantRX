"use client";

import { useState } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { setAuthToken } from "@/lib/api";
import type { Profile } from "@/lib/types";

export type AuthModalProps = {
  open: boolean;
  onClose: () => void;
  onAuthSuccess: (profile: Profile | null) => void;
};

export function AuthModal({ open, onClose, onAuthSuccess }: AuthModalProps) {
  const [mode, setMode] = useState<"signin" | "signup">("signup");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [marketingOptIn, setMarketingOptIn] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState<{ email: boolean; password: boolean }>({ email: false, password: false });
  const [termsShake, setTermsShake] = useState(false);

  if (!open) return null;

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  const passwordValid = password.length >= 6;
  const showEmailError = touched.email && !emailValid;
  const showPasswordError = touched.password && !passwordValid;

  const canSubmit =
    emailValid &&
    passwordValid &&
    (mode === "signin" || (fullName.trim() !== "" && termsAccepted));

  const triggerTermsShake = () => {
    setTermsShake(true);
    setTimeout(() => setTermsShake(false), 600);
  };

  const handleOAuth = async (provider: "google" | "linkedin_oidc") => {
    // Enforce Terms checkbox for OAuth sign-ups too
    if (mode === "signup" && !termsAccepted) {
      triggerTermsShake();
      setError("Please accept the Terms of Service & Privacy Policy to continue.");
      return;
    }
    setError(null);

    // Persist consent flags to localStorage so they survive the OAuth redirect.
    // Also set cookies so the server-side callback route can read them.
    if (mode === "signup") {
      const consent = {
        terms_accepted: true,
        privacy_accepted: true,
        marketing_opt_in: marketingOptIn,
        full_name: fullName.trim() || null,
        timestamp: new Date().toISOString(),
      };
      try {
        localStorage.setItem("grantrx_oauth_consent", JSON.stringify(consent));
        // Cookie for server-side callback (expires in 10 minutes)
        const cookieExpiry = new Date(Date.now() + 10 * 60 * 1000).toUTCString();
        document.cookie = `grantrx_consent=${JSON.stringify(consent)}; expires=${cookieExpiry}; path=/; SameSite=Lax`;
      } catch {
        // localStorage may be unavailable (private mode) — cookies still work
      }
    }

    if (!supabase) {
      // Dev mode without Supabase configured — simulate auth
      setAuthToken("grantrx-dev-demo");
      onAuthSuccess(null);
      return;
    }

    try {
      const redirectTo = `${window.location.origin}/auth/callback`;
      const { error: sbError } = await supabase.auth.signInWithOAuth({
        provider,
        options: {
          redirectTo,
        },
      });
      if (sbError) {
        // Provider not enabled in Supabase dashboard
        if (
          sbError.message.includes("provider") ||
          sbError.message.includes("not enabled") ||
          sbError.message.includes("not supported") ||
          sbError.message.includes("OAuth")
        ) {
          setError(
            "OAuth provider is not yet enabled in Supabase. Please sign up using email and password.",
          );
        } else {
          setError(sbError.message);
        }
      }
    } catch {
      setError(
        "OAuth provider is not yet enabled in Supabase. Please sign up using email and password.",
      );
    }
  };

  const handleSubmit = async () => {
    console.log("[AuthModal] Submitting with mode:", mode);
    console.log("[AuthModal] NEXT_PUBLIC_API_URL:", process.env.NEXT_PUBLIC_API_URL);
    console.log("[AuthModal] NEXT_PUBLIC_SUPABASE_URL:", process.env.NEXT_PUBLIC_SUPABASE_URL);
    setTouched({ email: true, password: true });
    if (!emailValid || !passwordValid) return;
    if (mode === "signup" && !termsAccepted) {
      triggerTermsShake();
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      if (!supabase) {
        // Dev mode without Supabase configured — simulate auth
        console.log("[AuthModal] No Supabase client — using dev demo token");
        setAuthToken("grantrx-dev-demo");
        onAuthSuccess(null);
        return;
      }

      if (mode === "signup") {
        const { data, error: authError } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: { data: { full_name: fullName.trim() } },
        });
        if (authError) {
          setError(authError.message);
          setSubmitting(false);
          return;
        }

        // Set the auth token for API calls if a session was returned
        if (data.session?.access_token) {
          console.log("[AuthModal] Signup: setAuthToken with session token, length:", data.session.access_token.length);
          setAuthToken(data.session.access_token);
        }

        // Construct default base profile so the session never resets to null
        const studentProfile = {
          id: data?.user?.id || "local-user",
          user_id: data?.user?.id || "local-user",
          full_name: fullName.trim(),
          email: email.trim(),
          primary_discipline: "pharmacy",
          target_credential: "PharmD",
          clinical_phase: "Professional (P1-P4)",
          gpa: 3.5,
          state_residence: "OH",
          updated_at: new Date().toISOString(),
        };

        // Store in localStorage immediately so the LeftPanel and feed
        // recognize the user is logged in without waiting for backend sync.
        try {
          localStorage.setItem("grantrx_profile", JSON.stringify(studentProfile));
        } catch {
          // localStorage may be unavailable (private mode) — proceed anyway
        }

        // Attempt direct profile initialization via Supabase (best-effort)
        try {
          if (data?.user) {
            await supabase.from("profiles").upsert({
              id: data.user.id,
              user_id: data.user.id,
              full_name: fullName.trim(),
              email: email.trim(),
              terms_accepted_at: new Date().toISOString(),
              privacy_accepted_at: new Date().toISOString(),
              marketing_opt_in: marketingOptIn,
              marketing_opt_in_at: marketingOptIn ? new Date().toISOString() : null,
            });
          }
        } catch (dbErr) {
          console.warn("Profile table upsert skipped:", dbErr);
        }

        // Advance user to the app with the student profile
        onAuthSuccess(studentProfile as unknown as Profile);
      } else {
        const { data, error: authError } =
          await supabase.auth.signInWithPassword({ email, password });
        if (authError) {
          setError(authError.message);
          setSubmitting(false);
          return;
        }

        if (data.session?.access_token) {
          console.log("[AuthModal] Signin: setAuthToken with session token, length:", data.session.access_token.length);
          setAuthToken(data.session.access_token);
        }

        // Advance user — profile will be loaded from Supabase or localStorage
        onAuthSuccess(null);
      }
    } catch (err: any) {
      console.error("[AuthModal Catch] Detailed error object:", err);
      console.error("[AuthModal Catch] Error stack:", err?.stack);
      setError(
        err?.stack
          ? `${err.message} (${err.stack.split("\n")[1]?.trim() || ""})`
          : err?.message || "Registration failed",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-textPrimary/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="max-w-md w-full max-h-[90vh] overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl relative"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-600 transition"
          aria-label="Close"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {/* Header */}
        <div className="mb-4 text-center pr-6">
          <h2 className="font-serif text-xl font-bold text-textPrimary">
            {mode === "signup" ? "Create your account" : "Welcome back"}
          </h2>
          <p className="mt-1 text-sm text-textSecondary">
            {mode === "signup"
              ? "Sign up to find matched scholarships"
              : "Sign in to your GrantRx account"}
          </p>
        </div>

        {/* Mode toggle */}
        <div className="mb-4 flex rounded-full bg-textSecondary/10 p-1">
          <button
            type="button"
            onClick={() => setMode("signup")}
            className={`flex-1 rounded-full px-4 py-1.5 text-sm font-medium transition ${
              mode === "signup"
                ? "bg-crayolaBlue text-surfaceBg"
                : "text-textSecondary"
            }`}
          >
            Sign Up
          </button>
          <button
            type="button"
            onClick={() => setMode("signin")}
            className={`flex-1 rounded-full px-4 py-1.5 text-sm font-medium transition ${
              mode === "signin"
                ? "bg-crayolaBlue text-surfaceBg"
                : "text-textSecondary"
            }`}
          >
            Sign In
          </button>
        </div>

        {error && (
          <div className="mb-3 rounded-xl bg-red-50 px-4 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* OAuth provider buttons */}
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => handleOAuth("google")}
            className="flex w-full items-center justify-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-textPrimary shadow-sm transition hover:bg-slate-50 hover:border-slate-300"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            Continue with Google
          </button>

          <button
            type="button"
            onClick={() => handleOAuth("linkedin_oidc")}
            className="flex w-full items-center justify-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-textPrimary shadow-sm transition hover:bg-slate-50 hover:border-slate-300"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="#0A66C2" aria-hidden="true">
              <path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.34V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.12 2.06 2.06 0 0 1 0 4.12zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.72V1.72C24 .77 23.2 0 22.22 0z" />
            </svg>
            Continue with LinkedIn
          </button>
        </div>

        {/* Divider */}
        <div className="my-4 flex items-center gap-3">
          <div className="h-px flex-1 bg-slate-200" />
          <span className="text-xs font-medium text-textSecondary">or</span>
          <div className="h-px flex-1 bg-slate-200" />
        </div>

        {/* Form */}
        <div className="space-y-3">
          {mode === "signup" && (
            <div>
              <label className="block text-sm font-medium text-textSecondary">
                Full Name
              </label>
              <input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Jane Doe"
                className="mt-1 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2 text-textPrimary"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-textSecondary">
              Email
            </label>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => setTouched((t) => ({ ...t, email: true }))}
              type="email"
              placeholder="jane@example.com"
              className={`mt-1 w-full rounded-xl border bg-surfaceBg px-4 py-2 text-textPrimary transition ${
                showEmailError
                  ? "border-red-400 ring-1 ring-red-200"
                  : "border-textSecondary/20 focus:border-crayolaBlue"
              }`}
            />
            {showEmailError && (
              <p className="mt-1 text-xs text-red-500">Please enter a valid email address.</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-textSecondary">
              Password
            </label>
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onBlur={() => setTouched((t) => ({ ...t, password: true }))}
              type="password"
              placeholder="At least 6 characters"
              className={`mt-1 w-full rounded-xl border bg-surfaceBg px-4 py-2 text-textPrimary transition ${
                showPasswordError
                  ? "border-red-400 ring-1 ring-red-200"
                  : "border-textSecondary/20 focus:border-crayolaBlue"
              }`}
            />
            {showPasswordError && (
              <p className="mt-1 text-xs text-red-500">Password must be at least 6 characters.</p>
            )}
          </div>

          {mode === "signup" && (
            <div className="space-y-2.5 pt-1">
              {/* Terms & Privacy — mandatory */}
              <label
                className={`flex items-start gap-2.5 text-sm text-textPrimary ${termsShake ? "animate-shake" : ""}`}
                style={termsShake ? { animation: "shake 0.4s ease-in-out" } : undefined}
              >
                <input
                  type="checkbox"
                  checked={termsAccepted}
                  onChange={(e) => setTermsAccepted(e.target.checked)}
                  className={`mt-0.5 h-4 w-4 accent-crayolaBlue ${termsShake ? "ring-2 ring-red-300 rounded" : ""}`}
                />
                <span>
                  I agree to the{" "}
                  <Link
                    href="/terms"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-crayolaBlue underline"
                  >
                    Terms of Service
                  </Link>{" "}
                  and{" "}
                  <Link
                    href="/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-crayolaBlue underline"
                  >
                    Privacy Policy
                  </Link>
                </span>
              </label>

              {/* Marketing opt-in — optional */}
              <label className="flex items-start gap-2.5 text-sm text-textSecondary">
                <input
                  type="checkbox"
                  checked={marketingOptIn}
                  onChange={(e) => setMarketingOptIn(e.target.checked)}
                  className="mt-0.5 h-4 w-4 accent-crayolaBlue"
                />
                <span>
                  I opt in to receive scholarship alerts, updates, and email
                  communications from GrantRx, its parent company, and
                  subsidiaries.
                </span>
              </label>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="mt-4 flex items-center justify-between">
          <button
            onClick={onClose}
            className="text-sm text-textSecondary hover:text-textPrimary"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
            className="rounded-full bg-crayolaBlue px-6 py-2 text-sm font-medium text-surfaceBg disabled:opacity-40"
          >
            {submitting
              ? "Please wait…"
              : mode === "signup"
                ? "Create Account"
                : "Sign In"}
          </button>
        </div>
      </div>
    </div>
  );
}

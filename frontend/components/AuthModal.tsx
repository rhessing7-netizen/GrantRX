"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { api, setAuthToken } from "@/lib/api";
import { BrandMark } from "@/components/Brand";
import type { Profile } from "@/lib/types";

export type AuthModalProps = {
  open: boolean;
  onClose: () => void;
  onAuthSuccess: (profile: Profile | null) => void;
};

function EyeIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
      <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
      <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
      <line x1="2" x2="22" y1="2" y2="22" />
    </svg>
  );
}

type AuthMode = "signin" | "signup" | "forgot_password" | "verify_reset_otp";

export function AuthModal({ open, onClose, onAuthSuccess }: AuthModalProps) {
  const [mode, setMode] = useState<AuthMode>("signup");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [marketingOptIn, setMarketingOptIn] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState<{ email: boolean; password: boolean }>({ email: false, password: false });
  const [termsShake, setTermsShake] = useState(false);

  // Password visibility toggles
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [showResetPassword, setShowResetPassword] = useState(false);
  const [showConfirmResetPassword, setShowConfirmResetPassword] = useState(false);

  // OTP verification state
  const [verifyScreen, setVerifyScreen] = useState(false);
  const [otpCode, setOtpCode] = useState("");
  const [pendingEmail, setPendingEmail] = useState("");
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  const passwordValid = password.length >= 6;
  const showEmailError = touched.email && !emailValid;
  const showPasswordError = touched.password && !passwordValid;

  const canSubmit =
    emailValid &&
    passwordValid &&
    (mode === "signin" || (fullName.trim() !== "" && termsAccepted && confirmPassword.trim().length > 0));

  // Forgot password mode only needs a valid email
  const canSendResetCode = emailValid;

  // Reset OTP mode needs code + matching passwords
  const canResetPassword =
    otpCode.trim().length === 6 &&
    password.length >= 6 &&
    password === confirmPassword;

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

    if (!supabase) { setError("Authentication is not configured."); return; }

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
            "This sign-in option isn't available yet. Please continue with email and password.",
          );
        } else {
          setError(sbError.message);
        }
      }
    } catch {
      setError(
        "This sign-in option isn't available yet. Please continue with email and password.",
      );
    }
  };

  const handleSubmit = async () => {
    setTouched({ email: true, password: true });
    if (!emailValid || !passwordValid) return;
    if (mode === "signup" && !termsAccepted) {
      triggerTermsShake();
      return;
    }

    // Client-side password validation for signup
    if (mode === "signup") {
      if (password.length < 6) {
        setError("Password must be at least 6 characters long.");
        return;
      }
      if (password !== confirmPassword) {
        setError("Passwords do not match. Please check and try again.");
        return;
      }
    }

    setSubmitting(true);
    setError(null);
    try {
      if (!supabase) { setError("Authentication is not configured."); return; }

      if (mode === "signup") {
        let signUpData: { user?: { id?: string; email_confirmed_at?: string | null } | null; session?: { access_token?: string } | null } | null = null;
        let signUpError: Error | null = null;
        try {
          const { data, error: authError } = await supabase.auth.signUp({
            email: email.trim(),
            password,
            options: {
              data: { full_name: fullName.trim() },
              emailRedirectTo: `${window.location.origin}/auth/callback`,
            },
          });
          if (authError) {
            console.error("[AuthModal] signUp returned error:", authError);
            signUpError = authError;
          } else {
            signUpData = data;
          }
        } catch (signUpErr) {
          console.error("[AuthModal] signUp threw:", signUpErr);
          signUpError = signUpErr as Error;
        }

        // If signUp succeeded but no session was returned, Supabase requires
        // email confirmation — transition to the OTP verification screen.
        if (!signUpError && signUpData?.user && !signUpData.session && !signUpData.user.email_confirmed_at) {
          setPendingEmail(email.trim());
          setVerifyScreen(true);
          setSubmitting(false);
          return;
        }

        // Set the auth token for API calls if a session was returned
        if (signUpData?.session?.access_token) {
          setAuthToken(signUpData.session.access_token);
        }

        if (signUpData?.session?.access_token) {
          try {
            const created = await api.createProfile({ full_name: fullName.trim() || undefined, email: email.trim(), terms_accepted: true, privacy_accepted: true, marketing_opt_in: marketingOptIn });
            try { localStorage.setItem("grantrx_profile", JSON.stringify(created)); } catch {}
            onAuthSuccess(created);
          } catch { onAuthSuccess(null); }
        } else { onAuthSuccess(null); }
      } else {
        const { data, error: authError } =
          await supabase.auth.signInWithPassword({ email, password });
        if (authError) {
          setError(authError.message);
          setSubmitting(false);
          return;
        }

        if (data.session?.access_token) {
          setAuthToken(data.session.access_token);
        }

        // Advance user — profile will be loaded from Supabase or localStorage
        onAuthSuccess(null);
      }
    } catch (err: unknown) {
      console.error("[AuthModal Catch] Detailed error object:", err);
      const e = err instanceof Error ? err : null;
      setError(e?.message || "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleVerifyOtp = async () => {
    if (otpCode.trim().length !== 6) {
      setError("Please enter the 6-digit verification code.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      if (!supabase) { setError("Authentication is not configured."); return; }
      const { data, error: verifyError } = await supabase.auth.verifyOtp({
        email: pendingEmail,
        token: otpCode.trim(),
        type: "signup",
      });
      if (verifyError) {
        setError(verifyError.message);
        setSubmitting(false);
        return;
      }

      // Set the auth token if a session was created
      if (data.session?.access_token) {
        setAuthToken(data.session.access_token);
      }

      let createdProfile: Profile | null = null;
      try {
        createdProfile = await api.createProfile({ full_name: fullName.trim() || undefined, email: pendingEmail, terms_accepted: true, privacy_accepted: true, marketing_opt_in: marketingOptIn });
        try { localStorage.setItem("grantrx_profile", JSON.stringify(createdProfile)); } catch {}
      } catch {}

      setVerifyScreen(false);
      onAuthSuccess(createdProfile);
    } catch (err: unknown) {
      console.error("[AuthModal] OTP verification error:", err);
      setError(
        err instanceof Error && err.message
          ? err.message
          : "Verification failed. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  // Forgot Password — send recovery code to email
  const handleSendResetCode = async () => {
    if (!emailValid) {
      setError("Please enter a valid email address.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      if (!supabase) { setError("Authentication is not configured."); return; }
      const { error: resetErr } = await supabase.auth.resetPasswordForEmail(
        email.trim(),
      );
      if (resetErr) {
        setError(resetErr.message);
        return;
      }
      setSuccess("Recovery code sent to " + email.trim());
      setMode("verify_reset_otp");
    } catch (err: unknown) {
      setError(
        err instanceof Error && err.message
          ? err.message
          : "Failed to send reset code. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  // Verify recovery OTP and update password
  const handleVerifyResetOtp = async () => {
    if (otpCode.trim().length !== 6) {
      setError("Please enter the 6-digit recovery code.");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters long.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match. Please check and try again.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      if (!supabase) { setError("Authentication is not configured."); return; }
      // 1. Verify the recovery OTP to establish recovery session
      const { data, error: verifyErr } = await supabase.auth.verifyOtp({
        email: email.trim(),
        token: otpCode.trim(),
        type: "recovery",
      });
      if (verifyErr) throw verifyErr;

      // 2. Update user password
      const { error: updateErr } = await supabase.auth.updateUser({
        password,
      });
      if (updateErr) throw updateErr;

      // Set auth token if a session was established
      if (data.session?.access_token) {
        setAuthToken(data.session.access_token);
      }

      // 3. Complete and log in
      setSuccess("Password updated successfully! Signing you in...");
      setTimeout(() => {
        onAuthSuccess(null);
      }, 1200);
    } catch (err: unknown) {
      console.error("[AuthModal] Password reset error:", err);
      setError(
        err instanceof Error && err.message
          ? err.message
          : "Password reset failed. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-text/40 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative mx-auto w-[calc(100%-2rem)] max-w-md max-h-[90dvh] overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl sm:w-full sm:p-8"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Sign in or create account"
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-textMuted hover:text-text transition"
          aria-label="Close"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {/* OTP Verification Screen (signup) */}
        {verifyScreen ? (
          <div className="text-center">
            <div className="mb-4 pr-6">
              <h2 className="font-serif text-xl font-bold text-text">
                Verify Your Email
              </h2>
              <p className="mt-1 text-sm text-textMuted">
                We sent a 6-digit code to{" "}
                <span className="font-medium text-text">{pendingEmail}</span>.
                Enter it below to complete your registration.
              </p>
            </div>

            {error && (
              <div className="mb-3 rounded-xl bg-dangerSoft px-4 py-2.5 text-sm text-danger">
                {error}
              </div>
            )}
            {success && (
              <div className="mb-3 rounded-xl bg-accentSoft/20 px-4 py-2.5 text-sm text-text">
                {success}
              </div>
            )}

            <form
              className="space-y-4"
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                handleVerifyOtp();
              }}
            >
              <input
                type="text"
                value={otpCode}
                onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="123456"
                maxLength={6}
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                className="w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-3 text-center text-2xl font-bold tracking-[0.5em] text-text focus:border-primary"
              />
              <button
                type="submit"
                disabled={submitting || otpCode.length !== 6}
                className="w-full rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface disabled:opacity-40"
              >
                {submitting ? "Verifying…" : "Verify Code"}
              </button>
              <div className="flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => {
                    setVerifyScreen(false);
                    setOtpCode("");
                    setError(null);
                  }}
                  className="text-xs text-textMuted hover:text-text"
                >
                  Back to sign up
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      if (!supabase) { setError("Authentication is not configured."); return; }
                      const { error: resendErr } = await supabase.auth.resend({
                        type: "signup",
                        email: pendingEmail,
                      });
                      if (resendErr) {
                        setError(resendErr.message);
                      } else {
                        setSuccess("Verification code resent to " + pendingEmail);
                        setError(null);
                      }
                    } catch {
                      setError("Failed to resend code. Please try again.");
                    }
                  }}
                  className="text-xs text-primary hover:underline"
                >
                  Resend code
                </button>
              </div>
            </form>
          </div>
        ) : mode === "forgot_password" ? (
          <div className="text-center">
            <div className="mb-4 pr-6">
              <h2 className="font-serif text-xl font-bold text-text">
                Reset Your Password
              </h2>
              <p className="mt-1 text-sm text-textMuted">
                Enter your registered email address and we will send you a
                6-digit recovery code.
              </p>
            </div>

            {error && (
              <div className="mb-3 rounded-xl bg-dangerSoft px-4 py-2.5 text-sm text-danger">
                {error}
              </div>
            )}
            {success && (
              <div className="mb-3 rounded-xl bg-accentSoft/20 px-4 py-2.5 text-sm text-text">
                {success}
              </div>
            )}

            <form
              className="space-y-4 text-left"
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                handleSendResetCode();
              }}
            >
              <div>
                <label className="block text-sm font-medium text-textMuted">
                  Email Address
                </label>
                <input
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onBlur={() => setTouched((t) => ({ ...t, email: true }))}
                  type="email"
                  placeholder="jane@example.com"
                  autoFocus
                  className={`mt-1 w-full rounded-xl border bg-surface px-4 py-2 text-text transition ${
                    showEmailError
                      ? "border-danger ring-1 ring-danger/30"
                      : "border-textMuted/20 focus:border-primary"
                  }`}
                />
                {showEmailError && (
                  <p className="mt-1 text-xs text-danger">
                    Please enter a valid email address.
                  </p>
                )}
              </div>

              <button
                type="submit"
                disabled={!canSendResetCode || submitting}
                className="w-full rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface disabled:opacity-40"
              >
                {submitting ? "Sending…" : "Send Reset Code"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setMode("signin");
                  setError(null);
                  setSuccess(null);
                }}
                className="w-full text-xs text-textMuted hover:text-text"
              >
                Back to Sign In
              </button>
            </form>
          </div>
        ) : mode === "verify_reset_otp" ? (
          <div className="text-center">
            <div className="mb-4 pr-6">
              <h2 className="font-serif text-xl font-bold text-text">
                Enter Recovery Code
              </h2>
              <p className="mt-1 text-sm text-textMuted">
                Enter the 6-digit code sent to{" "}
                <span className="font-medium text-text">{email}</span>{" "}
                and choose your new password.
              </p>
            </div>

            {error && (
              <div className="mb-3 rounded-xl bg-dangerSoft px-4 py-2.5 text-sm text-danger">
                {error}
              </div>
            )}
            {success && (
              <div className="mb-3 rounded-xl bg-accentSoft/20 px-4 py-2.5 text-sm text-text">
                {success}
              </div>
            )}

            <form
              className="space-y-4 text-left"
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                handleVerifyResetOtp();
              }}
            >
              <div>
                <label className="block text-xs font-semibold text-text mb-1">
                  Recovery Code
                </label>
                <input
                  type="text"
                  autoFocus
                  value={otpCode}
                  onChange={(e) =>
                    setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                  }
                  placeholder="123456"
                  maxLength={6}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  className="w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-3 text-center text-2xl font-bold tracking-[0.5em] text-text focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-text mb-1">
                  New Password
                </label>
                <div className="relative">
                  <input
                    type={showResetPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="At least 6 characters"
                    className="w-full rounded-xl border border-border pl-3.5 pr-10 py-2.5 text-sm text-text placeholder:text-textMuted/50 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all font-sans tracking-normal"
                  />
                  <button
                    type="button"
                    onClick={() => setShowResetPassword(!showResetPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-textMuted hover:text-text focus:outline-none p-1"
                    aria-label={showResetPassword ? "Hide password" : "Show password"}
                  >
                    {showResetPassword ? <EyeOffIcon /> : <EyeIcon />}
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-text mb-1">
                  Confirm New Password
                </label>
                <div className="relative">
                  <input
                    type={showConfirmResetPassword ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => {
                      setConfirmPassword(e.target.value);
                      if (error && error.includes("match")) setError(null);
                    }}
                    placeholder="Re-enter your new password"
                    className="w-full rounded-xl border border-border pl-3.5 pr-10 py-2.5 text-sm text-text placeholder:text-textMuted/50 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all font-sans tracking-normal"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmResetPassword(!showConfirmResetPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-textMuted hover:text-text focus:outline-none p-1"
                    aria-label={showConfirmResetPassword ? "Hide password" : "Show password"}
                  >
                    {showConfirmResetPassword ? <EyeOffIcon /> : <EyeIcon />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={!canResetPassword || submitting}
                className="w-full rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface disabled:opacity-40"
              >
                {submitting ? "Updating…" : "Update Password"}
              </button>

              <div className="flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => {
                    setMode("signin");
                    setOtpCode("");
                    setPassword("");
                    setConfirmPassword("");
                    setError(null);
                    setSuccess(null);
                  }}
                  className="text-xs text-textMuted hover:text-text"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      if (!supabase) { setError("Authentication is not configured."); return; }
                      const { error: resendErr } =
                        await supabase.auth.resetPasswordForEmail(email.trim());
                      if (resendErr) {
                        setError(resendErr.message);
                      } else {
                        setSuccess("Recovery code resent to " + email.trim());
                        setError(null);
                      }
                    } catch {
                      setError("Failed to resend code. Please try again.");
                    }
                  }}
                  className="text-xs text-primary hover:underline"
                >
                  Resend code
                </button>
              </div>
            </form>
          </div>
        ) : (
          <div>
        {/* Header */}
        <div className="mb-4 text-center pr-6">
          <div className="mb-3 flex justify-center">
            <BrandMark />
          </div>
          <h2 className="font-serif text-xl font-bold text-text">
            {mode === "signup" ? "Create your account" : "Welcome back"}
          </h2>
          <p className="mt-1 text-sm text-textMuted">
            {mode === "signup"
              ? "Sign up to find matched funding opportunities"
              : "Sign in to your EdFintia account"}
          </p>
        </div>

        {/* Mode toggle */}
        <div className="mb-4 flex rounded-full bg-textMuted/10 p-1">
          <button
            type="button"
            onClick={() => { setMode("signup"); setConfirmPassword(""); setError(null); }}
            className={`flex-1 rounded-full px-4 py-1.5 text-sm font-medium transition ${
              mode === "signup"
                ? "bg-primary text-surface"
                : "text-textMuted"
            }`}
          >
            Sign Up
          </button>
          <button
            type="button"
            onClick={() => { setMode("signin"); setConfirmPassword(""); setError(null); }}
            className={`flex-1 rounded-full px-4 py-1.5 text-sm font-medium transition ${
              mode === "signin"
                ? "bg-primary text-surface"
                : "text-textMuted"
            }`}
          >
            Sign In
          </button>
        </div>

        {error && (
          <div className="mb-3 rounded-xl bg-dangerSoft px-4 py-2.5 text-sm text-danger">
            {error}
          </div>
        )}

        {/* OAuth provider buttons */}
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => handleOAuth("google")}
            className="flex w-full items-center justify-center gap-3 rounded-xl border border-border bg-white px-4 py-2 text-sm font-medium text-text shadow-sm transition hover:bg-surfaceSubtle hover:border-border"
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
            className="flex w-full items-center justify-center gap-3 rounded-xl border border-border bg-white px-4 py-2 text-sm font-medium text-text shadow-sm transition hover:bg-surfaceSubtle hover:border-border"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="#0A66C2" aria-hidden="true">
              <path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.34V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.12 2.06 2.06 0 0 1 0 4.12zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.72V1.72C24 .77 23.2 0 22.22 0z" />
            </svg>
            Continue with LinkedIn
          </button>
        </div>

        {/* Divider */}
        <div className="my-4 flex items-center gap-3">
          <div className="h-px flex-1 bg-border" />
          <span className="text-xs font-medium text-textMuted">or</span>
          <div className="h-px flex-1 bg-border" />
        </div>

        {/* Form */}
        <form
          className="space-y-3"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
        >
          {mode === "signup" && (
            <div>
              <label className="block text-sm font-medium text-textMuted">
                Full Name
              </label>
              <input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Jane Doe"
                autoFocus
                className="mt-1 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2 text-text"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-textMuted">
              Email
            </label>
            <input
              autoFocus={mode === "signin"}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => setTouched((t) => ({ ...t, email: true }))}
              type="email"
              placeholder="jane@example.com"
              className={`mt-1 w-full rounded-xl border bg-surface px-4 py-2 text-text transition ${
                showEmailError
                  ? "border-danger ring-1 ring-danger/30"
                  : "border-textMuted/20 focus:border-primary"
              }`}
            />
            {showEmailError && (
              <p className="mt-1 text-xs text-danger">Please enter a valid email address.</p>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-semibold text-text mb-1">
                Password
              </label>
              {mode === "signin" && (
                <button
                  type="button"
                  onClick={() => { setMode("forgot_password"); setError(null); setSuccess(null); }}
                  className="text-xs font-semibold text-primary hover:text-primaryHover"
                >
                  Forgot password?
                </button>
              )}
            </div>
            <div className="relative">
              <input
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onBlur={() => setTouched((t) => ({ ...t, password: true }))}
                type={showPassword ? "text" : "password"}
                placeholder="At least 6 characters"
                className={`w-full rounded-xl border pl-3.5 pr-10 py-2.5 text-sm text-text placeholder:text-textMuted/50 focus:outline-none focus:ring-2 transition-all font-sans tracking-normal ${
                  showPasswordError
                    ? "border-danger ring-1 ring-danger/30 focus:ring-danger/20"
                    : "border-border focus:border-primary focus:ring-primary/20"
                }`}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-textMuted hover:text-text focus:outline-none p-1"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOffIcon /> : <EyeIcon />}
              </button>
            </div>
            {showPasswordError && (
              <p className="mt-1 text-xs text-danger">Password must be at least 6 characters.</p>
            )}
          </div>

          {mode === "signup" && (
            <div>
              <label className="block text-xs font-semibold text-text mb-1">
                Confirm Password
              </label>
              <div className="relative">
                <input
                  type={showConfirmPassword ? "text" : "password"}
                  value={confirmPassword}
                  onChange={(e) => {
                    setConfirmPassword(e.target.value);
                    if (error && error.includes("match")) setError(null);
                  }}
                  placeholder="Re-enter your password"
                  required
                  className="w-full rounded-xl border border-border pl-3.5 pr-10 py-2.5 text-sm text-text placeholder:text-textMuted/50 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all font-sans tracking-normal"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-textMuted hover:text-text focus:outline-none p-1"
                  aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                >
                  {showConfirmPassword ? <EyeOffIcon /> : <EyeIcon />}
                </button>
              </div>
            </div>
          )}

          {mode === "signup" && (
            <div className="space-y-2.5 pt-1">
              {/* Terms & Privacy — mandatory */}
              <label
                className={`flex items-start gap-2 text-xs text-textMuted leading-tight ${termsShake ? "animate-shake" : ""}`}
                style={termsShake ? { animation: "shake 0.4s ease-in-out" } : undefined}
              >
                <input
                  type="checkbox"
                  checked={termsAccepted}
                  onChange={(e) => setTermsAccepted(e.target.checked)}
                  className={`h-4 w-4 shrink-0 rounded border-border accent-primary focus:ring-primary/30 mt-0.5 ${termsShake ? "ring-2 ring-danger/40" : ""}`}
                />
                <span>
                  I agree to the{" "}
                  <Link
                    href="/terms"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline"
                  >
                    Terms of Service
                  </Link>{" "}
                  and{" "}
                  <Link
                    href="/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline"
                  >
                    Privacy Policy
                  </Link>
                </span>
              </label>

              {/* Marketing opt-in — optional */}
              <label className="flex items-start gap-2 text-xs text-textMuted leading-tight">
                <input
                  type="checkbox"
                  checked={marketingOptIn}
                  onChange={(e) => setMarketingOptIn(e.target.checked)}
                  className="h-4 w-4 shrink-0 rounded border-border accent-primary focus:ring-primary/30 mt-0.5"
                />
                <span>
                  I opt in to receive funding alerts, updates, and email
                  communications from EdFintia, its parent company, and
                  subsidiaries.
                </span>
              </label>
            </div>
          )}

        {/* Actions */}
        <div className="mt-4 flex items-center justify-between">
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-textMuted hover:text-text"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canSubmit || submitting}
            className="rounded-full bg-primary px-6 py-2 text-sm font-medium text-surface disabled:opacity-40"
          >
            {submitting
              ? "Please wait…"
              : mode === "signup"
                ? "Create Account"
                : "Sign In"}
          </button>
        </div>
        </form>
          </div>
        )}
      </div>
    </div>
  );
}

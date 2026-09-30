'use client';

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { trackEvent } from "@/lib/analytics";
import type {
  EarlyAccessAudienceType,
  EarlyAccessEducationType,
  EarlyAccessSignupRequest,
} from "@/lib/types";

const AUDIENCE_OPTIONS: { value: EarlyAccessAudienceType; label: string }[] = [
  { value: "student", label: "Student" },
  { value: "parent", label: "Parent" },
  { value: "college_staff", label: "College Staff" },
  { value: "counselor", label: "Counselor" },
  { value: "scholarship_organization", label: "Scholarship Organization" },
  { value: "other", label: "Other" },
];

const EDUCATION_OPTIONS: { value: EarlyAccessEducationType; label: string }[] = [
  { value: "undergraduate", label: "Undergraduate" },
  { value: "graduate", label: "Graduate" },
  { value: "professional", label: "Professional" },
  { value: "trade", label: "Trade" },
  { value: "other", label: "Other" },
];

type Attribution = Pick<
  EarlyAccessSignupRequest,
  | "referral_source"
  | "referral_code"
  | "referred_by"
  | "utm_source"
  | "utm_medium"
  | "utm_campaign"
  | "utm_content"
  | "utm_term"
  | "landing_page"
>;

/** Read acquisition attribution from the landing URL once, on mount, so it
 * survives the whole waitlist interaction. Channel, referral code, and UTM
 * parameters stay in their own fields — never collapsed together. */
function captureAttribution(): Attribution {
  const params = new URLSearchParams(window.location.search);
  const pick = (...names: string[]): string | null => {
    for (const name of names) {
      const value = params.get(name)?.trim();
      if (value) return value.slice(0, 120);
    }
    return null;
  };
  return {
    referral_source: pick("source", "ref_source", "referral_source"),
    referral_code: pick("ref", "referral", "referral_code", "code"),
    referred_by: pick("referred_by", "by"),
    utm_source: pick("utm_source"),
    utm_medium: pick("utm_medium"),
    utm_campaign: pick("utm_campaign"),
    utm_content: pick("utm_content"),
    utm_term: pick("utm_term"),
    landing_page: window.location.pathname.slice(0, 500),
  };
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

type FieldErrors = {
  first_name?: string;
  email?: string;
  audience_type?: string;
  consent?: string;
};

const inputClass = (invalid: boolean) =>
  `mt-1 w-full rounded-xl border bg-surface px-4 py-2.5 text-sm text-text placeholder:text-textMuted/50 transition focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 ${
    invalid ? "border-danger ring-1 ring-danger/30" : "border-border"
  }`;

export function EarlyAccessForm() {
  const [firstName, setFirstName] = useState("");
  const [email, setEmail] = useState("");
  const [audienceType, setAudienceType] = useState<EarlyAccessAudienceType | "">("");
  const [educationType, setEducationType] = useState<EarlyAccessEducationType | "">("");
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [status, setStatus] = useState<"idle" | "submitting" | "success">("idle");
  const [successMessage, setSuccessMessage] = useState("");
  const [serverError, setServerError] = useState<string | null>(null);

  // Attribution is captured once on mount (from the landing URL) and kept in
  // a ref so it is preserved through the whole waitlist interaction.
  const attributionRef = useRef<Attribution | null>(null);
  useEffect(() => {
    attributionRef.current = captureAttribution();
    trackEvent("early_access_view");
  }, []);

  const validate = (): FieldErrors => {
    const next: FieldErrors = {};
    if (!firstName.trim()) next.first_name = "Please enter your first name.";
    if (!EMAIL_RE.test(email.trim().toLowerCase()))
      next.email = "Please enter a valid email address.";
    if (!audienceType) next.audience_type = "Please choose the option that fits you best.";
    if (!consent)
      next.consent = "Please confirm you'd like to join the early-access list.";
    return next;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (status === "submitting") return;

    const nextErrors = validate();
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setStatus("submitting");
    setServerError(null);
    trackEvent("early_access_submit");

    const payload: EarlyAccessSignupRequest = {
      first_name: firstName.trim(),
      email: email.trim().toLowerCase(),
      audience_type: audienceType as EarlyAccessAudienceType,
      education_type: educationType || null,
      consent: true,
      consent_source: "early_access_form",
      ...(attributionRef.current ?? {}),
    };

    try {
      const result = await api.submitEarlyAccess(payload);
      trackEvent("early_access_success");
      setSuccessMessage(
        result.message ||
          "You're on the early-access list — watch your inbox for updates.",
      );
      setStatus("success");
    } catch (err) {
      const e = err as Error & { status?: number };
      console.error("Early-access signup failed:", err);
      setServerError(
        e.status === 429
          ? "Too many attempts — please wait a few minutes and try again."
          : "Something went wrong on our end. Please try again in a moment.",
      );
      setStatus("idle");
    }
  };

  if (status === "success") {
    return (
      <div
        className="rounded-2xl border border-success/30 bg-successSoft p-6 sm:p-8 text-center"
        role="status"
        aria-live="polite"
      >
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-success/15" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6 text-success" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 6L9 17l-5-5" />
          </svg>
        </div>
        <h2 className="mt-4 font-serif text-2xl font-bold text-text">
          You&rsquo;re on the list
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-textMuted">
          {successMessage}
        </p>
        <p className="mt-4 text-xs text-textMuted">
          We&rsquo;ll email you when early access opens.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="text-left">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="ea-first-name" className="block text-sm font-medium text-text">
            First name <span aria-hidden="true" className="text-danger">*</span>
          </label>
          <input
            id="ea-first-name"
            name="first_name"
            type="text"
            autoComplete="given-name"
            required
            maxLength={80}
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            aria-invalid={!!errors.first_name}
            aria-describedby={errors.first_name ? "ea-first-name-error" : undefined}
            className={inputClass(!!errors.first_name)}
          />
          {errors.first_name && (
            <p id="ea-first-name-error" className="mt-1 text-xs text-danger" role="alert">
              {errors.first_name}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="ea-email" className="block text-sm font-medium text-text">
            Email <span aria-hidden="true" className="text-danger">*</span>
          </label>
          <input
            id="ea-email"
            name="email"
            type="email"
            autoComplete="email"
            required
            maxLength={254}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? "ea-email-error" : undefined}
            className={inputClass(!!errors.email)}
          />
          {errors.email && (
            <p id="ea-email-error" className="mt-1 text-xs text-danger" role="alert">
              {errors.email}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="ea-audience" className="block text-sm font-medium text-text">
            I am a&hellip; <span aria-hidden="true" className="text-danger">*</span>
          </label>
          <select
            id="ea-audience"
            name="audience_type"
            required
            value={audienceType}
            onChange={(e) => setAudienceType(e.target.value as EarlyAccessAudienceType)}
            aria-invalid={!!errors.audience_type}
            aria-describedby={errors.audience_type ? "ea-audience-error" : undefined}
            className={inputClass(!!errors.audience_type)}
          >
            <option value="" disabled>
              Select one
            </option>
            {AUDIENCE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          {errors.audience_type && (
            <p id="ea-audience-error" className="mt-1 text-xs text-danger" role="alert">
              {errors.audience_type}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="ea-education" className="block text-sm font-medium text-text">
            Education path <span className="font-normal text-textMuted">(optional)</span>
          </label>
          <select
            id="ea-education"
            name="education_type"
            value={educationType}
            onChange={(e) => setEducationType(e.target.value as EarlyAccessEducationType)}
            className={inputClass(false)}
          >
            <option value="">Prefer not to say</option>
            {EDUCATION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-5">
        <div className="flex items-start gap-3">
          <input
            id="ea-consent"
            name="consent"
            type="checkbox"
            required
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            aria-invalid={!!errors.consent}
            aria-describedby="ea-consent-desc"
            className="mt-0.5 h-4 w-4 shrink-0 rounded border-border text-primary accent-primary focus:ring-2 focus:ring-primary/30"
          />
          <label htmlFor="ea-consent" className="text-sm leading-relaxed text-textMuted">
            <span id="ea-consent-desc">
              Yes — email me when EdFintia early access opens and send
              occasional product updates. I can unsubscribe anytime.{" "}
            </span>
            <Link href="/privacy" className="text-primary underline underline-offset-2 hover:text-primaryHover">
              Privacy Policy
            </Link>
            {" · "}
            <Link href="/terms" className="text-primary underline underline-offset-2 hover:text-primaryHover">
              Terms
            </Link>
          </label>
        </div>
        {errors.consent && (
          <p className="mt-1 text-xs text-danger" role="alert">
            {errors.consent}
          </p>
        )}
      </div>

      {serverError && (
        <div className="mt-4 rounded-xl border border-danger/30 bg-dangerSoft px-4 py-3 text-sm text-danger" role="alert">
          {serverError}
        </div>
      )}

      <button
        type="submit"
        disabled={status === "submitting"}
        className="mt-5 w-full rounded-full bg-primary px-6 py-3 text-sm font-semibold text-surface shadow-sm transition hover:bg-primaryHover disabled:opacity-50"
      >
        {status === "submitting" ? "Joining…" : "Get early access"}
      </button>
      <p className="mt-3 text-center text-xs leading-relaxed text-textMuted">
        No spam — just launch updates. Unsubscribe anytime.
      </p>
    </form>
  );
}

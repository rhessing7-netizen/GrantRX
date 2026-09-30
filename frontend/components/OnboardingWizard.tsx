"use client";

import { useEffect, useRef, useState } from "react";
import {
  AFFILIATION_OPTIONS,
  CREDENTIAL_OPTIONS,
  type MatchPreview,
  type Profile,
  type ProfileCreate,
} from "@/lib/types";
import { getMetrosForState } from "@/lib/constants/metros";
import { MAJOR_CATEGORIES, mapMajorToClinicalDiscipline } from "@/lib/constants/disciplines";
import { levelForCredential, type DegreeLevel } from "@/lib/constants/credentials";
import { api } from "@/lib/api";
import { MultiSelect } from "./MultiSelect";
import { GroupedMultiSelect } from "./GroupedMultiSelect";
import { CascadingCredentialSelect } from "./CascadingCredentialSelect";

const STEPS = ["Fields of Study", "Academic Details", "Background & Interests"];

export type OnboardingWizardProps = {
  onComplete: (profile: Profile) => void;
  onCancel?: () => void;
  existingProfile?: Profile | null;
};

export function OnboardingWizard({ onComplete, onCancel, existingProfile }: OnboardingWizardProps) {
  useEffect(() => {
    if (!onCancel) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step 1 — multi-select disciplines and cascading credentials (all optional)
  const [disciplines, setDisciplines] = useState<string[]>(
    existingProfile?.disciplines ?? [],
  );
  const [credentials, setCredentials] = useState<string[]>(
    existingProfile?.target_credentials ?? [],
  );

  // Cascading credential selection — reverse-map a previously saved
  // credential to its degree level so the select restores the full path
  // instead of hiding (and potentially erasing) the saved value.
  const [degreeLevel, setDegreeLevel] = useState<DegreeLevel | "">(
    existingProfile?.target_credential
      ? levelForCredential(existingProfile.target_credential)
      : "",
  );
  const [selectedCredential, setSelectedCredential] = useState(
    existingProfile?.target_credential ?? "",
  );

  // Step 2 — academic details (all optional)
  const [clinicalPhase, setClinicalPhase] = useState(existingProfile?.clinical_phase ?? "");
  const [gpa, setGpa] = useState(
    existingProfile?.gpa != null ? String(existingProfile.gpa) : "",
  );
  const [stateResidence, setStateResidence] = useState(existingProfile?.state_residence ?? "");
  const [metroArea, setMetroArea] = useState(existingProfile?.metro_area ?? "");
  const [saiScore, setSaiScore] = useState(
    existingProfile?.sai_score != null ? String(existingProfile.sai_score) : "",
  );

  // Step 3 — background & interests (all optional)
  const [firstGen, setFirstGen] = useState(existingProfile?.first_gen ?? false);
  const [minorityFlag, setMinorityFlag] = useState(existingProfile?.minority_flag ?? false);
  const [affiliations, setAffiliations] = useState<string[]>(
    existingProfile?.professional_affiliations ?? [],
  );
  const [hobbies, setHobbies] = useState(
    (existingProfile?.hobbies ?? []).join(", "),
  );

  // Live matching projection — debounced preview of how many opportunities
  // the user's current onboarding answers would surface.
  const [projection, setProjection] = useState<MatchPreview | null>(null);
  const [projectionLoading, setProjectionLoading] = useState(false);
  const previewAbort = useRef<AbortController | null>(null);

  // ALL steps are optional — canNext always returns true
  const canNext = () => true;

  const toggleAffiliation = (a: string) => {
    setAffiliations((prev) =>
      prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a],
    );
  };

  const buildPayload = (): ProfileCreate => {
    // Stable-order dedup: the cascading credential may already be present in
    // the multi-select list after a previous save.
    const allCredentials = [
      ...new Set(
        selectedCredential ? [...credentials, selectedCredential] : credentials,
      ),
    ];
    // Explicit nulls let the upsert clear previously-set optional fields;
    // omission would be indistinguishable from "leave unchanged".
    const payload: ProfileCreate = {
      disciplines,
      target_credentials: allCredentials,
      first_gen: firstGen,
      minority_flag: minorityFlag,
      professional_affiliations: affiliations,
      hobbies: hobbies
        .split(",")
        .map((h) => h.trim())
        .filter(Boolean),
      // Map the first selected major to primary_discipline for backend matching
      primary_discipline:
        disciplines.length > 0
          ? mapMajorToClinicalDiscipline(disciplines[0])
          : null,
      target_credential: selectedCredential || null,
      clinical_phase: clinicalPhase || null,
      gpa: gpa ? parseFloat(gpa) : null,
      state_residence: stateResidence ? stateResidence.toUpperCase() : null,
      metro_area: metroArea || null,
      sai_score: saiScore ? parseInt(saiScore, 10) : null,
    };
    return payload;
  };

  const hasEnoughInfo =
    disciplines.length > 0 || credentials.length > 0 || !!selectedCredential;

  useEffect(() => {
    // Only run the preview once the user has selected at least one discipline
    // or credential — otherwise the projection is meaningless.
    if (!hasEnoughInfo) return;
    // Debounce: wait 400ms after the last change before firing.
    const handle = setTimeout(() => {
      previewAbort.current?.abort();
      const controller = new AbortController();
      previewAbort.current = controller;
      setProjectionLoading(true);
      const payload = buildPayload();
      api
        .previewMatchCount(payload, controller.signal)
        .then((res) => {
          if (!controller.signal.aborted) setProjection(res);
        })
        .catch(() => {
          // Silent — onboarding must never block on a preview failure.
          if (!controller.signal.aborted) setProjection(null);
        })
        .finally(() => {
          if (!controller.signal.aborted) setProjectionLoading(false);
        });
    }, 400);
    return () => {
      clearTimeout(handle);
      previewAbort.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- buildPayload is a stable closure over state setters
  }, [
    hasEnoughInfo,
    disciplines,
    credentials,
    selectedCredential,
    clinicalPhase,
    gpa,
    stateResidence,
    metroArea,
    saiScore,
    firstGen,
    minorityFlag,
    affiliations,
    hobbies,
  ]);

  // Clear the projection when there's not enough info to project.
  // Derived in render to avoid setState-in-effect.
  const displayedProjection = hasEnoughInfo ? projection : null;
  const displayedLoading = hasEnoughInfo && projectionLoading;

  /** Persist through the backend only; localStorage is only a cache. */
  const persistProfile = async (payload: ProfileCreate): Promise<Profile> => {
    const savedProfile = await api.createProfile(payload);
    try { localStorage.setItem("grantrx_profile", JSON.stringify(savedProfile)); } catch {}
    return savedProfile;
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const profile = await persistProfile(buildPayload());
      onComplete(profile);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setSubmitting(false);
    }
  };

  // Skip: create a profile with zero fields selected (unrestricted search)
  const handleSkip = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const payload: ProfileCreate = {
        disciplines: [],
        target_credentials: [],
        first_gen: false,
        minority_flag: false,
        professional_affiliations: [],
        hobbies: [],
      };
      const profile = await persistProfile(payload);
      onComplete(profile);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-text/40 p-4 backdrop-blur-sm">
      <div
        className="mx-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-2xl bg-surface p-6 shadow-2xl sm:w-full sm:rounded-3xl sm:p-8"
        role="dialog"
        aria-modal="true"
        aria-label="Set up your profile"
      >
        {/* Intro — orients first-time users before any field appears */}
        <div className="mb-5 text-center">
          <h2 className="font-serif text-xl font-bold text-text">
            Build your Funding Profile
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-textMuted">
            Tell us what you&apos;re studying so we can match you with
            scholarships, grants, and other aid. Everything is optional and
            you can change it later.
          </p>
        </div>

        {/* Progress */}
        <div className="mb-6 flex items-center gap-2">
          {STEPS.map((label, i) => (
            <div key={label} className="flex-1">
              <div
                className={`h-1.5 rounded-full ${i <= step ? "bg-primary" : "bg-textMuted/15"}`}
              />
              <p className="mt-1.5 text-xs text-textMuted">{label}</p>
            </div>
          ))}
        </div>

        {error && (
          <div className="mb-4 flex items-start gap-3 rounded-xl border border-danger/30 bg-dangerSoft px-4 py-3">
            <svg className="mt-0.5 h-5 w-5 shrink-0 text-danger" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
            </svg>
            <div className="flex-1">
              <p className="text-sm font-medium text-danger">Could not save profile</p>
              <p className="mt-0.5 text-xs text-danger">{error}</p>
            </div>
            <button
              onClick={() => setError(null)}
              className="shrink-0 text-danger hover:text-danger"
              aria-label="Dismiss"
            >
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
              </svg>
            </button>
          </div>
        )}

        {/* Step 1 — Fields of Study (multi-select, all optional) */}
        {step === 0 && (
          <div className="space-y-5">
            <div>
              <GroupedMultiSelect
                label="Majors / Fields of Study (optional — select all that apply)"
                categories={MAJOR_CATEGORIES}
                selected={disciplines}
                onChange={setDisciplines}
                placeholder="Search and select your major…"
                maxHeight={320}
              />
            </div>

            <div>
              <CascadingCredentialSelect
                label="Degree Level & Credential (optional)"
                selectedLevel={degreeLevel}
                selectedCredential={selectedCredential}
                onLevelChange={setDegreeLevel}
                onCredentialChange={setSelectedCredential}
              />
            </div>

            {/* Additional multi-select credentials for users with multiple degrees */}
            <div>
              <MultiSelect
                label="Additional Credentials (optional — select all that apply)"
                options={CREDENTIAL_OPTIONS}
                selected={credentials}
                onChange={setCredentials}
                placeholder="Select additional credentials…"
                maxHeight={200}
              />
            </div>

            {/* Skip button — prominent on screen 1 */}
            <div className="rounded-xl bg-surfaceSubtle p-4 text-center">
              <p className="text-sm text-textMuted">
                No specific field in mind? You can explore all opportunities without selecting anything.
              </p>
              <button
                onClick={handleSkip}
                disabled={submitting}
                className="mt-3 inline-flex items-center gap-2 rounded-full border-2 border-primary px-6 py-2.5 text-sm font-semibold text-primary transition hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting && (
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                )}
                {submitting ? "Setting up…" : "Skip Setup & Explore All Opportunities"}
              </button>
            </div>
          </div>
        )}

        {/* Step 2 — Academic Details (all optional) */}
        {step === 1 && (
          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-textMuted">
                Clinical Phase (optional)
              </label>
              <input
                value={clinicalPhase}
                onChange={(e) => setClinicalPhase(e.target.value)}
                placeholder="e.g. P1, P2, MS3, Pre-Clinical"
                className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
              />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-textMuted">
                  Cumulative GPA (optional)
                </label>
                <input
                  value={gpa}
                  onChange={(e) => setGpa(e.target.value)}
                  type="number"
                  step="0.01"
                  min="0"
                  max="4"
                  placeholder="3.75"
                  className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-textMuted">
                  State of Residence (optional)
                </label>
                <input
                  value={stateResidence}
                  onChange={(e) =>
                    setStateResidence(e.target.value.toUpperCase().slice(0, 2))
                  }
                  placeholder="CA"
                  maxLength={2}
                  className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-textMuted">
                SAI Score (optional)
              </label>
              <input
                value={saiScore}
                onChange={(e) => setSaiScore(e.target.value)}
                type="number"
                placeholder="e.g. 1200"
                className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-textMuted">
                Metropolitan Area (optional)
              </label>
              <select
                value={metroArea}
                onChange={(e) => setMetroArea(e.target.value)}
                className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
              >
                <option value="">Any / Not specified</option>
                {getMetrosForState(stateResidence).map((m) => (
                  <option key={m.slug} value={m.name}>
                    {m.matchesState ? "\u2605 " : ""}{m.shortName} ({m.states.join(", ")})
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-textMuted">
                {stateResidence
                  ? `Metros matching ${stateResidence} are starred and shown first. Selecting a metro area helps match metro-restricted opportunities.`
                  : "Selecting a metro area helps match metro-restricted opportunities."}
              </p>
            </div>
          </div>
        )}

        {/* Step 3 — Background & Interests (all optional) */}
        {step === 2 && (
          <div className="space-y-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:gap-6">
              <label className="flex min-h-[44px] items-center gap-2 text-sm text-text">
                <input
                  type="checkbox"
                  checked={firstGen}
                  onChange={(e) => setFirstGen(e.target.checked)}
                  className="h-4 w-4 accent-primary"
                />
                First-Generation
              </label>
              <label className="flex min-h-[44px] items-center gap-2 text-sm text-text">
                <input
                  type="checkbox"
                  checked={minorityFlag}
                  onChange={(e) => setMinorityFlag(e.target.checked)}
                  className="h-4 w-4 accent-primary"
                />
                Minority / Underrepresented
              </label>
            </div>

            <div>
              <label className="block text-sm font-medium text-textMuted">
                Professional Affiliations (optional)
              </label>
              <div className="mt-2 flex flex-wrap gap-2">
                {AFFILIATION_OPTIONS.map((a) => (
                  <button
                    key={a}
                    type="button"
                    onClick={() => toggleAffiliation(a)}
                    className={`rounded-full px-3 py-1.5 text-sm transition ${
                      affiliations.includes(a)
                        ? "bg-primary text-surface"
                        : "border border-textMuted/20 text-textMuted"
                    }`}
                  >
                    {a}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-textMuted">
                Hobbies / Interests (optional, comma-separated)
              </label>
              <input
                value={hobbies}
                onChange={(e) => setHobbies(e.target.value)}
                placeholder="research, volunteering, music"
                className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
              />
            </div>
          </div>
        )}

        {/* Live matching projection — shows on every step once enough
            info exists to project a match count. */}
        {(displayedProjection || displayedLoading) && (
          <div className="mt-6 flex items-center gap-3 rounded-xl border border-accentSoft/40 bg-accentSoft/10 px-4 py-3">
            <svg
              className="h-5 w-5 shrink-0 text-secondary"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 17l6-6 4 4 3-3" />
            </svg>
            <div className="text-sm">
              {displayedLoading ? (
                <span className="text-textMuted">
                  Estimating your matches…
                </span>
              ) : displayedProjection ? (
                <span className="text-text">
                  <span className="font-bold text-secondary">
                    {displayedProjection.projected_count} opportunit
                    {displayedProjection.projected_count === 1 ? "y" : "ies"}
                  </span>{" "}
                  projected to match your profile
                  {displayedProjection.projected_funding_total > 0 && (
                    <>
                      {" "}·{" "}
                      <span className="font-semibold">
                        ${displayedProjection.projected_funding_total.toLocaleString()}
                      </span>{" "}
                      potential funding
                    </>
                  )}
                </span>
              ) : null}
            </div>
          </div>
        )}

        {/* Navigation */}
        <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
          {onCancel && step === 0 ? (
            <button
              onClick={onCancel}
              className="text-sm text-textMuted hover:text-text"
            >
              Cancel
            </button>
          ) : (
            <button
              onClick={() => setStep((s) => s - 1)}
              disabled={step === 0}
              className="text-sm text-textMuted hover:text-text disabled:opacity-30"
            >
              Back
            </button>
          )}

          {step < STEPS.length - 1 ? (
            <button
              onClick={() => setStep((s) => s + 1)}
              disabled={!canNext()}
              className="rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface disabled:opacity-40"
            >
              Continue
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface transition hover:bg-primaryHover disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting && (
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              )}
              {submitting ? "Saving…" : "Complete Setup"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

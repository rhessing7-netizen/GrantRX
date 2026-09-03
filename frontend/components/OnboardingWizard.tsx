"use client";

import { useState } from "react";
import {
  AFFILIATION_OPTIONS,
  CREDENTIAL_OPTIONS,
  type Profile,
  type ProfileCreate,
} from "@/lib/types";
import { getMetrosForState } from "@/lib/constants/metros";
import { MAJOR_CATEGORIES, mapMajorToClinicalDiscipline } from "@/lib/constants/disciplines";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { MultiSelect } from "./MultiSelect";
import { GroupedMultiSelect } from "./GroupedMultiSelect";

const STEPS = ["Fields of Study", "Academic Details", "Background & Interests"];

export type OnboardingWizardProps = {
  onComplete: (profile: Profile) => void;
  onCancel?: () => void;
  existingProfile?: Profile | null;
};

export function OnboardingWizard({ onComplete, onCancel, existingProfile }: OnboardingWizardProps) {
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step 1 — multi-select disciplines and credentials (all optional)
  const [disciplines, setDisciplines] = useState<string[]>(
    existingProfile?.disciplines ?? [],
  );
  const [credentials, setCredentials] = useState<string[]>(
    existingProfile?.target_credentials ?? [],
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

  // ALL steps are optional — canNext always returns true
  const canNext = () => true;

  const toggleAffiliation = (a: string) => {
    setAffiliations((prev) =>
      prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a],
    );
  };

  const buildPayload = (): ProfileCreate => {
    const payload: ProfileCreate = {
      disciplines,
      target_credentials: credentials,
      first_gen: firstGen,
      minority_flag: minorityFlag,
      professional_affiliations: affiliations,
      hobbies: hobbies
        .split(",")
        .map((h) => h.trim())
        .filter(Boolean),
    };
    // Map the first selected major to primary_discipline for backend matching
    if (disciplines.length > 0) {
      payload.primary_discipline = mapMajorToClinicalDiscipline(disciplines[0]);
    }
    if (clinicalPhase) payload.clinical_phase = clinicalPhase;
    if (gpa) payload.gpa = parseFloat(gpa);
    if (stateResidence) payload.state_residence = stateResidence.toUpperCase();
    if (metroArea) payload.metro_area = metroArea;
    if (saiScore) payload.sai_score = parseInt(saiScore, 10);
    return payload;
  };

  /**
   * Persist the profile via Supabase directly (primary), then fall back to
   * the backend API, then fall back to localStorage so the user is never
   * blocked from reaching the discovery feed.
   */
  const persistProfile = async (
    payload: ProfileCreate,
  ): Promise<Profile> => {
    // --- Attempt 1: Direct Supabase upsert ---
    if (supabase) {
      try {
        const { data: { user } } = await supabase.auth.getUser();
        if (user) {
          const sbPayload = {
            id: user.id,
            user_id: user.id,
            disciplines: payload.disciplines ?? [],
            target_credentials: payload.target_credentials ?? [],
            primary_discipline: payload.primary_discipline ?? null,
            target_credential: payload.target_credential ?? null,
            clinical_phase: payload.clinical_phase ?? null,
            gpa: payload.gpa ?? null,
            state_residence: payload.state_residence ?? null,
            metro_area: payload.metro_area ?? null,
            sai_score: payload.sai_score ?? null,
            first_gen: payload.first_gen ?? false,
            minority_flag: payload.minority_flag ?? false,
            professional_affiliations: payload.professional_affiliations ?? [],
            hobbies: payload.hobbies ?? [],
            updated_at: new Date().toISOString(),
          };

          const { data, error } = await supabase
            .from("profiles")
            .upsert(sbPayload)
            .select()
            .single();

          if (!error && data) {
            return data as unknown as Profile;
          }
          // RLS or table issue — fall through to API attempt
        }
      } catch {
        // Supabase call failed — fall through to API attempt
      }
    }

    // --- Attempt 2: Backend API ---
    try {
      const profile = await api.createProfile(payload);
      return profile;
    } catch {
      // API unreachable — fall through to localStorage
    }

    // --- Attempt 3: localStorage fallback ---
    const localProfile: Profile = {
      id: "local-profile",
      disciplines: payload.disciplines ?? [],
      target_credentials: payload.target_credentials ?? [],
      primary_discipline: payload.primary_discipline ?? null,
      target_credential: payload.target_credential ?? null,
      clinical_phase: payload.clinical_phase ?? null,
      gpa: payload.gpa ?? null,
      state_residence: payload.state_residence ?? null,
      metro_area: payload.metro_area ?? null,
      sai_score: payload.sai_score ?? null,
      first_gen: payload.first_gen ?? false,
      minority_flag: payload.minority_flag ?? false,
      professional_affiliations: payload.professional_affiliations ?? [],
      hobbies: payload.hobbies ?? [],
      subscription_tier: "free",
      full_name: null,
      email: null,
      terms_accepted_at: null,
      privacy_accepted_at: null,
      marketing_opt_in: false,
      marketing_opt_in_at: null,
      searches_used_this_week: 0,
      search_cycle_reset_at: null,
      feed_token: null,
      stripe_subscription_status: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    try {
      localStorage.setItem("grantrx_profile", JSON.stringify(localProfile));
    } catch {
      // localStorage may be unavailable (private mode) — proceed anyway
    }
    return localProfile;
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-textPrimary/40 backdrop-blur-sm">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-3xl bg-surfaceBg p-8 shadow-2xl">
        {/* Progress */}
        <div className="mb-6 flex items-center gap-2">
          {STEPS.map((label, i) => (
            <div key={label} className="flex-1">
              <div
                className={`h-1.5 rounded-full ${i <= step ? "bg-crayolaBlue" : "bg-textSecondary/15"}`}
              />
              <p className="mt-1.5 text-xs text-textSecondary">{label}</p>
            </div>
          ))}
        </div>

        {error && (
          <div className="mb-4 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3">
            <svg className="mt-0.5 h-5 w-5 shrink-0 text-red-500" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
            </svg>
            <div className="flex-1">
              <p className="text-sm font-medium text-red-800">Could not save profile</p>
              <p className="mt-0.5 text-xs text-red-600">{error}</p>
            </div>
            <button
              onClick={() => setError(null)}
              className="shrink-0 text-red-400 hover:text-red-600"
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
              <MultiSelect
                label="Target Credentials (optional — select all that apply)"
                options={CREDENTIAL_OPTIONS}
                selected={credentials}
                onChange={setCredentials}
                placeholder="Select credentials…"
                maxHeight={200}
              />
            </div>

            {/* Skip button — prominent on screen 1 */}
            <div className="rounded-xl bg-cardBg p-4 text-center">
              <p className="text-sm text-textSecondary">
                No specific field in mind? You can explore all grants without selecting anything.
              </p>
              <button
                onClick={handleSkip}
                disabled={submitting}
                className="mt-3 inline-flex items-center gap-2 rounded-full border-2 border-crayolaBlue px-6 py-2.5 text-sm font-semibold text-crayolaBlue transition hover:bg-crayolaBlue/5 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting && (
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                )}
                {submitting ? "Setting up…" : "Skip Setup & Explore All Grants"}
              </button>
            </div>
          </div>
        )}

        {/* Step 2 — Academic Details (all optional) */}
        {step === 1 && (
          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-textSecondary">
                Clinical Phase (optional)
              </label>
              <input
                value={clinicalPhase}
                onChange={(e) => setClinicalPhase(e.target.value)}
                placeholder="e.g. P1, P2, MS3, Pre-Clinical"
                className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-textSecondary">
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
                  className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-textSecondary">
                  State of Residence (optional)
                </label>
                <input
                  value={stateResidence}
                  onChange={(e) =>
                    setStateResidence(e.target.value.toUpperCase().slice(0, 2))
                  }
                  placeholder="CA"
                  maxLength={2}
                  className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-textSecondary">
                SAI Score (optional)
              </label>
              <input
                value={saiScore}
                onChange={(e) => setSaiScore(e.target.value)}
                type="number"
                placeholder="e.g. 1200"
                className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-textSecondary">
                Metropolitan Area (optional)
              </label>
              <select
                value={metroArea}
                onChange={(e) => setMetroArea(e.target.value)}
                className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
              >
                <option value="">Any / Not specified</option>
                {getMetrosForState(stateResidence).map((m) => (
                  <option key={m.slug} value={m.name}>
                    {m.matchesState ? "\u2605 " : ""}{m.shortName} ({m.states.join(", ")})
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-textSecondary">
                {stateResidence
                  ? `Metros matching ${stateResidence} are starred and shown first. Selecting a metro area helps match metro-restricted scholarships.`
                  : "Selecting a metro area helps match metro-restricted scholarships."}
              </p>
            </div>
          </div>
        )}

        {/* Step 3 — Background & Interests (all optional) */}
        {step === 2 && (
          <div className="space-y-5">
            <div className="flex gap-6">
              <label className="flex items-center gap-2 text-sm text-textPrimary">
                <input
                  type="checkbox"
                  checked={firstGen}
                  onChange={(e) => setFirstGen(e.target.checked)}
                  className="h-4 w-4 accent-crayolaBlue"
                />
                First-Generation
              </label>
              <label className="flex items-center gap-2 text-sm text-textPrimary">
                <input
                  type="checkbox"
                  checked={minorityFlag}
                  onChange={(e) => setMinorityFlag(e.target.checked)}
                  className="h-4 w-4 accent-crayolaBlue"
                />
                Minority / Underrepresented
              </label>
            </div>

            <div>
              <label className="block text-sm font-medium text-textSecondary">
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
                        ? "bg-crayolaBlue text-surfaceBg"
                        : "border border-textSecondary/20 text-textSecondary"
                    }`}
                  >
                    {a}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-textSecondary">
                Hobbies / Interests (optional, comma-separated)
              </label>
              <input
                value={hobbies}
                onChange={(e) => setHobbies(e.target.value)}
                placeholder="research, volunteering, music"
                className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
              />
            </div>
          </div>
        )}

        {/* Navigation */}
        <div className="mt-8 flex items-center justify-between">
          {onCancel && step === 0 ? (
            <button
              onClick={onCancel}
              className="text-sm text-textSecondary hover:text-textPrimary"
            >
              Cancel
            </button>
          ) : (
            <button
              onClick={() => setStep((s) => s - 1)}
              disabled={step === 0}
              className="text-sm text-textSecondary hover:text-textPrimary disabled:opacity-30"
            >
              Back
            </button>
          )}

          {step < STEPS.length - 1 ? (
            <button
              onClick={() => setStep((s) => s + 1)}
              disabled={!canNext()}
              className="rounded-full bg-crayolaBlue px-6 py-2.5 text-sm font-medium text-surfaceBg disabled:opacity-40"
            >
              Continue
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="inline-flex items-center gap-2 rounded-full bg-aquamarine px-6 py-2.5 text-sm font-semibold text-textPrimary transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
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

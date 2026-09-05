"use client";

import Link from "next/link";
import type { Profile, Usage } from "@/lib/types";
import { DISCIPLINE_LABELS } from "@/lib/types";
import { TOP_20_METROS } from "@/lib/constants/metros";

export type LeftPanelProps = {
  profile: Profile | null;
  usage: Usage | null;
  search: string;
  onSearchChange: (v: string) => void;
  metroFilter: string;
  onMetroFilterChange: (v: string) => void;
  onOpenOnboarding: () => void;
  onKeywordSearch: () => void;
  onRefreshFeed: () => void;
  onUpgrade?: () => void;
  onOpenAuth?: () => void;
};

export function LeftPanel({
  profile,
  usage,
  search,
  onSearchChange,
  metroFilter,
  onMetroFilterChange,
  onOpenOnboarding,
  onKeywordSearch,
  onRefreshFeed,
  onUpgrade,
  onOpenAuth,
}: LeftPanelProps) {
  const hasText = search.trim().length > 0;
  const quotaExhausted =
    !!usage && !usage.is_premium && usage.remaining !== null && usage.remaining <= 0;
  // Only disable the keyword search button when the user has text AND quota is exhausted.
  // Without text, the button acts as a free match refresh.
  const searchDisabled = hasText && quotaExhausted;

  // Format disciplines for display
  const disciplineDisplay = profile?.disciplines?.length
    ? profile.disciplines.length <= 2
      ? profile.disciplines.join(", ")
      : `${profile.disciplines[0]} +${profile.disciplines.length - 1} more`
    : profile?.primary_discipline
      ? DISCIPLINE_LABELS[profile.primary_discipline] ?? profile.primary_discipline
      : "All disciplines";

  const credentialDisplay = profile?.target_credentials?.length
    ? profile.target_credentials.length <= 2
      ? profile.target_credentials.join(", ")
      : `${profile.target_credentials[0]} +${profile.target_credentials.length - 1} more`
    : profile?.target_credential ?? "All credentials";

  // Profile strength: count how many key fields are populated (0-100%)
  const profileStrength = profile
    ? Math.round(
        [
          profile.disciplines?.length > 0,
          profile.target_credentials?.length > 0,
          !!profile.clinical_phase,
          profile.gpa != null,
          !!profile.state_residence,
          !!profile.metro_area,
          profile.sai_score != null,
          profile.first_gen || profile.minority_flag,
        ].filter(Boolean).length / 8 * 100,
      )
    : 0;

  // Dynamic recommendation based on the highest-impact missing fields
  // Dynamic unlock guidance: list specific missing profile vectors
  const unlockGuidance = (() => {
    if (!profile) return null;
    if (profileStrength >= 100) return null;
    const missing: string[] = [];
    if (!profile.disciplines?.length && !profile.primary_discipline) missing.push("Field of Study");
    if (!profile.target_credentials?.length && !profile.target_credential) missing.push("Target Credential");
    if (!profile.clinical_phase) missing.push("Clinical Phase");
    if (profile.gpa == null) missing.push("GPA");
    if (!profile.state_residence) missing.push("State of Residence");
    if (!profile.metro_area) missing.push("Metro Area");
    if (profile.sai_score == null) missing.push("SAI Score");
    if (!profile.first_gen && !profile.minority_flag) missing.push("Demographics");
    if (!profile.professional_affiliations?.length) missing.push("Affiliations");
    return missing;
  })();

  const strengthPrompt = (() => {
    if (!profile) return null;
    if (profileStrength > 70) {
      return "High Match Ready \u2014 all matching algorithms fully activated.";
    }
    if (profileStrength < 40) {
      const missing: string[] = [];
      if (profile.gpa == null) missing.push("GPA");
      if (!profile.state_residence) missing.push("State");
      if (missing.length > 0) {
        return `Add your ${missing.join(" and ")} to unlock local state grants.`;
      }
      return "Complete your profile basics to unlock local state grants.";
    }
    // 40-70%: recommend affiliations / credential details
    if (!profile.professional_affiliations?.length) {
      return "Add professional affiliations (APhA, AMA) to boost match accuracy.";
    }
    if (!profile.target_credentials?.length && !profile.target_credential) {
      return "Add your target credential to sharpen scholarship matching.";
    }
    if (!profile.metro_area) {
      return "Add your metro area to surface regional scholarships.";
    }
    return "Add remaining profile details to boost match accuracy.";
  })();

  return (
    <div className="space-y-6">
      {/* Profile summary — frosted glass */}
      <section className="bg-white/95 backdrop-blur-md rounded-2xl border border-slate-200 shadow-xs p-6">
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-xl font-semibold text-textPrimary">
            Student Profile
          </h2>
          <button
            onClick={onOpenOnboarding}
            className="text-xs text-crayolaBlue hover:underline"
          >
            {profile ? "Edit" : "Set up"}
          </button>
        </div>
        {profile ? (
          <div className="mt-3 space-y-1 text-sm text-textSecondary">
            <p>
              <span className="font-medium text-textPrimary">
                {disciplineDisplay}
              </span>
            </p>
            <p>{credentialDisplay}</p>
            <p>
              {profile.clinical_phase ?? "—"} · GPA {profile.gpa?.toFixed(2) ?? "—"} ·{" "}
              {profile.state_residence ?? "—"}
            </p>
            <p className="text-xs">
              {profile.subscription_tier === "premium" ? "Premium" : "Free"} tier
            </p>

            {/* Profile Strength meter */}
            <div className="mt-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-textSecondary">
                  Profile Strength
                </span>
                {profileStrength > 70 && (
                  <span className="text-xs font-semibold text-blueEnergy bg-skyAqua/15 px-2 py-0.5 rounded-md">
                    {"\u26A1"} High Match Ready
                  </span>
                )}
              </div>
              <div className="mt-1.5 bg-slate-100 rounded-full h-3 overflow-hidden p-0.5">
                <div
                  className="bg-gradient-to-r from-skyAqua via-blueEnergy to-aquamarine h-full rounded-full transition-all duration-500"
                  style={{ width: `${profileStrength}%` }}
                />
              </div>
              {strengthPrompt && (
                <p
                  className={`mt-2 text-xs leading-relaxed ${
                    profileStrength > 70 ? "text-blueEnergy font-medium" : "text-textSecondary"
                  }`}
                >
                  {"\u26A1"} {strengthPrompt}
                </p>
              )}

              {/* Dynamic unlock guidance — missing profile vectors */}
              {unlockGuidance && unlockGuidance.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  <p className="text-xs font-medium text-textSecondary/70">
                    Unlock more matches by adding:
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {unlockGuidance.slice(0, 5).map((field) => (
                      <span
                        key={field}
                        className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-textSecondary border border-slate-200"
                      >
                        <svg className="h-3 w-3 text-textSecondary/50" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                        </svg>
                        {field}
                      </span>
                    ))}
                    {unlockGuidance.length > 5 && (
                      <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs text-textSecondary border border-slate-200">
                        +{unlockGuidance.length - 5} more
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            <p className="text-sm text-textSecondary">
              Complete onboarding to start matching.
            </p>
            {onOpenAuth && (
              <button
                onClick={onOpenAuth}
                className="rounded-full bg-crayolaBlue px-4 py-2 text-xs font-medium text-surfaceBg"
              >
                Sign In / Sign Up
              </button>
            )}
          </div>
        )}
      </section>

      {/* Search — frosted glass */}
      <section className="bg-white/95 backdrop-blur-md rounded-2xl border border-slate-200 shadow-xs p-6">
        <label className="text-sm font-medium text-textSecondary">
          Keyword Search
        </label>
        <div className="relative mt-2">
          <input
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                if (hasText && !quotaExhausted) onKeywordSearch();
                else if (!hasText) onRefreshFeed();
              }
            }}
            placeholder="Keyword, provider, or tag"
            className="w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 pr-10 text-textPrimary placeholder:text-textSecondary/50"
          />
          {/* Search icon button */}
          <button
            onClick={() => {
              if (hasText && !quotaExhausted) onKeywordSearch();
              else if (!hasText) onRefreshFeed();
            }}
            disabled={searchDisabled}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-textSecondary hover:text-crayolaBlue disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Search"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </button>
        </div>
        {/* Keyword search button — consumes quota only when text is present */}
        <button
          onClick={() => {
            if (hasText) onKeywordSearch();
            else onRefreshFeed();
          }}
          disabled={searchDisabled}
          className="mt-3 w-full rounded-full bg-crayolaBlue px-4 py-2 text-sm font-medium text-surfaceBg hover:bg-blueEnergy disabled:cursor-not-allowed disabled:opacity-40"
        >
          {searchDisabled
            ? "Keyword Search Limit Reached"
            : hasText
              ? "Search Grants"
              : "Search Grants"}
        </button>

        {/* Free refresh button — always free, no quota deduction */}
        <button
          onClick={onRefreshFeed}
          className="mt-2 w-full rounded-full border border-textSecondary/20 px-4 py-2 text-sm font-medium text-textSecondary hover:border-crayolaBlue/40 hover:text-crayolaBlue"
        >
          Refresh Matches (free)
        </button>

        {searchDisabled && (
          <p className="mt-2 text-xs text-textSecondary">
            You&apos;ve used all 10 free keyword searches this week.{" "}
            {onUpgrade && (
              <button
                onClick={onUpgrade}
                className="text-crayolaBlue hover:underline"
              >
                Upgrade to Premium
              </button>
            )}{" "}
            for unlimited keyword searches. Filter adjustments and match
            refreshes remain free.
          </p>
        )}
      </section>

      {/* Metro Area filter — frosted glass */}
      <section className="bg-white/95 backdrop-blur-md rounded-2xl border border-slate-200 shadow-xs p-6">
        <label className="text-sm font-medium text-textSecondary">
          Metro Area Filter
        </label>
        <select
          value={metroFilter}
          onChange={(e) => onMetroFilterChange(e.target.value)}
          className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
        >
          <option value="">All metros</option>
          {TOP_20_METROS.map((m) => (
            <option key={m.slug} value={m.name}>
              {m.shortName}
            </option>
          ))}
        </select>
        {metroFilter && (
          <button
            onClick={() => onMetroFilterChange("")}
            className="mt-2 text-xs text-crayolaBlue hover:underline"
          >
            Clear metro filter
          </button>
        )}
      </section>

      {/* Usage tracker — frosted glass */}
      {usage && (
        <section className="bg-white/95 backdrop-blur-md rounded-2xl border border-slate-200 shadow-xs p-6">
          <h3 className="font-serif text-lg font-semibold text-textPrimary">
            Keyword Search Quota
          </h3>
          {usage.is_premium ? (
            <p className="mt-2 text-sm text-textSecondary">
              Unlimited searches (Premium)
            </p>
          ) : (
            <>
              <p className="mt-2 text-sm text-textPrimary">
                Keyword searches this week:{" "}
                <span className="font-semibold">
                  {usage.searches_used_this_week}
                </span>{" "}
                / {usage.search_limit ?? 10}
              </p>
              <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-textSecondary/15">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-aquamarine to-neonIce transition-all duration-500 ease-out"
                  style={{
                    width: `${Math.min(
                      100,
                      (usage.searches_used_this_week /
                        (usage.search_limit ?? 1)) *
                        100,
                    )}%`,
                  }}
                />
              </div>
              <p className="mt-2 text-xs text-textSecondary">
                {usage.search_limit
                  ? `${usage.search_limit - usage.searches_used_this_week} keyword search${usage.search_limit - usage.searches_used_this_week === 1 ? "" : "es"} left this week. Filter adjustments and match refreshes are unlimited.`
                  : "Unlimited keyword searches (Premium)."}
              </p>
              <p className="mt-1 text-xs text-textSecondary">
                Resets {formatResetCountdown(usage.reset_at)}
              </p>
            </>
          )}
        </section>
      )}

      {/* Upgrade CTA */}
      {usage && !usage.is_premium && (
        <section className="rounded-2xl bg-gradient-to-r from-aquamarine to-neonIce p-5 text-textPrimary">
          <h3 className="font-serif text-lg font-semibold">Upgrade to Premium</h3>
          <p className="mt-1 text-sm">
            Unlimited searches, unmasked results, and deadline reminders.
          </p>
          <button
            onClick={onUpgrade}
            className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-textPrimary px-4 py-2 text-sm font-semibold text-surfaceBg transition hover:opacity-90"
          >
            <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
              <path d="M11.983 1.908a.963.963 0 00-1.306.196L6.95 7.075A.963.963 0 007.646 8.6h2.09l-1.39 4.36a.963.963 0 001.548.963l4.727-4.97a.963.963 0 00-.696-1.617h-2.09l1.39-4.36a.963.963 0 00-.732-1.068z" />
            </svg>
            View Plans
          </button>
        </section>
      )}

      {/* Legal footer */}
      <footer className="pt-2 text-center">
        <p className="text-xs text-textSecondary/60">
          © 2026 GrantRx. All rights reserved.
        </p>
        <p className="mt-1 text-xs">
          <Link href="/terms" className="text-textSecondary/60 hover:text-crayolaBlue hover:underline">
            Terms of Service
          </Link>
          {" · "}
          <Link href="/privacy" className="text-textSecondary/60 hover:text-crayolaBlue hover:underline">
            Privacy Policy
          </Link>
        </p>
      </footer>
    </div>
  );
}

function formatResetCountdown(iso: string): string {
  const target = new Date(iso).getTime();
  const now = Date.now();
  const diff = target - now;
  if (diff <= 0) return "soon";
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
  if (days > 0) return `in ${days}d ${hours}h`;
  const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
  return `in ${hours}h ${mins}m`;
}

'use client';

import { useCallback, useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/Shell";
import { LeftPanel } from "@/components/LeftPanel";
import { OnboardingWizard } from "@/components/OnboardingWizard";
import { ProfileEditModal } from "@/components/ProfileEditModal";
import { AuthModal } from "@/components/AuthModal";
import { AccountSettingsModal } from "@/components/AccountSettingsModal";
import { ScholarshipFeed } from "@/components/ScholarshipFeed";
import { KanbanBoard } from "@/components/KanbanBoard";
import { DeadlineCalendar } from "@/components/DeadlineCalendar";
import { CollegeFinancialPlanner } from "@/components/CollegeFinancialPlanner";
import { UpgradeModal } from "@/components/UpgradeModal";
import { api, setAuthToken } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type {
  MatchedFeed,
  MatchedScholarship,
  Profile,
  Usage,
  UserScholarship,
} from "@/lib/types";

type Tab = "discover" | "kanban" | "calendar" | "planner";

export default function Home() {
  const [tab, setTab] = useState<Tab>("discover");
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [showAuth, setShowAuth] = useState(false);
  const [showUpgrade, setShowUpgrade] = useState(false);
  const [showProfileEdit, setShowProfileEdit] = useState(false);
  const [showAccountSettings, setShowAccountSettings] = useState(false);
  const [upgradeReason, setUpgradeReason] = useState<string | undefined>(undefined);

  const [profile, setProfile] = useState<Profile | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [feed, setFeed] = useState<MatchedFeed | null>(null);
  const [kanbanItems, setKanbanItems] = useState<UserScholarship[]>([]);
  const [search, setSearch] = useState("");
  const [metroFilter, setMetroFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auth token is auto-configured in lib/api.ts:
  //   - Uses NEXT_PUBLIC_DEMO_JWT if set
  //   - Falls back to "grantrx-dev-demo" for local dev (accepted by backend in dev mode)
  //   - In production, setAuthToken(supabaseSession.access_token) after OAuth login

  // Immediately restore cached profile from localStorage on mount so the
  // LeftPanel and matching feed recognize the user is logged in without
  // waiting for the async Supabase session check to complete.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const cachedProfile = localStorage.getItem("grantrx_profile");
      if (cachedProfile) {
        setProfile(JSON.parse(cachedProfile));
      }
    } catch {
      // localStorage may be unavailable or contain invalid JSON — ignore
    }
  }, []);

  // Session check and auth state listener are defined after loadFeed below
  // because they depend on loadFeed for immediate feed hydration after OAuth.

  // Detect ?onboarding=open from OAuth callback redirect
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("onboarding") === "open") {
      setShowOnboarding(true);
      // Clean up the URL param
      params.delete("onboarding");
      const cleanUrl = params.toString()
        ? `${window.location.pathname}?${params.toString()}`
        : window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
    }
  }, []);

  // Strip stale ?auth_error=... from the URL so it doesn't trigger
  // persistent error banners after the OAuth redirect lands.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.has("auth_error")) {
      params.delete("auth_error");
      const cleanUrl = params.toString()
        ? `${window.location.pathname}?${params.toString()}`
        : window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
    }
  }, []);

  // Load profile + usage on mount
  const loadProfileAndUsage = useCallback(async () => {
    try {
      const p = await api.getProfile();
      setProfile(p);
      // If profile exists, close onboarding wizard
      setShowOnboarding(false);
    } catch {
      setProfile(null);
    }
    try {
      const u = await api.getUsage();
      setUsage(u);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async data load on mount
    loadProfileAndUsage().catch(() => {
      if (!cancelled) setProfile(null);
    });
    return () => { cancelled = true; };
  }, [loadProfileAndUsage]);

  // Load matched feed (initial load / refresh / filter change — does NOT
  // consume a search quota because no keyword query is sent)
  const loadFeed = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const f = await api.getMatchedScholarships();
      setFeed(f);
      // If the feed was loaded via the Supabase fallback (backend returned
      // "Invalid token" or was unreachable), clear any stale error banner
      // so the red error box never shows alongside working fallback data.
      setError(null);
      // Refresh usage display — wrapped separately so a usage fetch failure
      // doesn't blank out the successfully loaded feed.
      try {
        const u = await api.getUsage();
        setUsage(u);
      } catch {
        /* usage fetch failure is non-fatal */
      }
    } catch (err) {
      const e = err as Error & { status?: number; body?: unknown };
      if (e.status === 404) {
        setError("Please complete onboarding to see matched scholarships.");
      } else if (e.message?.includes("Invalid token")) {
        // Suppress the "Invalid token" banner — the Supabase fallback in
        // getMatchedScholarships should have handled this, but if it also
        // failed, show a neutral message instead of the raw error.
        setError(null);
      } else {
        setError(e.message || "Failed to load scholarships");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Load the feed on mount — works for both authenticated users and guest
  // visitors. The Supabase fallback in getMatchedScholarships handles
  // unauthenticated users without throwing or setting an error banner.
  useEffect(() => {
    loadFeed();
  }, [loadFeed]);

  // Check for existing Supabase session on mount and listen for auth state
  // changes (covers Google/LinkedIn OAuth redirects that arrive after mount).
  // Hydrates the profile from localStorage, Supabase, or OAuth user_metadata
  // so the LeftPanel and feed recognize the user immediately.
  useEffect(() => {
    if (!supabase) return;

    // Helper: hydrate profile from session
    const hydrateProfile = async (session: { user?: { id?: string; email?: string; user_metadata?: Record<string, unknown> } | null; access_token?: string } | null) => {
      if (!session?.user) return;
      if (session.access_token) setAuthToken(session.access_token);

      // 1. Check localStorage for a cached profile
      try {
        const cached = localStorage.getItem("grantrx_profile");
        if (cached) {
          setProfile(JSON.parse(cached));
        }
      } catch {
        // localStorage may be unavailable or contain invalid JSON — ignore
      }

      // 2. Query Supabase directly for the user's profile row
      try {
        const { data: sbProfile } = await supabase
          .from("profiles")
          .select("*")
          .eq("id", session.user.id)
          .maybeSingle();

        if (sbProfile && sbProfile.primary_discipline) {
          setProfile(sbProfile);
          localStorage.setItem("grantrx_profile", JSON.stringify(sbProfile));
          loadFeed();
        } else {
          // New OAuth user: seed profile from OAuth user_metadata
          const metaName =
            (session.user.user_metadata?.full_name as string) ||
            (session.user.user_metadata?.name as string) ||
            "Student";
          const metaEmail = session.user.email || "";
          const newOAuthProfile = {
            id: session.user.id,
            user_id: session.user.id,
            full_name: metaName,
            email: metaEmail,
            primary_discipline: sbProfile?.primary_discipline || "pharmacy",
            target_credential: sbProfile?.target_credential || "PharmD",
            clinical_phase: sbProfile?.clinical_phase || "Professional (P1-P4)",
            gpa: sbProfile?.gpa || 3.5,
            state_residence: sbProfile?.state_residence || "OH",
            updated_at: new Date().toISOString(),
          };
          setProfile(newOAuthProfile as unknown as Profile);
          localStorage.setItem("grantrx_profile", JSON.stringify(newOAuthProfile));
          loadFeed();
        }
      } catch {
        // Supabase query failed — the localStorage profile (if any) is enough
      }
    };

    // Initial session check
    supabase.auth.getSession().then(({ data }) => {
      hydrateProfile(data.session as Parameters<typeof hydrateProfile>[0]);
    });

    // Listen for auth state changes (OAuth redirects, token refreshes, etc.)
    const { data: authListener } = supabase.auth.onAuthStateChange(
      async (_event, session) => {
        hydrateProfile(session as Parameters<typeof hydrateProfile>[0]);
      },
    );

    return () => {
      authListener?.subscription?.unsubscribe();
    };
  }, [loadFeed]);

  // Explicit keyword search (consumes a search quota for free users).
  // Only called when the user presses Enter or clicks the search icon with
  // active text in the search input.
  const runKeywordSearch = useCallback(async () => {
    const keyword = search.trim();
    // No text — treat as a free refresh, not a keyword search
    if (!keyword) {
      loadFeed();
      return;
    }

    // Check if user has reached their limit before making the request
    if (usage && !usage.is_premium && usage.remaining !== null && usage.remaining <= 0) {
      setUpgradeReason("You've reached your free keyword search limit (10/week). Upgrade for unlimited searches.");
      setShowUpgrade(true);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const f = await api.getMatchedScholarships(keyword);
      setFeed(f);
      // Refresh usage after consuming a search
      const u = await api.getUsage();
      setUsage(u);
    } catch (err) {
      const e = err as Error & { status?: number; body?: unknown };
      if (e.status === 402) {
        setUpgradeReason("You've reached your free keyword search limit (10/week). Upgrade for unlimited searches.");
        setShowUpgrade(true);
      } else if (e.message?.includes("Invalid token") || e.message === "Invalid token") {
        console.warn("Suppressed unauthenticated token error on public feed:", err);
        setError(null);
        return;
      } else {
        setError(e.message || "Failed to load scholarships");
      }
    } finally {
      setLoading(false);
    }
  }, [usage, search, loadFeed]);

  // Load kanban items
  const loadKanban = useCallback(async () => {
    try {
      const items = await api.listUserScholarships();
      setKanbanItems(items);
    } catch (err) {
      console.error("Failed to load kanban", err);
    }
  }, []);

  useEffect(() => {
    if (tab !== "kanban") return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async data load on tab change
    loadKanban().catch(() => {
      if (!cancelled) return;
    });
    return () => { cancelled = true; };
  }, [tab, loadKanban]);

  // Filter feed by search keyword and metro filter
  const filteredResults: MatchedScholarship[] = useMemo(() => {
    if (!feed) return [];
    let results = feed.results;

    // Metro filter: show only scholarships matching the selected metro
    if (metroFilter) {
      results = results.filter(
        (r) =>
          r.metro_restrictions?.length > 0 &&
          r.metro_restrictions.some((m) => m === metroFilter),
      );
    }

    // Keyword search filter (client-side live filtering)
    if (search.trim()) {
      const q = search.toLowerCase();
      results = results.filter(
        (r) =>
          r.title.toLowerCase().includes(q) ||
          r.provider.toLowerCase().includes(q) ||
          r.missing_criteria.some((c) => c.toLowerCase().includes(q)),
      );
    }

    return results;
  }, [feed, search, metroFilter]);

  const isPremium = usage?.is_premium ?? false;

  const handleOnboardingComplete = (p: Profile) => {
    setProfile(p);
    setShowOnboarding(false);
    loadProfileAndUsage();
    loadFeed();  // Initial load — does not consume a search
  };

  const handleAuthSuccess = (p: Profile | null) => {
    setShowAuth(false);
    // Clean up OAuth consent data from localStorage now that auth is complete
    try {
      localStorage.removeItem("grantrx_oauth_consent");
    } catch {
      // localStorage may be unavailable — ignore
    }
    if (p) {
      setProfile(p);
      // Profile already complete — show discovery feed (initial load, no search consumed)
      setShowOnboarding(false);
      loadFeed();
    } else {
      // No profile yet — open onboarding wizard
      setShowOnboarding(true);
    }
  };

  const handleKanbanChanged = () => {
    loadKanban();
  };

  const openUpgrade = (reason?: string) => {
    setUpgradeReason(reason);
    setShowUpgrade(true);
  };

  const handleSignOut = async () => {
    if (supabase) {
      try {
        await supabase.auth.signOut();
      } catch {
        // Best-effort — proceed with local cleanup
      }
    }
    try {
      localStorage.removeItem("grantrx_profile");
    } catch {
      // localStorage may be unavailable — ignore
    }
    setProfile(null);
    setUsage(null);
    setFeed(null);
    setAuthToken(null);
  };

  return (
    <>
      <Shell
        left={
          <LeftPanel
            profile={profile}
            usage={usage}
            search={search}
            onSearchChange={setSearch}
            metroFilter={metroFilter}
            onMetroFilterChange={setMetroFilter}
            onOpenOnboarding={() => {
              if (profile) {
                setShowProfileEdit(true);
              } else {
                setShowOnboarding(true);
              }
            }}
            onKeywordSearch={runKeywordSearch}
            onRefreshFeed={loadFeed}
            onUpgrade={() => openUpgrade()}
            onOpenAuth={() => setShowAuth(true)}
            onSignOut={handleSignOut}
            onOpenAccountSettings={() => setShowAccountSettings(true)}
          />
        }
        right={
          <div className="space-y-6">
            {/* Tab switcher */}
            <div className="flex gap-2 border-b border-textSecondary/10 pb-3">
              <TabButton
                active={tab === "discover"}
                onClick={() => setTab("discover")}
              >
                Discover Grants
              </TabButton>
              <TabButton
                active={tab === "kanban"}
                onClick={() => setTab("kanban")}
              >
                My Applications
              </TabButton>
              <TabButton
                active={tab === "calendar"}
                onClick={() => setTab("calendar")}
              >
                Calendar
              </TabButton>
              <TabButton
                active={tab === "planner"}
                onClick={() => setTab("planner")}
              >
                Financial Planner
              </TabButton>
            </div>

            {error && error !== "Invalid token" && (
              <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-600">
                {error}
              </div>
            )}

            {tab === "discover" && (
              <div className="space-y-4">
                <h1 className="font-serif text-3xl font-bold text-textPrimary">
                  Discover Scholarships
                </h1>

                {!profile && !error && (
                  <div className="rounded-2xl bg-cardBg p-6 text-center">
                    <p className="text-textSecondary">
                      Complete your profile to see matched scholarships.
                    </p>
                    <button
                      onClick={() => setShowOnboarding(true)}
                      className="mt-4 rounded-full bg-crayolaBlue px-6 py-2.5 text-sm font-medium text-surfaceBg"
                    >
                      Start Onboarding
                    </button>
                  </div>
                )}

                {profile && !feed && !loading && !error && (
                  <div className="rounded-2xl bg-cardBg p-6 text-center">
                    <p className="text-textSecondary">
                      Click &ldquo;Refresh Matches&rdquo; to run the matching engine.
                    </p>
                  </div>
                )}

                {loading && (
                  <div className="rounded-2xl bg-cardBg p-6 text-center text-textSecondary">
                    Loading matches…
                  </div>
                )}

                {feed && (
                  <>
                    <p className="text-sm text-textSecondary">
                      {feed.total} scholarships matched · {feed.visible} visible
                      {!isPremium && ` (free tier shows top ${feed.visible})`}
                    </p>
                    <ScholarshipFeed
                      results={filteredResults}
                      isPremium={isPremium}
                      onUnlock={() =>
                        openUpgrade("Unlock all scholarship results with Premium.")
                      }
                      onTrack={() => {
                        // Refresh kanban count silently
                        loadKanban();
                      }}
                    />
                  </>
                )}
              </div>
            )}

            {tab === "kanban" && (
              <div className="space-y-4">
                <h1 className="font-serif text-3xl font-bold text-textPrimary">
                  My Applications
                </h1>
                <p className="text-sm text-textSecondary">
                  Drag cards between columns to update status.{" "}
                  {!isPremium &&
                    "Free tier: max 3 active applications (In Progress + Submitted)."}
                </p>
                <KanbanBoard
                  items={kanbanItems}
                  isPremium={isPremium}
                  onChanged={handleKanbanChanged}
                  onPaywall={() =>
                    openUpgrade(
                      "Free tier is limited to 3 active applications. Upgrade to Premium for unlimited tracking.",
                    )
                  }
                />
              </div>
            )}

            {tab === "calendar" && (
              <DeadlineCalendar isPremium={isPremium} />
            )}

            {tab === "planner" && (
              <CollegeFinancialPlanner />
            )}
          </div>
        }
      />

      {showOnboarding && (
        <OnboardingWizard
          onComplete={handleOnboardingComplete}
          onCancel={profile ? () => setShowOnboarding(false) : undefined}
          existingProfile={profile}
        />
      )}

      {showProfileEdit && profile && (
        <ProfileEditModal
          open={showProfileEdit}
          onClose={() => setShowProfileEdit(false)}
          profile={profile}
          onSaved={(p) => {
            setProfile(p);
            loadProfileAndUsage();
            loadFeed();
          }}
          onDeleted={() => {
            setProfile(null);
            setUsage(null);
            setKanbanItems([]);
            setFeed(null);
            setShowProfileEdit(false);
            setShowOnboarding(false);
            setError("Your account has been permanently deleted.");
          }}
        />
      )}

      <AuthModal
        open={showAuth}
        onClose={() => setShowAuth(false)}
        onAuthSuccess={handleAuthSuccess}
      />

      <UpgradeModal
        open={showUpgrade}
        onClose={() => setShowUpgrade(false)}
        reason={upgradeReason}
      />

      <AccountSettingsModal
        open={showAccountSettings}
        onClose={() => setShowAccountSettings(false)}
        profile={profile}
        onProfileUpdated={(p) => setProfile(p)}
        onUpgrade={() => openUpgrade()}
        onDeleted={() => {
          setProfile(null);
          setUsage(null);
          setKanbanItems([]);
          setFeed(null);
          setShowAccountSettings(false);
          setShowOnboarding(false);
          setAuthToken(null);
          setError("Your account has been permanently deleted.");
        }}
      />
    </>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-5 py-2 text-sm font-medium transition ${
        active
          ? "bg-crayolaBlue text-surfaceBg"
          : "text-textSecondary hover:text-textPrimary"
      }`}
    >
      {children}
    </button>
  );
}

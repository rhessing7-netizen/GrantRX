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
import { InteractiveTour, notifyTourSave } from "@/components/InteractiveTour";
import { MobileHeader } from "@/components/MobileHeader";
import { MobileBottomNav } from "@/components/MobileBottomNav";
import { MobileMenu } from "@/components/MobileMenu";
import { DiscoverSearch } from "@/components/DiscoverSearch";
import { api, setAuthToken, getAuthToken } from "@/lib/api";
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
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [upgradeReason, setUpgradeReason] = useState<string | undefined>(undefined);

  const [profile, setProfile] = useState<Profile | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  // Auth resolution gate: protected API calls must not leave the browser
  // before the Supabase session (or a configured dev token) is known.
  const [authState, setAuthState] = useState<
    "pending" | "anonymous" | "signed-in"
  >("pending");
  const [feed, setFeed] = useState<MatchedFeed | null>(null);
  const [kanbanItems, setKanbanItems] = useState<UserScholarship[]>([]);
  const [search, setSearch] = useState("");
  const [metroFilter, setMetroFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authNotice, setAuthNotice] = useState<string | null>(null);

  // Auth comes from the Supabase session. A demo JWT is used only when
  // NEXT_PUBLIC_DEMO_JWT is explicitly configured for local testing.

  // Session check and auth state listener are defined after loadFeed below:
  // auth resolution gates whether the protected initial loads ever run.

  // Restore the cached profile after mount. localStorage is client-only, so
  // the first render must agree with SSR (null); the cache is applied
  // post-mount as a UX hint only — the backend profile fetched in
  // loadProfileAndUsage stays authoritative and overwrites it.
  useEffect(() => {
    queueMicrotask(() => {
      try {
        const cached = localStorage.getItem("grantrx_profile");
        if (cached) {
          setProfile(JSON.parse(cached) as Profile);
        }
      } catch {
        // localStorage may be unavailable or contain invalid JSON — ignore
      }
    });
  }, []);

  // Detect and consume the ?onboarding=open flag from the OAuth callback
  // redirect. The wizard opens post-mount (deferred) so SSR and the first
  // client render agree, then the URL flag is stripped.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("onboarding") === "open") {
      params.delete("onboarding");
      const cleanUrl = params.toString()
        ? `${window.location.pathname}?${params.toString()}`
        : window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
      queueMicrotask(() => setShowOnboarding(true));
    }
    // The layout-mounted support assistant redirects here with ?signin=1
    // when a guest taps Sign In from a public page.
    if (params.get("signin") === "1") {
      params.delete("signin");
      const cleanUrl = params.toString()
        ? `${window.location.pathname}?${params.toString()}`
        : window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
      queueMicrotask(() => setShowAuth(true));
    }
  }, []);

  // Consume ?auth_error=... from the OAuth callback: map the safe error
  // code to a friendly notice, then strip it from the URL.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("auth_error");
    if (code) {
      params.delete("auth_error");
      const cleanUrl = params.toString()
        ? `${window.location.pathname}?${params.toString()}`
        : window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
      const messages: Record<string, string> = {
        cancelled: "Sign-in was cancelled. You can try again anytime.",
        oauth_failed:
          "We couldn't complete sign-in with that provider. Please try again or use email and password.",
        auth_unavailable:
          "Sign-in is temporarily unavailable. Please try again in a few minutes.",
      };
      const message =
        messages[code] ??
        "Sign-in couldn't be completed. Please try again.";
      queueMicrotask(() => setAuthNotice(message));
    }
  }, []);

  // Load profile + usage (only runs once a session/token is confirmed — see
  // the auth-gated effect below).
  const loadProfileAndUsage = useCallback(async () => {
    try {
      const p = await api.getProfile();
      setProfile(p);
      try {
        localStorage.setItem("grantrx_profile", JSON.stringify(p));
      } catch {
        // localStorage may be unavailable — non-fatal
      }
      // If profile exists, close onboarding wizard
      setShowOnboarding(false);
    } catch (err) {
      const status = (err as Error & { status?: number }).status;
      setProfile(null);
      // Signed-in user with no profile yet → onboarding wizard.
      if (status === 404) setShowOnboarding(true);
    }
    try {
      const u = await api.getUsage();
      setUsage(u);
    } catch {
      /* ignore */
    }
  }, []);

  // Components outside the page tree (e.g. the layout-mounted support
  // assistant) can request the auth modal via this event.
  useEffect(() => {
    const open = () => setShowAuth(true);
    window.addEventListener("grantrx:auth:open", open);
    return () => window.removeEventListener("grantrx:auth:open", open);
  }, []);

  // Load matched feed (initial load / refresh / filter change — does NOT
  // consume a search quota because no keyword query is sent)
  const loadFeed = useCallback(async () => {
    if (!getAuthToken()) {
      // Confirmed anonymous — never dispatch the protected request.
      setFeed(null);
      setError("Please sign in to see matched opportunities.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const f = await api.getMatchedScholarships();
      setFeed(f);
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
        setError("Please complete onboarding to see matched opportunities.");
      } else if (e.status === 401) {
        // Distinguish anonymous users (no saved token) from users whose token
        // has expired or been invalidated; raw backend details must not surface.
        if (getAuthToken()) {
          setError("Your session has expired. Please sign in again.");
        } else {
          setError("Please sign in to see matched opportunities.");
        }
      } else {
        // Unexpected errors keep their detail and are logged for diagnosis.
        console.error("Feed load failed:", err);
        setError(e.message || "Failed to load opportunities");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Resolve auth state BEFORE any protected API call. Session resolution
  // comes first; confirmed-anonymous users get the signed-out Discover
  // experience without a single authenticated request leaving the browser.
  useEffect(() => {
    const applyAnonymous = () => {
      setAuthState("anonymous");
      // A stale cached profile must not linger for a signed-out visitor.
      setProfile(null);
      setUsage(null);
      setFeed(null);
      try {
        localStorage.removeItem("grantrx_profile");
      } catch {
        // localStorage may be unavailable — ignore
      }
      setError("Please sign in to see matched opportunities.");
    };

    const applySession = (session: { access_token?: string } | null) => {
      if (session?.access_token) setAuthToken(session.access_token);
      setAuthState("signed-in");
      // Show the locally cached profile immediately as a UX hint; the
      // authoritative backend fetch in loadProfileAndUsage overwrites it.
      try {
        const cached = localStorage.getItem("grantrx_profile");
        if (cached) setProfile(JSON.parse(cached) as Profile);
      } catch {
        // localStorage may be unavailable or contain invalid JSON — ignore
      }
    };

    const resolve = (session: { user?: unknown; access_token?: string } | null) => {
      if (session?.user) {
        applySession(session);
      } else if (getAuthToken()) {
        // Pre-signed token configured via NEXT_PUBLIC_DEMO_JWT, or an
        // injected dev token — signed-in path without a Supabase session.
        setAuthState("signed-in");
      } else {
        applyAnonymous();
      }
    };

    if (!supabase) {
      // No Supabase client — the only possible credential is a configured
      // dev token; otherwise the visitor is confirmed anonymous.
      queueMicrotask(() => resolve(null));
      return;
    }

    // Initial session check
    supabase.auth.getSession()
      .then(({ data }) => resolve(data.session))
      .catch(() => resolve(null));

    // Listen for auth state changes (OAuth redirects, token refreshes, etc.)
    const { data: authListener } = supabase.auth.onAuthStateChange(
      (event, session) => {
        if (event === "SIGNED_OUT") {
          setAuthToken(null);
          applyAnonymous();
          return;
        }
        if (session?.user) applySession(session);
      },
    );

    return () => {
      authListener?.subscription?.unsubscribe();
    };
  }, []);

  // Authenticated initial load — fires only once auth resolves to signed-in.
  // Profile/usage/feed are protected endpoints; anonymous users never reach
  // this branch. Failures remain visible instead of being replaced with
  // fabricated scholarship data.
  useEffect(() => {
    if (authState !== "signed-in") return;
    let cancelled = false;
    // Deferred to a microtask so the loaders' synchronous setState does not
    // run inside the effect body.
    queueMicrotask(() => {
      if (cancelled) return;
      loadProfileAndUsage().catch(() => {
        if (!cancelled) setProfile(null);
      });
      void loadFeed();
    });
    return () => { cancelled = true; };
  }, [authState, loadProfileAndUsage, loadFeed]);

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
      setUpgradeReason(`You've reached your free keyword search limit (${usage.search_limit ?? 10}/week). Upgrade for unlimited searches.`);
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
        setUpgradeReason(`You've reached your free keyword search limit (${usage?.search_limit ?? 10}/week). Upgrade for unlimited searches.`);
        setShowUpgrade(true);
      } else if (e.status === 401) {
        setError("Please sign in to see matched opportunities.");
      } else if (e.message?.includes("Invalid token") || e.message === "Invalid token") {
        console.warn("Suppressed unauthenticated token error on public feed:", err);
        setError(null);
        return;
      } else {
        setError(e.message || "Failed to load opportunities");
      }
    } finally {
      setLoading(false);
    }
  }, [usage, search, loadFeed]);

  // Load kanban items
  const loadKanban = useCallback(async () => {
    if (!getAuthToken()) {
      setKanbanItems([]);
      return;
    }
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

    // If the new user hasn't completed the product tour, launch it once the
    // feed renders. The tour component listens for this event and will only
    // start when the match-card element is present in the DOM.
    const tourCompleted =
      typeof window !== "undefined" &&
      localStorage.getItem("grantrx_tour_completed") === "true";
    if (!p.has_completed_tour && !tourCompleted) {
      // Defer slightly so loadFeed() has a chance to populate the DOM.
      setTimeout(() => {
        if (typeof window !== "undefined") {
          window.dispatchEvent(new CustomEvent("grantrx:tour:start"));
        }
      }, 1200);
    }
  };

  const handleAuthSuccess = (p: Profile | null) => {
    // Defense-in-depth: "auth succeeded" callers must never promote the app
    // to signed-in without a credential the API layer can actually send.
    if (!getAuthToken()) {
      console.warn(
        "handleAuthSuccess called without an auth token — remaining signed out",
      );
      setShowAuth(false);
      setAuthState("anonymous");
      setError("Please sign in to see matched opportunities.");
      return;
    }
    setShowAuth(false);
    setAuthState("signed-in");
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
    setAuthState("anonymous");
    setError("Please sign in to see matched opportunities.");
  };

  const leftPanelProps = {
    profile,
    usage,
    search,
    onSearchChange: setSearch,
    metroFilter,
    onMetroFilterChange: setMetroFilter,
    onOpenOnboarding: () => {
      if (profile) {
        setShowProfileEdit(true);
      } else {
        setShowOnboarding(true);
      }
    },
    onKeywordSearch: runKeywordSearch,
    onRefreshFeed: loadFeed,
    onUpgrade: () => openUpgrade(),
    onOpenAuth: () => setShowAuth(true),
    onSignOut: handleSignOut,
    onOpenAccountSettings: () => setShowAccountSettings(true),
    busy: loading,
  };

  return (
    <>
      <MobileHeader
        onOpenMenu={() => setMobileMenuOpen(true)}
        onOpenAccount={() => setShowAccountSettings(true)}
      />
      <MobileMenu open={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)}>
        <LeftPanel {...leftPanelProps} idPrefix="menu" />
        <div className="mt-6 space-y-2 border-t border-border pt-4">
          <button
            onClick={() => { setTab("planner"); setMobileMenuOpen(false); }}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-medium text-text transition hover:bg-surfaceSubtle"
          >
            <svg className="h-5 w-5 text-textMuted" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Financial Planner
          </button>
        </div>
      </MobileMenu>
      <Shell
        left={<LeftPanel key="desktop" {...leftPanelProps} />}
        right={
          <div className="space-y-6">
            {/* Tab switcher */}
            <div className="hidden flex-wrap gap-2 border-b border-textMuted/10 pb-3 lg:flex">
              <TabButton
                active={tab === "discover"}
                onClick={() => setTab("discover")}
              >
                Discover
              </TabButton>
              <TabButton
                active={tab === "kanban"}
                onClick={() => setTab("kanban")}
                data-tour="kanban-tab"
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

            {authNotice && (
              <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-secondary/30 bg-secondary/10 p-4 text-sm text-text">
                <p>{authNotice}</p>
                <button
                  onClick={() => setAuthNotice(null)}
                  className="shrink-0 rounded-lg p-1 text-textMuted transition hover:text-text"
                  aria-label="Dismiss notice"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            )}

            {error && error !== "Invalid token" && (
              <div className="mb-4 rounded-xl border border-danger/30 bg-dangerSoft p-4 text-sm text-danger">
                {error}
              </div>
            )}

            {tab === "discover" && (
              <div className="space-y-4">
                <h1 className="font-serif text-3xl font-bold text-text">
                  Discover Opportunities
                </h1>

                {/* Mobile Discover search — visible without opening the menu */}
                <div className="lg:hidden rounded-2xl border border-border bg-surface p-4 shadow-sm">
                  <DiscoverSearch
                    search={search}
                    onSearchChange={setSearch}
                    onKeywordSearch={runKeywordSearch}
                    onRefreshFeed={loadFeed}
                    usage={usage}
                    onUpgrade={() =>
                      openUpgrade(
                        `You've reached your free keyword search limit (${usage?.search_limit ?? 10}/week). Upgrade for unlimited searches.`,
                      )
                    }
                    idPrefix="mb"
                    busy={loading}
                  />
                </div>

                {!profile && !error && (
                  <div className="rounded-2xl bg-surfaceSubtle p-6 text-center">
                    <p className="text-textMuted">
                      Complete your profile to see matched opportunities.
                    </p>
                    <button
                      onClick={() => setShowOnboarding(true)}
                      className="mt-4 rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface"
                    >
                      Start Onboarding
                    </button>
                  </div>
                )}

                {profile && !feed && !loading && !error && (
                  <div className="rounded-2xl bg-surfaceSubtle p-6 text-center">
                    <p className="text-textMuted">
                      Click &ldquo;Refresh Matches&rdquo; to run the matching engine.
                    </p>
                  </div>
                )}

                {loading && (
                  <div className="rounded-2xl bg-surfaceSubtle p-6 text-center text-textMuted">
                    Loading matches…
                  </div>
                )}

                {feed && (
                  <>
                    <p className="text-sm text-textMuted">
                      {feed.total} opportunities matched · {feed.visible} visible
                      {!isPremium && ` (free tier shows top ${feed.visible})`}
                    </p>
                    <ScholarshipFeed
                      results={filteredResults}
                      isPremium={isPremium}
                      profile={profile}
                      onUnlock={() =>
                        openUpgrade("Unlock all matched opportunities with Premium.")
                      }
                      onTrack={() => {
                        // Refresh kanban count silently
                        loadKanban();
                        // Notify the interactive tour that a save action fired
                        notifyTourSave();
                      }}
                    />
                  </>
                )}
              </div>
            )}

            {tab === "kanban" && (
              <div className="space-y-4">
                <h1 className="font-serif text-3xl font-bold text-text">
                  My Applications
                </h1>
                <p className="text-sm text-textMuted">
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
              <DeadlineCalendar />
            )}

            {tab === "planner" && (
              <CollegeFinancialPlanner />
            )}
          </div>
        }
      />

      <InteractiveTour
        shouldStart={!loading && !!feed && !profile?.has_completed_tour}
        tab={tab}
        onSwitchTab={setTab}
        profile={profile}
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
            setAuthToken(null);
            setAuthState("anonymous");
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
          setAuthState("anonymous");
          setError("Your account has been permanently deleted.");
        }}
      />

      <MobileBottomNav
        activeTab={tab === "planner" ? null : (tab as "discover" | "kanban" | "calendar")}
        onTabChange={(t) => setTab(t)}
        onOpenMenu={() => setMobileMenuOpen(true)}
      />
    </>
  );
}

function TabButton({
  active,
  onClick,
  children,
  ...rest
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  "data-tour"?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-5 py-2 text-sm font-medium transition ${
        active
          ? "bg-primary text-surface"
          : "text-textMuted hover:text-text"
      }`}
      {...rest}
    >
      {children}
    </button>
  );
}

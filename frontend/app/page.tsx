"use client";
export const dynamic = 'force-dynamic';
import { useCallback, useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/Shell";
import { LeftPanel } from "@/components/LeftPanel";
import { OnboardingWizard } from "@/components/OnboardingWizard";
import { ProfileEditModal } from "@/components/ProfileEditModal";
import { AuthModal } from "@/components/AuthModal";
import { ScholarshipFeed } from "@/components/ScholarshipFeed";
import { KanbanBoard } from "@/components/KanbanBoard";
import { DeadlineCalendar } from "@/components/DeadlineCalendar";
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

type Tab = "discover" | "kanban" | "calendar";

export default function Home() {
  const [tab, setTab] = useState<Tab>("discover");
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [showAuth, setShowAuth] = useState(false);
  const [showUpgrade, setShowUpgrade] = useState(false);
  const [showProfileEdit, setShowProfileEdit] = useState(false);
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

  // Check for existing Supabase session on mount
  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => {
      if (data.session?.access_token) {
        setAuthToken(data.session.access_token);
      }
    });
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
      // Refresh usage display
      const u = await api.getUsage();
      setUsage(u);
    } catch (err) {
      const e = err as Error & { status?: number; body?: unknown };
      if (e.status === 404) {
        setError("Please complete onboarding to see matched scholarships.");
      } else {
        setError(e.message || "Failed to load scholarships");
      }
    } finally {
      setLoading(false);
    }
  }, []);

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
            </div>

            {error && (
              <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">
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

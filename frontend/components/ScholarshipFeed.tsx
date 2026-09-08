"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { MatchedScholarship, Profile, ScoreBucket } from "@/lib/types";
import { getMetroShortName } from "@/lib/constants/metros";
import { api } from "@/lib/api";
import { ApplicationDrawer } from "./ApplicationDrawer";

/** True when the keydown target is a text-entry surface — shortcuts must not
 *  fire while the user is typing. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

export type ScholarshipFeedProps = {
  results: MatchedScholarship[];
  isPremium: boolean;
  /** Student profile — used for the preview drawer's qualification breakdown. */
  profile?: Profile | null;
  onTrack?: (scholarshipId: string) => void;
  onUnlock?: () => void;
};

// ---------------------------------------------------------------------------
// Discipline banner images (curated clinical photography from Unsplash)
// ---------------------------------------------------------------------------
const DISCIPLINE_BANNERS: Record<string, string> = {
  pharmacy: "https://images.unsplash.com/photo-1587854692152-cbe660dbde88?auto=format&fit=crop&w=800&q=80",
  medicine: "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?auto=format&fit=crop&w=800&q=80",
  nursing: "https://images.unsplash.com/photo-1584515979956-d9f6e5d09982?auto=format&fit=crop&w=800&q=80",
  therapeutics_rehab: "https://images.unsplash.com/photo-1576091160550-2173dba999ef?auto=format&fit=crop&w=800&q=80",
  diagnostic_imaging: "https://images.unsplash.com/photo-1516549655169-df83a0774514?auto=format&fit=crop&w=800&q=80",
  public_health_emergency: "https://images.unsplash.com/photo-1587745416684-47953f16f02f?auto=format&fit=crop&w=800&q=80",
};
const FALLBACK_BANNER = "https://images.unsplash.com/photo-1532938911079-1b06ac7ceec7?auto=format&fit=crop&w=800&q=80";

function getBannerUrl(disciplines: string[] | undefined): string {
  if (!disciplines || disciplines.length === 0) return FALLBACK_BANNER;
  const first = disciplines[0].toLowerCase();
  return DISCIPLINE_BANNERS[first] ?? FALLBACK_BANNER;
}

export const ScholarshipFeed = ({ results, isPremium, profile, onTrack, onUnlock }: ScholarshipFeedProps) => {
  const [tracking, setTracking] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"cards" | "list">("cards");
  // Read-only preview drawer opened by clicking a card / list row
  const [previewScholarship, setPreviewScholarship] = useState<MatchedScholarship | null>(null);
  // Feed curation: ids animating out, ids fully hidden, and undo toast state
  const [fadingIds, setFadingIds] = useState<Set<string>>(new Set());
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  const [undoToast, setUndoToast] = useState<{ id: string; title: string } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Rapid-fire triage: index of the keyboard-focused card/row
  const [selectedCardIndex, setSelectedCardIndex] = useState(0);
  const cardRefs = useRef<Map<string, HTMLElement>>(new Map());

  const handleTrack = useCallback(async (scholarshipId: string) => {
    setTracking(scholarshipId);
    try {
      await api.trackScholarship({ scholarship_id: scholarshipId });
      onTrack?.(scholarshipId);
    } finally {
      setTracking(null);
    }
  }, [onTrack]);

  const handleDismiss = useCallback(async (scholarshipId: string, title: string) => {
    // Optimistic: fade & collapse the card immediately
    setFadingIds((prev) => new Set(prev).add(scholarshipId));
    setTimeout(() => {
      setHiddenIds((prev) => new Set(prev).add(scholarshipId));
      setFadingIds((prev) => {
        const next = new Set(prev);
        next.delete(scholarshipId);
        return next;
      });
    }, 300);

    // Show undo toast (auto-dismiss after 6s)
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setUndoToast({ id: scholarshipId, title });
    toastTimer.current = setTimeout(() => setUndoToast(null), 6000);

    try {
      await api.dismissScholarship(scholarshipId);
    } catch {
      // Revert on failure
      setHiddenIds((prev) => {
        const next = new Set(prev);
        next.delete(scholarshipId);
        return next;
      });
      setFadingIds((prev) => {
        const next = new Set(prev);
        next.delete(scholarshipId);
        return next;
      });
      setUndoToast(null);
    }
  }, []);

  const handleUndo = useCallback(async () => {
    if (!undoToast) return;
    const { id } = undoToast;
    setUndoToast(null);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    try {
      await api.undismissScholarship(id);
    } catch {
      // Even if the API call fails, restore locally so the user isn't stuck
    }
    setHiddenIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, [undoToast]);

  const visibleResults = results.filter((s) => !hiddenIds.has(s.scholarship_id));

  // Keep the pointer in range as cards are dismissed / results refresh.
  const clampedIndex = Math.min(selectedCardIndex, Math.max(0, visibleResults.length - 1));
  const focusedId = visibleResults[clampedIndex]?.scholarship_id ?? null;

  // Global keyboard triage: J/↓ next, K/↑ previous, S save, X dismiss.
  // Disabled while the preview drawer is open so its own controls win.
  useEffect(() => {
    if (previewScholarship) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      if (visibleResults.length === 0) return;

      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      const move = (delta: number) => {
        e.preventDefault();
        setSelectedCardIndex((prev) => {
          const next = Math.min(
            Math.max(0, Math.min(prev, visibleResults.length - 1) + delta),
            visibleResults.length - 1,
          );
          const el = cardRefs.current.get(visibleResults[next].scholarship_id);
          el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
          return next;
        });
      };

      const current = visibleResults[clampedIndex];
      switch (key) {
        case "ArrowDown":
        case "j":
          move(1);
          break;
        case "ArrowUp":
        case "k":
          move(-1);
          break;
        case "s":
          if (!current || (current.is_locked && !isPremium)) return;
          e.preventDefault();
          if (tracking !== current.scholarship_id) void handleTrack(current.scholarship_id);
          break;
        case "x":
          if (!current) return;
          e.preventDefault();
          void handleDismiss(current.scholarship_id, current.title);
          break;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [visibleResults, clampedIndex, previewScholarship, isPremium, tracking, handleTrack, handleDismiss]);

  const registerCard = useCallback((id: string, el: HTMLElement | null) => {
    if (el) cardRefs.current.set(id, el);
    else cardRefs.current.delete(id);
  }, []);

  if (visibleResults.length === 0) {
    return (
      <div className="rounded-2xl bg-cardBg p-8 text-center text-textSecondary">
        No scholarships matched your profile yet. Try broadening your criteria
        or check back after new scholarships are ingested.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Toolbar: result count + view mode toggle */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="text-sm text-slate-500">
            {visibleResults.length} scholarship{visibleResults.length === 1 ? "" : "s"}
          </p>
          <p className="hidden text-xs text-slate-400 font-mono sm:block" aria-hidden="true">
            Press <kbd className="rounded border border-slate-200 bg-slate-50 px-1">S</kbd> to save,{" "}
            <kbd className="rounded border border-slate-200 bg-slate-50 px-1">X</kbd> to dismiss,{" "}
            <kbd className="rounded border border-slate-200 bg-slate-50 px-1">↓</kbd>/<kbd className="rounded border border-slate-200 bg-slate-50 px-1">↑</kbd> to navigate
          </p>
        </div>
        <div className="inline-flex p-1 rounded-xl bg-slate-100 border border-slate-200/80">
          <button
            onClick={() => setViewMode("cards")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition ${
              viewMode === "cards"
                ? "bg-white text-slate-900 shadow-xs font-semibold"
                : "text-slate-500 hover:text-slate-700"
            }`}
            aria-label="Card view"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
            </svg>
            Cards
          </button>
          <button
            onClick={() => setViewMode("list")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition ${
              viewMode === "list"
                ? "bg-white text-slate-900 shadow-xs font-semibold"
                : "text-slate-500 hover:text-slate-700"
            }`}
            aria-label="List view"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <line x1="8" y1="6" x2="21" y2="6" />
              <line x1="8" y1="12" x2="21" y2="12" />
              <line x1="8" y1="18" x2="21" y2="18" />
              <line x1="3" y1="6" x2="3.01" y2="6" />
              <line x1="3" y1="12" x2="3.01" y2="12" />
              <line x1="3" y1="18" x2="3.01" y2="18" />
            </svg>
            List
          </button>
        </div>
      </div>

      {viewMode === "cards"
        ? visibleResults.map((s, i) => (
            <ScholarshipCard
              key={s.scholarship_id}
              scholarship={s}
              isPremium={isPremium}
              onTrack={handleTrack}
              onUnlock={onUnlock}
              onDismiss={handleDismiss}
              onOpen={setPreviewScholarship}
              tracking={tracking === s.scholarship_id}
              fading={fadingIds.has(s.scholarship_id)}
              focused={s.scholarship_id === focusedId}
              onFocusCard={() => setSelectedCardIndex(i)}
              registerRef={registerCard}
              index={i}
            />
          ))
        : visibleResults.map((s, i) => (
            <ScholarshipListItem
              key={s.scholarship_id}
              scholarship={s}
              isPremium={isPremium}
              onTrack={handleTrack}
              onUnlock={onUnlock}
              onDismiss={handleDismiss}
              onOpen={setPreviewScholarship}
              tracking={tracking === s.scholarship_id}
              fading={fadingIds.has(s.scholarship_id)}
              focused={s.scholarship_id === focusedId}
              onFocusCard={() => setSelectedCardIndex(i)}
              registerRef={registerCard}
            />
          ))}

      {/* Read-only preview drawer */}
      <ApplicationDrawer
        mode="preview"
        scholarship={previewScholarship}
        profile={profile}
        isOpen={!!previewScholarship}
        saving={!!previewScholarship && tracking === previewScholarship.scholarship_id}
        onSave={async () => {
          if (!previewScholarship) return;
          await handleTrack(previewScholarship.scholarship_id);
          setPreviewScholarship(null);
        }}
        onClose={() => setPreviewScholarship(null)}
      />

      {/* Undo toast */}
      {undoToast && (
        <div className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full bg-textPrimary px-5 py-3 text-sm text-surfaceBg shadow-xl">
          <span className="max-w-[240px] truncate">
            Hidden from your feed
          </span>
          <button
            onClick={handleUndo}
            className="font-semibold text-aquamarine hover:underline"
          >
            Undo
          </button>
        </div>
      )}
    </div>
  );
};

function ScholarshipCard({
  scholarship,
  isPremium,
  onTrack,
  onUnlock,
  onDismiss,
  onOpen,
  tracking,
  fading,
  focused,
  onFocusCard,
  registerRef,
  index = 0,
}: {
  scholarship: MatchedScholarship;
  isPremium: boolean;
  onTrack: (id: string) => void;
  onUnlock?: () => void;
  onDismiss: (id: string, title: string) => void;
  onOpen: (scholarship: MatchedScholarship) => void;
  tracking: boolean;
  fading: boolean;
  focused: boolean;
  onFocusCard: () => void;
  registerRef: (id: string, el: HTMLElement | null) => void;
  index?: number;
}) {
  const [imgLoaded, setImgLoaded] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState<"broken_link" | "inaccurate_deadline" | "expired">("broken_link");
  const [reportSubmitted, setReportSubmitted] = useState(false);
  const locked = scholarship.is_locked && !isPremium;
  const bannerUrl = getBannerUrl(scholarship.eligible_disciplines);
  const providerInitial = (scholarship.provider?.trim()?.charAt(0) || "G").toUpperCase();

  const handleReport = async () => {
    try {
      await api.reportScholarship(scholarship.scholarship_id, reportReason);
      setReportSubmitted(true);
      setReportOpen(false);
    } catch {
      // Best-effort
    }
  };

  const openPreview = () => {
    if (!locked) onOpen(scholarship);
  };

  return (
    <article
      ref={(el) => registerRef(scholarship.scholarship_id, el)}
      data-tour={index === 0 ? "match-card" : undefined}
      onClick={openPreview}
      onMouseEnter={onFocusCard}
      onFocus={onFocusCard}
      onKeyDown={(e) => {
        if (!locked && (e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) {
          e.preventDefault();
          openPreview();
        }
      }}
      role={locked ? undefined : "button"}
      tabIndex={locked ? undefined : 0}
      aria-label={locked ? undefined : `View details for ${scholarship.title}`}
      aria-current={focused ? "true" : undefined}
      className={`bg-white/95 rounded-2xl border border-slate-200/90 shadow-[0_4px_20px_-4px_rgba(15,23,42,0.06)] hover:shadow-[0_12px_32px_-6px_rgba(74,143,231,0.18)] hover:-translate-y-1 hover:border-slate-300 transition-all duration-200 flex flex-col relative ${
        locked ? "ring-1 ring-textSecondary/10" : "cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-skyAqua"
      } ${focused && !locked ? "ring-2 ring-blueEnergy/60" : ""} ${
        fading ? "opacity-0 scale-95 max-h-0 pointer-events-none overflow-hidden" : "opacity-100"
      }`}
    >
      {/* Discipline banner image — explicit height + shimmer placeholder to prevent CLS */}
      <div className="relative h-24 w-full overflow-hidden rounded-t-2xl bg-slate-100">
        {/* Shimmer placeholder — visible until image loads */}
        {!imgLoaded && (
          <div className="absolute inset-0 animate-pulse bg-gradient-to-r from-slate-100 via-slate-200 to-slate-100" />
        )}
        {/* eslint-disable-next-line @next/next/no-img-element -- external CDN image */}
        <img
          src={bannerUrl}
          alt=""
          className={`object-cover w-full h-full transition-opacity duration-300 ${
            imgLoaded ? "opacity-100" : "opacity-0"
          }`}
          loading="lazy"
          onLoad={() => setImgLoaded(true)}
          onError={(e) => {
            const img = e.currentTarget;
            if (img.src !== FALLBACK_BANNER) {
              img.src = FALLBACK_BANNER;
            } else {
              setImgLoaded(true);
            }
          }}
        />
        {/* Darkened gradient overlay anchored to bottom for text contrast */}
        <div className="absolute inset-0 bg-gradient-to-t from-slate-950/80 via-slate-950/25 to-transparent" />
      </div>

      {/* Provider avatar — crisp 44x44 tile overlapping the banner */}
      <div className="relative z-10 -mt-6 ml-5">
        <div className="h-11 w-11 rounded-xl bg-gradient-to-br from-crayolaBlue to-blueEnergy text-white font-bold shadow-md ring-2 ring-white flex items-center justify-center text-sm">
          {providerInitial}
        </div>
      </div>

      {/* Card body */}
      <div className="px-5 pb-5 pt-3">
        {/* Score badge + title row */}
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            {locked ? (
              <>
                <h3 className="font-serif text-lg font-semibold text-textPrimary/40 blur-[3px] select-none">
                  {scholarship.masked_title ?? scholarship.title}
                </h3>
                <p className="mt-0.5 text-sm text-textSecondary/50 blur-[3px] select-none">
                  {scholarship.masked_provider ?? scholarship.provider}
                </p>
              </>
            ) : (
              <>
                <h3 className="font-serif text-slate-900 font-bold text-lg leading-snug tracking-tight hover:text-blueEnergy transition-colors">
                  {scholarship.title}
                </h3>
                <p className="mt-0.5 text-slate-500 font-semibold text-xs tracking-wider uppercase">
                  {scholarship.provider}
                </p>
                {/* Metro restriction badges — soft glowing pills */}
                {scholarship.metro_restrictions?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {scholarship.metro_restrictions.map((m) => (
                      <span
                        key={m}
                        className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold text-surfaceBg"
                        style={{ backgroundColor: "#4A8FE7" }}
                      >
                        <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd" />
                        </svg>
                        {getMetroShortName(m)} Area
                      </span>
                    ))}
                  </div>
                )}
                {/* Employer benefit & service-obligation chips */}
                {(scholarship.has_service_commitment ||
                  scholarship.funding_type === "tuition_reimbursement" ||
                  scholarship.funding_type === "employer_sponsorship" ||
                  scholarship.employment_required) && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {scholarship.has_service_commitment && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2.5 py-1 text-xs font-semibold text-violet-800">
                        <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                          <path d="M9 12l2 2 4-4" />
                          <path fillRule="evenodd" d="M3 10a7 7 0 1114 0 7 7 0 01-14 0zm7-5a5 5 0 100 10 5 5 0 000-10z" clipRule="evenodd" />
                        </svg>
                        Service Obligation
                      </span>
                    )}
                    {(scholarship.funding_type === "tuition_reimbursement" ||
                      scholarship.funding_type === "employer_sponsorship" ||
                      scholarship.employment_required) && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-800">
                        <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                          <path d="M4 4a2 2 0 012-2h8a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
                          <path d="M7 8h6v2H7z" />
                        </svg>
                        Employer Benefit
                      </span>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
          <div className="flex shrink-0 items-start gap-2">
            <ScorePopover scholarship={scholarship} label={`${scholarship.score}% Match`} />
            {/* Hide / dismiss button (Lucide EyeOff) */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDismiss(scholarship.scholarship_id, scholarship.title);
              }}
              className="rounded-lg p-1.5 text-textSecondary/40 transition hover:bg-slate-100 hover:text-textSecondary"
              aria-label="Hide this scholarship"
              title="Hide from my feed"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                viewBox="0 0 24 24"
              >
                <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
                <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
                <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
                <line x1="2" x2="22" y1="2" y2="22" />
              </svg>
            </button>
          </div>
        </div>

        {locked ? (
          /* Paywall overlay */
          <div className="mt-4 rounded-xl bg-surfaceBg/90 p-4 text-center backdrop-blur-md">
            <span className="inline-block rounded-full bg-blueEnergy px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
              Pro Only
            </span>
            <p className="mt-2 text-sm font-medium text-textPrimary">
              Unlock this scholarship
            </p>
            <p className="mt-1 text-xs text-textSecondary">
              Upgrade to Premium for full details, provider info, and application links.
            </p>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onUnlock?.();
              }}
              className="mt-3 rounded-full bg-gradient-to-r from-aquamarine to-neonIce px-5 py-2 text-sm font-semibold text-textPrimary transition hover:opacity-90"
            >
              Unlock with Premium
            </button>
          </div>
        ) : (
          <>
            {/* Details */}
            <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <span className="text-textSecondary">
                Award:{" "}
                <span className="font-semibold text-textPrimary">
                  {scholarship.award_amount > 0
                    ? `$${scholarship.award_amount.toLocaleString()}`
                    : "Varies"}
                </span>
              </span>
              <span className="text-textSecondary">
                Deadline:{" "}
                <span className="font-semibold text-textPrimary">
                  {scholarship.deadline || "Rolling"}
                </span>
              </span>
            </div>

            {/* Missing criteria — clickable resolver chips */}
            {scholarship.missing_criteria.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {scholarship.missing_criteria.map((c) => (
                  <GapChip key={c} criterion={c} portalUrl={scholarship.portal_url} />
                ))}
              </div>
            )}

            {/* Actions */}
            <div className="mt-4 flex gap-3">
              {scholarship.portal_url && (
                <a
                  href={scholarship.portal_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="rounded-full bg-crayolaBlue px-5 py-2 text-sm font-medium text-surfaceBg hover:bg-blueEnergy"
                >
                  Apply
                </a>
              )}
              <button
                data-tour={index === 0 ? "save-btn" : undefined}
                onClick={(e) => {
                  e.stopPropagation();
                  onTrack(scholarship.scholarship_id);
                }}
                disabled={tracking}
                className="rounded-full border border-textSecondary/20 px-5 py-2 text-sm font-medium text-textSecondary hover:border-crayolaBlue hover:text-textPrimary disabled:opacity-50"
              >
                {tracking ? "Saving\u2026" : "Save to Kanban"}
              </button>
            </div>

            {/* Report inaccurate info — wrapper stops propagation so the
                select/buttons never open the preview drawer */}
            <div className="mt-3" onClick={(e) => e.stopPropagation()}>
              {reportSubmitted ? (
                <p className="text-xs text-aquamarine">✓ Report submitted — thank you!</p>
              ) : reportOpen ? (
                <div className="flex items-center gap-2">
                  <select
                    value={reportReason}
                    onChange={(e) => setReportReason(e.target.value as typeof reportReason)}
                    className="rounded-lg border border-textSecondary/20 px-2 py-1 text-xs text-textPrimary"
                  >
                    <option value="broken_link">Broken link</option>
                    <option value="inaccurate_deadline">Wrong deadline</option>
                    <option value="expired">Expired</option>
                  </select>
                  <button
                    onClick={handleReport}
                    className="rounded-lg bg-crayolaBlue px-3 py-1 text-xs font-medium text-surfaceBg"
                  >
                    Submit
                  </button>
                  <button
                    onClick={() => setReportOpen(false)}
                    className="text-xs text-textSecondary hover:text-textPrimary"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setReportOpen(true)}
                  className="text-xs text-textSecondary/50 hover:text-crayolaBlue hover:underline"
                >
                  ⚑ Report inaccurate info
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Compact List / Row Item
// ---------------------------------------------------------------------------

function ScholarshipListItem({
  scholarship,
  isPremium,
  onTrack,
  onUnlock,
  onDismiss,
  onOpen,
  tracking,
  fading,
  focused,
  onFocusCard,
  registerRef,
}: {
  scholarship: MatchedScholarship;
  isPremium: boolean;
  onTrack: (id: string) => void;
  onUnlock?: () => void;
  onDismiss: (id: string, title: string) => void;
  onOpen: (scholarship: MatchedScholarship) => void;
  tracking: boolean;
  fading: boolean;
  focused: boolean;
  onFocusCard: () => void;
  registerRef: (id: string, el: HTMLElement | null) => void;
}) {
  const locked = scholarship.is_locked && !isPremium;
  const openPreview = () => {
    if (!locked) onOpen(scholarship);
  };
  const providerInitial = (scholarship.provider?.trim()?.charAt(0) || "G").toUpperCase();
  const firstDiscipline = scholarship.eligible_disciplines?.[0];

  // Days-left countdown
  const daysLeft = (() => {
    if (!scholarship.deadline) return null;
    const d = new Date(scholarship.deadline);
    if (isNaN(d.getTime())) return null;
    const diff = Math.ceil((d.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
    return diff;
  })();

  return (
    <article
      ref={(el) => registerRef(scholarship.scholarship_id, el)}
      onClick={openPreview}
      onMouseEnter={onFocusCard}
      onFocus={onFocusCard}
      onKeyDown={(e) => {
        if (!locked && (e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) {
          e.preventDefault();
          openPreview();
        }
      }}
      role={locked ? undefined : "button"}
      tabIndex={locked ? undefined : 0}
      aria-label={locked ? undefined : `View details for ${scholarship.title}`}
      aria-current={focused ? "true" : undefined}
      className={`bg-white rounded-xl border border-slate-200/90 shadow-xs hover:border-slate-300 hover:shadow-sm transition-all duration-150 p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 group ${
        locked ? "" : "cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-skyAqua"
      } ${focused && !locked ? "ring-2 ring-blueEnergy/60" : ""} ${
        fading ? "opacity-0 scale-95 max-h-0 pointer-events-none" : "opacity-100"
      }`}
    >
      {locked ? (
        /* Paywalled list row — blurred with centered lock badge */
        <div className="flex flex-1 items-center justify-center py-2">
          <div className="flex items-center gap-3 text-slate-400">
            <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            <span className="text-sm font-medium blur-[2px] select-none">
              {scholarship.masked_title ?? scholarship.title}
            </span>
            <span className="inline-block rounded-full bg-blueEnergy px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
              Pro Only
            </span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onUnlock?.();
              }}
              className="rounded-full bg-gradient-to-r from-aquamarine to-neonIce px-4 py-1.5 text-xs font-semibold text-textPrimary transition hover:opacity-90"
            >
              Unlock with Premium
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* Left column — identity & details */}
          <div className="min-w-0 flex-1">
            {/* Provider row */}
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 bg-gradient-to-br from-crayolaBlue to-blueEnergy text-white rounded-lg font-bold text-xs flex items-center justify-center shrink-0">
                {providerInitial}
              </div>
              <span className="text-slate-500 text-xs font-semibold tracking-wider uppercase truncate">
                {scholarship.provider}
              </span>
              {firstDiscipline && (
                <span className="shrink-0 rounded-full bg-slate-100 border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-600 capitalize">
                  {firstDiscipline.replace(/_/g, " ")}
                </span>
              )}
              {scholarship.has_service_commitment && (
                <span className="shrink-0 rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold text-violet-800">
                  Service Obligation
                </span>
              )}
              {(scholarship.funding_type === "tuition_reimbursement" ||
                scholarship.funding_type === "employer_sponsorship" ||
                scholarship.employment_required) && (
                <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
                  Employer Benefit
                </span>
              )}
            </div>

            {/* Title */}
            <h3 className="mt-1.5 font-serif text-slate-900 font-bold text-base leading-snug group-hover:text-blueEnergy transition-colors">
              {scholarship.title}
            </h3>

            {/* Metadata strip */}
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
              <span className="text-blueEnergy font-bold text-sm">
                {scholarship.award_amount > 0
                  ? `$${scholarship.award_amount.toLocaleString()}`
                  : "Varies"}
              </span>
              <span className="text-slate-500">
                {scholarship.deadline || "Rolling"}
                {daysLeft !== null && daysLeft >= 0 && (
                  <span className={`ml-1 font-medium ${daysLeft <= 7 ? "text-amber-600" : "text-slate-400"}`}>
                    ({daysLeft}d left)
                  </span>
                )}
              </span>
              {scholarship.missing_criteria.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {scholarship.missing_criteria.slice(0, 3).map((c) => (
                    <GapChip key={c} criterion={c} portalUrl={scholarship.portal_url} compact />
                  ))}
                  {scholarship.missing_criteria.length > 3 && (
                    <span className="text-xs text-slate-400">
                      +{scholarship.missing_criteria.length - 3} more
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Right column — score & actions */}
          <div className="flex shrink-0 items-center gap-3">
            <ScorePopover scholarship={scholarship} label={`${scholarship.score}%`} compact />

            <div className="flex items-center gap-2">
              {scholarship.portal_url && (
                <a
                  href={scholarship.portal_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="rounded-full bg-blueEnergy hover:bg-[#3b7ed6] text-white font-medium px-4 py-1.5 text-xs transition-colors"
                >
                  Apply
                </a>
              )}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onTrack(scholarship.scholarship_id);
                }}
                disabled={tracking}
                className="rounded-full border border-slate-200 px-4 py-1.5 text-xs font-medium text-slate-600 hover:border-slate-300 hover:text-slate-900 disabled:opacity-50 transition"
              >
                {tracking ? "Saving\u2026" : "Save"}
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDismiss(scholarship.scholarship_id, scholarship.title);
                }}
                className="rounded-lg p-1.5 text-slate-300 transition hover:bg-slate-100 hover:text-slate-600 opacity-0 group-hover:opacity-100"
                aria-label="Hide this scholarship"
                title="Hide from my feed"
              >
                <svg
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  viewBox="0 0 24 24"
                >
                  <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
                  <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
                  <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
                  <line x1="2" x2="22" y1="2" y2="22" />
                </svg>
              </button>
            </div>
          </div>
        </>
      )}
    </article>
  );
}

// ---------------------------------------------------------------------------
// "Why am I seeing this?" score breakdown popover
// ---------------------------------------------------------------------------
const SCORE_BUCKET_META: Record<ScoreBucket, { label: string; max: number }> = {
  gpa: { label: "GPA", max: 25 },
  geo: { label: "Geography", max: 25 },
  sai: { label: "Financial need", max: 25 },
  affiliations: { label: "Affiliations", max: 25 },
  local_boost: { label: "Local boost", max: 10 },
};

function ScorePopover({
  scholarship,
  label,
  compact = false,
}: {
  scholarship: MatchedScholarship;
  label: string;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const popoverId = useId();
  const breakdown = scholarship.score_breakdown;

  const bucketRows: { key: ScoreBucket; value: number }[] = breakdown
    ? (Object.entries(SCORE_BUCKET_META)
        .map(([key]) => ({
          key: key as ScoreBucket,
          value: breakdown[key as ScoreBucket] ?? 0,
        }))
        .filter((r) => r.value > 0))
    : [];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={popoverId}
        aria-label="Why am I seeing this?"
        title="Why am I seeing this?"
        className={
          compact
            ? scholarship.score >= 80
              ? "bg-aquamarine text-slate-950 font-bold px-2.5 py-1 rounded-full text-xs shadow-xs"
              : "bg-slate-100 text-slate-800 border border-slate-200 font-semibold px-2.5 py-1 rounded-full text-xs"
            : scholarship.score >= 80
              ? "bg-aquamarine text-slate-950 font-bold px-3 py-1 rounded-full text-xs shadow-xs"
              : "bg-slate-100 text-slate-800 border border-slate-200 font-semibold px-3 py-1 rounded-full text-xs"
        }
      >
        {label}
      </button>
      {open && (
        <>
          {/* Click-away catcher */}
          <div
            className="fixed inset-0 z-40"
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
            }}
          />
          <div
            id={popoverId}
            role="dialog"
            onClick={(e) => e.stopPropagation()}
            className="absolute right-0 top-full z-50 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-xl"
          >
            <p className="font-serif text-sm font-semibold text-textPrimary">
              Why am I seeing this?
            </p>
            <p className="mt-0.5 text-xs text-textSecondary">
              Match score is based on your profile vs. scholarship criteria.
            </p>
            {bucketRows.length > 0 ? (
              <ul className="mt-2 space-y-1.5">
                {bucketRows.map(({ key, value }) => {
                  const meta = SCORE_BUCKET_META[key];
                  return (
                    <li key={key} className="flex items-center justify-between gap-2 text-xs">
                      <span className="text-slate-600">{meta.label}</span>
                      <span className="flex items-center gap-1.5">
                        <span className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                          <span
                            className="block h-full rounded-full bg-blueEnergy"
                            style={{ width: `${(value / meta.max) * 100}%` }}
                          />
                        </span>
                        <span className="font-semibold text-textPrimary">
                          +{value}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="mt-2 text-xs text-slate-500">
                Detailed breakdown unavailable for this result.
              </p>
            )}
            <p className="mt-2 border-t border-slate-100 pt-2 text-[11px] text-slate-400">
              Total: <span className="font-semibold text-textPrimary">{scholarship.score}</span>/100
            </p>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Missing-criteria resolver chip — opens a popover with a CTA to address gap
// ---------------------------------------------------------------------------
function GapChip({
  criterion,
  portalUrl,
  compact = false,
}: {
  criterion: string;
  portalUrl?: string | null;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const popoverId = useId();

  // Heuristic resolver suggestion based on the criterion text
  const suggestion = (() => {
    const c = criterion.toLowerCase();
    if (c.includes("gpa")) {
      return "Confirm your GPA in Profile settings — higher GPAs unlock more awards.";
    }
    if (c.includes("financial need") || c.includes("sai")) {
      return "Complete the FAFSA/SAI field in Profile to demonstrate financial need.";
    }
    if (c.includes("resident") || c.includes("area")) {
      return "Update your state/metro residence in Profile to verify eligibility.";
    }
    if (c.includes("affiliation")) {
      return "Add professional affiliations in Profile to match identity-based awards.";
    }
    if (c.includes("tag")) {
      return "Add hobbies/interests in Profile to surface more preferenced awards.";
    }
    return "Review your profile details to confirm eligibility for this criterion.";
  })();

  return (
    <div className="relative inline-flex">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={popoverId}
        title="How to resolve this gap"
        className={
          compact
            ? "bg-amber-50 text-amber-900 border border-amber-200/80 font-medium px-2.5 py-0.5 rounded-md text-xs hover:bg-amber-100"
            : "bg-amber-50 text-amber-900 border border-amber-200/80 font-medium px-2.5 py-0.5 rounded-md text-xs flex items-center gap-1.5 hover:bg-amber-100"
        }
      >
        {criterion}
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
            }}
          />
          <div
            id={popoverId}
            role="dialog"
            onClick={(e) => e.stopPropagation()}
            className="absolute left-0 top-full z-50 mt-1 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-xl"
          >
            <p className="font-serif text-sm font-semibold text-textPrimary">
              Resolve this gap
            </p>
            <p className="mt-1 text-xs text-textSecondary">{suggestion}</p>
            {portalUrl && (
              <a
                href={portalUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="mt-2 inline-block rounded-full bg-blueEnergy px-3 py-1 text-xs font-semibold text-white hover:opacity-90"
              >
                Open provider site
              </a>
            )}
          </div>
        </>
      )}
    </div>
  );
}

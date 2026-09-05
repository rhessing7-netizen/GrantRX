"use client";

import { useCallback, useRef, useState } from "react";
import type { MatchedScholarship } from "@/lib/types";
import { getMetroShortName } from "@/lib/constants/metros";
import { api } from "@/lib/api";

export type ScholarshipFeedProps = {
  results: MatchedScholarship[];
  isPremium: boolean;
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

export const ScholarshipFeed = ({ results, isPremium, onTrack, onUnlock }: ScholarshipFeedProps) => {
  const [tracking, setTracking] = useState<string | null>(null);
  // Feed curation: ids animating out, ids fully hidden, and undo toast state
  const [fadingIds, setFadingIds] = useState<Set<string>>(new Set());
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  const [undoToast, setUndoToast] = useState<{ id: string; title: string } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      {visibleResults.map((s) => (
        <ScholarshipCard
          key={s.scholarship_id}
          scholarship={s}
          isPremium={isPremium}
          onTrack={handleTrack}
          onUnlock={onUnlock}
          onDismiss={handleDismiss}
          tracking={tracking === s.scholarship_id}
          fading={fadingIds.has(s.scholarship_id)}
        />
      ))}

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
  tracking,
  fading,
}: {
  scholarship: MatchedScholarship;
  isPremium: boolean;
  onTrack: (id: string) => void;
  onUnlock?: () => void;
  onDismiss: (id: string, title: string) => void;
  tracking: boolean;
  fading: boolean;
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

  return (
    <article
      className={`bg-white rounded-2xl border border-slate-200 shadow-xs hover:shadow-md hover:border-slate-300 transition-all duration-200 overflow-hidden flex flex-col ${
        locked ? "ring-1 ring-textSecondary/10" : ""
      } ${fading ? "opacity-0 scale-95 max-h-0 pointer-events-none" : "opacity-100"}`}
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
        <div className="absolute inset-0 bg-gradient-to-t from-slate-950/60 via-transparent to-transparent" />
      </div>

      {/* Provider avatar — overlaps banner bottom-left and card body */}
      <div className="relative z-10 -mt-6 ml-5">
        <div className="h-11 w-11 flex items-center justify-center font-bold text-white text-sm rounded-xl ring-2 ring-white shadow-md bg-gradient-to-br from-crayolaBlue to-blueEnergy">
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
                <h3 className="font-serif text-slate-900 font-bold text-lg leading-snug">
                  {scholarship.title}
                </h3>
                <p className="mt-0.5 text-slate-600 font-medium text-xs tracking-wide uppercase">
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
              </>
            )}
          </div>
          <div className="flex shrink-0 items-start gap-2">
            <span
              className={
                scholarship.score >= 80
                  ? "bg-aquamarine text-slate-950 font-bold px-2.5 py-1 rounded-full text-xs shadow-xs"
                  : "bg-slate-100 text-slate-800 border border-slate-200 font-semibold px-2.5 py-1 rounded-full text-xs"
              }
            >
              {scholarship.score}% Match
            </span>
            {/* Hide / dismiss button (Lucide EyeOff) */}
            <button
              onClick={() => onDismiss(scholarship.scholarship_id, scholarship.title)}
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
              onClick={onUnlock}
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

            {/* Missing criteria — warm warning chips */}
            {scholarship.missing_criteria.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {scholarship.missing_criteria.map((c) => (
                  <span
                    key={c}
                    className="bg-amber-50 text-amber-900 border border-amber-200/80 font-medium px-2 py-0.5 rounded-md text-xs flex items-center gap-1.5"
                  >
                    {c}
                  </span>
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
                  className="rounded-full bg-crayolaBlue px-5 py-2 text-sm font-medium text-surfaceBg hover:bg-blueEnergy"
                >
                  Apply
                </a>
              )}
              <button
                onClick={() => onTrack(scholarship.scholarship_id)}
                disabled={tracking}
                className="rounded-full border border-textSecondary/20 px-5 py-2 text-sm font-medium text-textSecondary hover:border-crayolaBlue hover:text-textPrimary disabled:opacity-50"
              >
                {tracking ? "Saving\u2026" : "Save to Kanban"}
              </button>
            </div>

            {/* Report inaccurate info */}
            <div className="mt-3">
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

'use client';

import type { ShowcaseItem } from "@/lib/types";

/** Public Discovery Showcase — the signed-out Discover experience.
 *
 * Renders the real catalog sample served by GET /api/scholarships/showcase.
 * These are NOT personalized matches: no score, criteria, tracking, or any
 * user state is shown. Account-gated actions (Save, personalized details)
 * open the sign-in modal via onRequireAuth; Apply remains a plain public
 * external link to the provider portal.
 */

interface ShowcaseGridProps {
  items: ShowcaseItem[] | null;
  loading: boolean;
  /** True while the API client is running its single automatic retry. */
  retrying: boolean;
  failed: boolean;
  onRetry: () => void;
  onRequireAuth: () => void;
}

function formatDeadline(iso: string | null): string {
  if (!iso) return "No deadline listed";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return "No deadline listed";
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatFundingType(raw: string | null): string | null {
  if (!raw) return null;
  return raw
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** Same restrained trust indicator used on matched cards. */
function VerificationBadge({ status }: { status: string }) {
  const verified = status === "verified";
  return (
    <span
      title={
        verified
          ? "Key facts (title, award, deadline, GPA) were confirmed on the source page. Other criteria may not be independently verified."
          : "This listing's facts have not yet been independently verified against its source."
      }
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
        verified ? "bg-successSoft text-success" : "bg-surfaceSubtle text-textMuted"
      }`}
    >
      {verified ? (
        <svg className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      ) : null}
      {verified ? "Source verified" : "Verification pending"}
    </span>
  );
}

function ShowcaseCard({
  item,
  onRequireAuth,
}: {
  item: ShowcaseItem;
  onRequireAuth: () => void;
}) {
  const funding = formatFundingType(item.funding_type);
  const tags = [...item.matching_tags, ...item.metro_restrictions].slice(0, 3);
  return (
    <article className="bg-white/95 rounded-2xl border border-border/90 shadow-[0_4px_20px_-4px_rgba(15,23,42,0.06)] hover:shadow-[0_12px_32px_-6px_rgba(87,74,226,0.16)] hover:-translate-y-1 hover:border-border transition-all duration-200 flex flex-col overflow-hidden">
      {/* Banner + provider monogram — mirrors matched-card chrome without
          implying any personalization */}
      <div className="relative h-20 w-full bg-gradient-to-br from-primary/20 via-surfaceSubtle to-secondary/20">
        <div className="absolute inset-0 bg-gradient-to-t from-navy/50 via-navy/10 to-transparent" />
        <div className="absolute -bottom-4 left-5 h-11 w-11 rounded-xl bg-gradient-to-br from-primary to-secondary text-white font-bold shadow-md ring-2 ring-white flex items-center justify-center text-sm">
          {item.provider?.[0]?.toUpperCase() ?? "E"}
        </div>
      </div>
      <div className="flex flex-1 flex-col px-5 pb-5 pt-7">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="font-serif text-text break-words font-bold text-lg leading-snug tracking-tight">
              {item.title}
            </h3>
            <p className="mt-0.5 text-textMuted max-w-full break-words font-semibold text-xs tracking-wider uppercase">
              {item.provider}
            </p>
          </div>
          <VerificationBadge status={item.verification_status} />
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {item.award_amount != null && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary px-2.5 py-1 text-xs font-semibold text-surface">
              ${item.award_amount.toLocaleString()}
            </span>
          )}
          <span className="inline-flex items-center gap-1 rounded-full bg-accentSoft px-2.5 py-1 text-xs font-semibold text-secondary">
            {formatDeadline(item.deadline)}
          </span>
          {funding && (
            <span className="inline-flex items-center gap-1 rounded-full bg-surfaceSubtle px-2.5 py-1 text-xs font-semibold text-textMuted">
              {funding}
            </span>
          )}
          {item.has_service_commitment && (
            <span className="inline-flex items-center gap-1 rounded-full bg-surfaceSubtle px-2.5 py-1 text-xs font-semibold text-textMuted">
              Service commitment
            </span>
          )}
          {item.employment_required && (
            <span className="inline-flex items-center gap-1 rounded-full bg-surfaceSubtle px-2.5 py-1 text-xs font-semibold text-textMuted">
              Employment required
            </span>
          )}
          {tags.map((t) => (
            <span
              key={t}
              className="inline-flex items-center rounded-full border border-border px-2.5 py-1 text-xs font-medium text-textMuted"
            >
              {t}
            </span>
          ))}
        </div>

        <div className="mt-auto flex items-center gap-2 pt-4">
          <a
            href={item.portal_url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-surface transition hover:opacity-90"
          >
            Apply
          </a>
          <button
            type="button"
            onClick={onRequireAuth}
            className="rounded-full border border-border px-4 py-2 text-sm font-medium text-text transition hover:bg-surfaceSubtle"
          >
            Save
          </button>
        </div>
      </div>
    </article>
  );
}

function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-2xl border border-border/90 bg-white/95 p-5 shadow-[0_4px_20px_-4px_rgba(15,23,42,0.06)]">
      <div className="h-20 rounded-xl bg-textMuted/10" />
      <div className="mt-4 space-y-2">
        <div className="h-4 w-3/4 rounded bg-textMuted/10" />
        <div className="h-3 w-1/2 rounded bg-textMuted/10" />
        <div className="h-3 w-2/3 rounded bg-textMuted/10" />
        <div className="mt-3 flex gap-2">
          <div className="h-7 w-20 rounded-full bg-textMuted/10" />
          <div className="h-7 w-20 rounded-full bg-textMuted/10" />
        </div>
      </div>
    </div>
  );
}

export function ShowcaseGrid({
  items,
  loading,
  retrying,
  failed,
  onRetry,
  onRequireAuth,
}: ShowcaseGridProps) {
  return (
    <section
      aria-labelledby="showcase-heading"
      aria-busy={loading}
      className="space-y-4"
    >
      {/* Intro + CTA — public sample framing, not an error state */}
      <div className="rounded-2xl border border-border/70 bg-surfaceSubtle p-5">
        <h2
          id="showcase-heading"
          className="font-serif text-lg font-semibold text-text"
        >
          Sample opportunities
        </h2>
        <p className="mt-1 text-sm text-textMuted">
          Browse a sample of opportunities available through EdFintia. Create
          your free Funding Profile to see opportunities matched to you.
        </p>
        <button
          type="button"
          onClick={onRequireAuth}
          className="mt-3 rounded-full bg-primary px-5 py-2 text-sm font-medium text-surface transition hover:opacity-90"
        >
          Create Free Funding Profile
        </button>
      </div>

      {failed ? (
        <div className="rounded-2xl bg-surfaceSubtle p-8 text-center">
          <p className="text-textMuted">
            We&apos;re having trouble loading opportunities right now.
          </p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 rounded-full border border-primary px-5 py-2 text-sm font-medium text-primary transition hover:bg-primary/5"
          >
            Retry
          </button>
        </div>
      ) : loading && !items ? (
        <div className="space-y-4">
          {retrying && (
            <p className="text-center text-sm text-textMuted">
              Still waking up the server…
            </p>
          )}
          <div
            className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
            aria-label="Loading sample opportunities"
          >
            {[0, 1, 2].map((i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        </div>
      ) : items && items.length > 0 ? (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((item) => (
              <ShowcaseCard
                key={item.scholarship_id}
                item={item}
                onRequireAuth={onRequireAuth}
              />
            ))}
          </div>
          <p className="text-sm text-textMuted">
            Showing sample opportunities · Sign up free to get personalized
            matches
          </p>
        </>
      ) : (
        <div className="rounded-2xl bg-surfaceSubtle p-8 text-center">
          <p className="text-textMuted">
            New opportunities are being curated — check back soon, or create a
            free Funding Profile to be ready when matches arrive.
          </p>
          <button
            type="button"
            onClick={onRequireAuth}
            className="mt-3 rounded-full bg-primary px-5 py-2 text-sm font-medium text-surface transition hover:opacity-90"
          >
            Create Free Funding Profile
          </button>
        </div>
      )}
    </section>
  );
}

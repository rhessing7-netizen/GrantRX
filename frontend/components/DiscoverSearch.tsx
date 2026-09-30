"use client";

import type { Usage } from "@/lib/types";

export type DiscoverSearchProps = {
  search: string;
  onSearchChange: (v: string) => void;
  onKeywordSearch: () => void;
  onRefreshFeed: () => void;
  usage: Usage | null;
  onUpgrade?: () => void;
  idPrefix?: string;
  /** True while a search or refresh request is in flight. */
  busy?: boolean;
};

export function DiscoverSearch({
  search,
  onSearchChange,
  onKeywordSearch,
  onRefreshFeed,
  usage,
  onUpgrade,
  idPrefix = "ds",
  busy = false,
}: DiscoverSearchProps) {
  const hasText = search.trim().length > 0;
  const quotaExhausted =
    !!usage && !usage.is_premium && usage.remaining !== null && usage.remaining <= 0;
  const searchDisabled = hasText && quotaExhausted;
  const searchLimit = usage?.search_limit ?? 10;
  const inputId = `${idPrefix}-search`;
  const msgId = `${inputId}-msg`;

  const handleSubmit = () => {
    if (busy) return;
    if (hasText && !quotaExhausted) onKeywordSearch();
    else if (!hasText) onRefreshFeed();
  };

  return (
    <div className="space-y-3">
      <label htmlFor={inputId} className="text-sm font-medium text-textMuted">
        Keyword Search
      </label>
      <div className="relative">
        <input
          id={inputId}
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleSubmit();
            }
          }}
          placeholder="Keyword, provider, or tag"
          aria-describedby={searchDisabled ? msgId : undefined}
          disabled={busy}
          className="w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 pr-12 text-sm text-text placeholder:text-textMuted/50 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60"
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={searchDisabled || busy}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-2.5 text-textMuted transition hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
          aria-label={hasText ? "Search" : "Refresh matches"}
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </button>
      </div>

      {/* Primary CTA reflects what will actually happen: a keyword search when
          text is present, otherwise a free match refresh. */}
      <button
        type="button"
        onClick={handleSubmit}
        disabled={searchDisabled || busy}
        className="min-h-[44px] w-full rounded-full bg-primary py-2.5 text-sm font-semibold text-surface shadow-sm transition hover:bg-primaryHover active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy
          ? hasText
            ? "Searching…"
            : "Refreshing…"
          : searchDisabled
            ? "Keyword Search Limit Reached"
            : hasText
              ? "Search Opportunities"
              : "Refresh Matches"}
      </button>

      {/* Free refresh escape hatch — shown only while a keyword is entered so
          the two CTAs never perform the same action at once. */}
      {hasText && (
        <button
          type="button"
          onClick={onRefreshFeed}
          disabled={busy}
          className="min-h-[44px] w-full rounded-lg border border-border/70 bg-surfaceSubtle px-4 py-2 text-xs font-medium text-text transition hover:bg-border/80 disabled:opacity-50"
        >
          Refresh Matches (free — doesn&apos;t use a search)
        </button>
      )}

      {searchDisabled && (
        <p id={msgId} className="text-xs text-textMuted">
          You&apos;ve used all {searchLimit} free keyword searches this week.{" "}
          {onUpgrade && (
            <button onClick={onUpgrade} className="text-primary hover:underline">
              Upgrade to Premium
            </button>
          )}{" "}
          for unlimited keyword searches. Filter adjustments and match refreshes remain free.
        </p>
      )}
    </div>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import type { AppStatus, CalendarEvent } from "@/lib/types";
import { api } from "@/lib/api";

const STATUS_COLORS: Record<AppStatus, string> = {
  saved: "bg-textSecondary/20 text-textSecondary",
  in_progress: "bg-skyAqua text-surfaceBg",
  submitted: "bg-blueEnergy text-surfaceBg",
  awarded: "bg-aquamarine text-textPrimary",
  archived: "bg-textSecondary/10 text-textSecondary",
};

const STATUS_DOT: Record<AppStatus, string> = {
  saved: "bg-textSecondary/40",
  in_progress: "bg-skyAqua",
  submitted: "bg-blueEnergy",
  awarded: "bg-aquamarine",
  archived: "bg-textSecondary/20",
};

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export type DeadlineCalendarProps = {
  isPremium: boolean;
};

export function DeadlineCalendar(_props: DeadlineCalendarProps) {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [feedUrl, setFeedUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [view, setView] = useState<"month" | "week">("month");
  const [cursor, setCursor] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [evs, feed] = await Promise.all([
          api.getCalendarEvents(),
          api.getFeedUrl().catch(() => null),
        ]);
        if (!cancelled) {
          setEvents(evs);
          if (feed) setFeedUrl(feed.feed_url);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Group events by deadline date (YYYY-MM-DD)
  const eventsByDate = useMemo(() => {
    const map: Record<string, CalendarEvent[]> = {};
    for (const ev of events) {
      if (!ev.deadline) continue;
      const key = ev.deadline.slice(0, 10);
      (map[key] ??= []).push(ev);
    }
    return map;
  }, [events]);

  const handleCopyFeed = async () => {
    if (!feedUrl) return;
    try {
      await navigator.clipboard.writeText(feedUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      // Fallback for older browsers
      const input = document.createElement("input");
      input.value = feedUrl;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    }
  };

  const navigate = (delta: number) => {
    if (view === "month") {
      setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + delta, 1));
    } else {
      setCursor(new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() + delta * 7));
    }
  };

  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl font-bold text-textPrimary">
            Deadline Calendar
          </h1>
          <p className="mt-1 text-sm text-textSecondary">
            Track scholarship deadlines with color-coded status indicators.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* View toggle */}
          <div className="flex rounded-full border border-textSecondary/20 p-0.5">
            <button
              onClick={() => setView("month")}
              className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
                view === "month" ? "bg-crayolaBlue text-surfaceBg" : "text-textSecondary"
              }`}
            >
              Month
            </button>
            <button
              onClick={() => setView("week")}
              className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
                view === "week" ? "bg-crayolaBlue text-surfaceBg" : "text-textSecondary"
              }`}
            >
              Week
            </button>
          </div>

          {/* Sync button */}
          <button
            onClick={handleCopyFeed}
            disabled={!feedUrl}
            className="rounded-full bg-gradient-to-r from-aquamarine to-neonIce px-5 py-2 text-sm font-semibold text-textPrimary disabled:opacity-50"
          >
            {copied ? "✓ Copied!" : "Sync to Calendar"}
          </button>
        </div>
      </div>

      {/* Feed URL display */}
      {feedUrl && (
        <div className="rounded-xl bg-cardBg p-3">
          <p className="text-xs text-textSecondary">
            .ics subscription URL (paste into Apple Calendar → New Subscription, Google Calendar → Add by URL, or Outlook → Import):
          </p>
          <code className="mt-1 block truncate text-xs text-textPrimary">{feedUrl}</code>
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate(-1)}
          className="rounded-full border border-textSecondary/20 px-4 py-1.5 text-sm text-textSecondary hover:border-crayolaBlue"
        >
          ‹ {view === "month" ? "Prev Month" : "Prev Week"}
        </button>
        <h2 className="font-serif text-lg font-semibold text-textPrimary">
          {view === "month"
            ? `${MONTHS[cursor.getMonth()]} ${cursor.getFullYear()}`
            : `Week of ${cursor.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`}
        </h2>
        <button
          onClick={() => navigate(1)}
          className="rounded-full border border-textSecondary/20 px-4 py-1.5 text-sm text-textSecondary hover:border-crayolaBlue"
        >
          {view === "month" ? "Next Month" : "Next Week"} ›
        </button>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 text-xs text-textSecondary">
        {(["saved", "in_progress", "submitted", "awarded"] as AppStatus[]).map((s) => (
          <span key={s} className="flex items-center gap-1.5">
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${STATUS_DOT[s]}`} />
            {s.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase())}
          </span>
        ))}
      </div>

      {/* Calendar grid */}
      {loading ? (
        <div className="rounded-2xl bg-cardBg p-8 text-center text-textSecondary">
          Loading calendar…
        </div>
      ) : view === "month" ? (
        <MonthGrid
          cursor={cursor}
          eventsByDate={eventsByDate}
          todayKey={todayKey}
        />
      ) : (
        <WeekGrid
          cursor={cursor}
          eventsByDate={eventsByDate}
          todayKey={todayKey}
        />
      )}

      {/* Upcoming list */}
      <UpcomingList events={events} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Month grid
// ---------------------------------------------------------------------------

function MonthGrid({
  cursor,
  eventsByDate,
  todayKey,
}: {
  cursor: Date;
  eventsByDate: Record<string, CalendarEvent[]>;
  todayKey: string;
}) {
  const year = cursor.getFullYear();
  const month = cursor.getMonth();
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells: (Date | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));
  while (cells.length % 7 !== 0) cells.push(null);

  return (
    <div className="overflow-hidden rounded-2xl border border-textSecondary/10 bg-cardBg">
      <div className="grid grid-cols-7 border-b border-textSecondary/10">
        {WEEKDAYS.map((d) => (
          <div key={d} className="px-2 py-2 text-center text-xs font-medium text-textSecondary">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {cells.map((date, i) => {
          if (!date) return <div key={i} className="min-h-[80px] border-b border-r border-textSecondary/5" />;
          const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
          const dayEvents = eventsByDate[key] ?? [];
          const isToday = key === todayKey;

          return (
            <div
              key={i}
              className={`min-h-[80px] border-b border-r border-textSecondary/5 p-1.5 ${
                isToday ? "bg-aquamarine/10" : ""
              }`}
            >
              <span
                className={`text-xs ${isToday ? "font-bold text-crayolaBlue" : "text-textSecondary"}`}
              >
                {date.getDate()}
              </span>
              <div className="mt-1 space-y-1">
                {dayEvents.slice(0, 3).map((ev) => (
                  <div
                    key={ev.tracking_id}
                    className={`truncate rounded px-1.5 py-0.5 text-[10px] font-medium ${STATUS_COLORS[ev.status]}`}
                    title={ev.title}
                  >
                    {ev.title}
                  </div>
                ))}
                {dayEvents.length > 3 && (
                  <p className="text-[10px] text-textSecondary">+{dayEvents.length - 3} more</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Week grid
// ---------------------------------------------------------------------------

function WeekGrid({
  cursor,
  eventsByDate,
  todayKey,
}: {
  cursor: Date;
  eventsByDate: Record<string, CalendarEvent[]>;
  todayKey: string;
}) {
  const startOfWeek = new Date(cursor);
  startOfWeek.setDate(cursor.getDate() - cursor.getDay());

  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(startOfWeek);
    d.setDate(startOfWeek.getDate() + i);
    return d;
  });

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-7">
      {days.map((date) => {
        const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
        const dayEvents = eventsByDate[key] ?? [];
        const isToday = key === todayKey;

        return (
          <div
            key={key}
            className={`rounded-xl border p-3 ${
              isToday ? "border-crayolaBlue bg-aquamarine/5" : "border-textSecondary/10 bg-cardBg"
            }`}
          >
            <p className={`text-xs font-medium ${isToday ? "text-crayolaBlue" : "text-textSecondary"}`}>
              {WEEKDAYS[date.getDay()]} {date.getDate()}
            </p>
            <div className="mt-2 space-y-2">
              {dayEvents.length === 0 && (
                <p className="text-xs text-textSecondary/40">No deadlines</p>
              )}
              {dayEvents.map((ev) => (
                <div key={ev.tracking_id} className="rounded-lg bg-surfaceBg p-2 shadow-sm">
                  <div className="flex items-center gap-1.5">
                    <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[ev.status]}`} />
                    <p className="truncate text-xs font-medium text-textPrimary">{ev.title}</p>
                  </div>
                  <p className="mt-0.5 text-[10px] text-textSecondary">
                    ${ev.award_amount.toLocaleString()} · {ev.provider}
                  </p>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upcoming deadlines list
// ---------------------------------------------------------------------------

function UpcomingList({ events }: { events: CalendarEvent[] }) {
  const sorted = useMemo(
    () =>
      [...events]
        .filter((e) => e.deadline)
        .sort((a, b) => a.deadline.localeCompare(b.deadline))
        .slice(0, 10),
    [events],
  );

  if (sorted.length === 0) return null;

  return (
    <div className="rounded-2xl bg-cardBg p-5">
      <h3 className="font-serif text-lg font-semibold text-textPrimary">
        Upcoming Deadlines
      </h3>
      <div className="mt-3 space-y-2">
        {sorted.map((ev) => (
          <div
            key={ev.tracking_id}
            className="flex items-center justify-between rounded-xl bg-surfaceBg px-4 py-2.5"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-textPrimary">
                {ev.title}
              </p>
              <p className="text-xs text-textSecondary">
                {ev.provider} · ${ev.award_amount.toLocaleString()}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[ev.status]}`}
              >
                {ev.status.replace("_", " ")}
              </span>
              <span className="text-sm font-semibold text-textPrimary">
                {ev.deadline.slice(5)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

"use client";

import { useMemo, useRef, useState } from "react";
import confetti from "canvas-confetti";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  closestCorners,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  useDraggable,
} from "@dnd-kit/core";
import type { AppStatus, UserScholarship } from "@/lib/types";
import { api } from "@/lib/api";
import { notifyTourKanbanAction } from "@/components/InteractiveTour";
import { ApplicationDrawer } from "./ApplicationDrawer";

const COLUMNS: { id: AppStatus; label: string; accent: string; emptyHint: string }[] = [
  { id: "saved", label: "Saved", accent: "border-textMuted/20", emptyHint: "Bookmark opportunities from the Discovery Feed and they'll show up here for tracking." },
  { id: "in_progress", label: "In Progress", accent: "border-accent", emptyHint: "Drag a saved opportunity here when you start working on your application." },
  { id: "submitted", label: "Submitted", accent: "border-secondary", emptyHint: "Once you've submitted an application, drag it here to track the outcome." },
  { id: "awarded", label: "Awarded", accent: "border-accentSoft", emptyHint: "Your wins will land here. Keep applying — every award counts!" },
];

const FREE_ACTIVE_LIMIT = 3;

function isActive(status: AppStatus) {
  return status === "in_progress" || status === "submitted";
}

export type KanbanBoardProps = {
  items: UserScholarship[];
  isPremium: boolean;
  onChanged?: () => void;
  onPaywall?: () => void;
};

export function KanbanBoard({ items, isPremium, onChanged, onPaywall }: KanbanBoardProps) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [paywallMsg, setPaywallMsg] = useState<string | null>(null);
  const [archiveConfirm, setArchiveConfirm] = useState<{ itemId: string; title: string } | null>(null);
  const [undoToast, setUndoToast] = useState<{ itemId: string; prevStatus: AppStatus; title: string } | null>(null);
  const [drawerItem, setDrawerItem] = useState<UserScholarship | null>(null);
  const [mobileStage, setMobileStage] = useState<AppStatus>("saved");

  // Milestone celebration toast
  const [milestone, setMilestone] = useState<{
    type: "submitted" | "awarded";
    title: string;
    itemId: string;
  } | null>(null);
  const [awardInput, setAwardInput] = useState<string>("");
  const [awardSubmitted, setAwardSubmitted] = useState(false);
  // Track the last item we celebrated so confetti only fires on a genuine
  // status transition, not on unrelated re-renders.
  const celebratedRef = useRef<Set<string>>(new Set());

  const fireConfetti = (type: "submitted" | "awarded") => {
    if (type === "awarded") {
      // Bigger celebration for an award win
      confetti({
        particleCount: 160,
        spread: 90,
        origin: { y: 0.7 },
        colors: ["#574AE2", "#654597", "#AB81CD", "#E2ADF2", "#222A68"],
      });
      setTimeout(
        () =>
          confetti({
            particleCount: 80,
            angle: 60,
            spread: 70,
            origin: { x: 0, y: 0.7 },
            colors: ["#574AE2", "#AB81CD", "#E2ADF2"],
          }),
        250,
      );
      setTimeout(
        () =>
          confetti({
            particleCount: 80,
            angle: 120,
            spread: 70,
            origin: { x: 1, y: 0.7 },
            colors: ["#574AE2", "#654597", "#E2ADF2"],
          }),
        450,
      );
    } else {
      // Smaller burst for a submission
      confetti({
        particleCount: 90,
        spread: 70,
        origin: { y: 0.75 },
        colors: ["#574AE2", "#AB81CD", "#E2ADF2", "#4A8FE7"],
      });
    }
  };

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  const grouped = useMemo(() => {
    const map: Record<AppStatus, UserScholarship[]> = {
      saved: [],
      in_progress: [],
      submitted: [],
      awarded: [],
      archived: [],
    };
    for (const item of items) {
      map[item.status]?.push(item);
    }
    return map;
  }, [items]);

  const activeCount = items.filter((i) => isActive(i.status)).length;
  const activeItem = activeId
    ? items.find((i) => i.id === activeId) ?? null
    : null;

  const handleDragStart = (e: DragStartEvent) => {
    setActiveId(e.active.id as string);
  };

  const applyStatusChange = async (item: UserScholarship, newStatus: AppStatus) => {
    if (item.status === newStatus) return;

    // Paywall: free users limited to 3 active applications
    if (!isPremium && isActive(newStatus) && !isActive(item.status)) {
      if (activeCount >= FREE_ACTIVE_LIMIT) {
        setPaywallMsg(
          `Free tier is limited to ${FREE_ACTIVE_LIMIT} active applications. Upgrade to Premium to track more.`,
        );
        return;
      }
    }

    // Confirmation for archiving
    if (newStatus === "archived") {
      const scholarship = item.scholarship;
      setArchiveConfirm({
        itemId: item.id,
        title: scholarship?.title ?? "this scholarship",
      });
      return;
    }

    // Optimistic update is handled by parent re-fetch; issue PATCH
    try {
      await api.updateTracking(item.id, { status: newStatus });
      onChanged?.();
      // Milestone celebration toasts + confetti
      if (newStatus === "submitted") {
        setMilestone({ type: "submitted", title: item.scholarship?.title ?? "scholarship", itemId: item.id });
        setTimeout(() => setMilestone(null), 6000);
        if (!celebratedRef.current.has(`${item.id}:submitted`)) {
          celebratedRef.current.add(`${item.id}:submitted`);
          fireConfetti("submitted");
        }
      } else if (newStatus === "awarded") {
        setMilestone({ type: "awarded", title: item.scholarship?.title ?? "scholarship", itemId: item.id });
        setAwardInput("");
        setAwardSubmitted(false);
        if (!celebratedRef.current.has(`${item.id}:awarded`)) {
          celebratedRef.current.add(`${item.id}:awarded`);
          fireConfetti("awarded");
        }
      }
    } catch (err) {
      console.error("Failed to update tracking", err);
    }
  };

  const handleDragEnd = async (e: DragEndEvent) => {
    setActiveId(null);
    const { active, over } = e;
    if (!over) return;

    const newStatus = over.id as AppStatus;
    const item = items.find((i) => i.id === active.id);
    if (!item) return;
    await applyStatusChange(item, newStatus);
  };

  const confirmArchive = async () => {
    if (!archiveConfirm) return;
    const item = items.find((i) => i.id === archiveConfirm.itemId);
    if (!item) {
      setArchiveConfirm(null);
      return;
    }
    const prevStatus = item.status;
    try {
      await api.updateTracking(item.id, { status: "archived" });
      onChanged?.();
      setUndoToast({
        itemId: item.id,
        prevStatus,
        title: archiveConfirm.title,
      });
      setTimeout(() => setUndoToast(null), 5000);
    } catch (err) {
      console.error("Failed to archive", err);
    }
    setArchiveConfirm(null);
  };

  const undoArchive = async () => {
    if (!undoToast) return;
    try {
      await api.updateTracking(undoToast.itemId, { status: undoToast.prevStatus });
      onChanged?.();
    } catch (err) {
      console.error("Failed to undo archive", err);
    }
    setUndoToast(null);
  };

  return (
    <div className="relative">
      {/* Undo toast */}
      {undoToast && (
        <div className="mb-4 flex items-center justify-between rounded-xl bg-secondary px-5 py-3 text-white shadow-md">
          <p className="text-sm font-medium">
            Archived &ldquo;{undoToast.title}&rdquo;
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={undoArchive}
              className="rounded-full bg-white/20 px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-white/30"
            >
              Undo
            </button>
            <button
              onClick={() => setUndoToast(null)}
              className="text-sm text-white/70 hover:text-white"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Milestone celebration toast — Submitted */}
      {milestone?.type === "submitted" && (
        <div className="mb-4 flex items-center justify-between rounded-xl bg-gradient-to-r from-accentSoft to-accent px-5 py-4 shadow-md">
          <div>
            <p className="text-sm font-bold text-text">
              Application Submitted!
            </p>
            <p className="mt-0.5 text-xs text-text/80">
              Great work taking action on your clinical education debt.
            </p>
          </div>
          <button
            onClick={() => setMilestone(null)}
            className="text-sm text-text/70 hover:text-text"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Milestone celebration toast — Awarded with award amount prompt */}
      {milestone?.type === "awarded" && (
        <div className="mb-4 rounded-xl bg-gradient-to-r from-accentSoft via-accent to-secondary px-5 py-4 shadow-lg">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm font-bold text-text">
                Awarded! Congratulations on winning funding!
              </p>
              <p className="mt-0.5 text-xs text-text/80">
                Log the award amount to keep your application notes accurate.
              </p>
            </div>
            <button
              onClick={() => setMilestone(null)}
              className="ml-3 shrink-0 text-sm text-text/70 hover:text-text"
            >
              Dismiss
            </button>
          </div>
          {!awardSubmitted ? (
            <div className="mt-3 flex items-center gap-2">
              <div className="relative flex-1 max-w-xs">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm font-medium text-text/60">$</span>
                <input
                  type="number"
                  value={awardInput}
                  onChange={(e) => setAwardInput(e.target.value)}
                  placeholder="Amount"
                  aria-label="Award amount in dollars"
                  className="w-full rounded-full border border-text/20 bg-surface pl-7 pr-3 py-1.5 text-sm text-text"
                />
              </div>
              <button
                onClick={() => {
                  const awarded = items.find((i) => i.id === milestone.itemId);
                  const amountText = `Award won: $${awardInput.trim()}`;
                  const existing = awarded?.application_notes?.trim();
                  void api
                    .updateTracking(milestone.itemId, {
                      application_notes: existing
                        ? `${existing}\n${amountText}`
                        : amountText,
                    })
                    .catch(() => undefined);
                  setAwardSubmitted(true);
                  setTimeout(() => setMilestone(null), 3000);
                }}
                disabled={!awardInput.trim()}
                className="rounded-full bg-text px-4 py-1.5 text-sm font-semibold text-surface disabled:opacity-40"
              >
                Save
              </button>
            </div>
          ) : (
            <p className="mt-2 text-xs font-medium text-text">
              ✓ Thank you for sharing your win!
            </p>
          )}
        </div>
      )}

      {/* Archive confirmation */}
      {archiveConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-text/40 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl bg-surface p-6 shadow-2xl">
            <h3 className="font-serif text-lg font-semibold text-text">
              Archive this application?
            </h3>
            <p className="mt-2 text-sm text-textMuted">
              &ldquo;{archiveConfirm.title}&rdquo; will be moved to Archived.
              You can undo this action right after.
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button
                onClick={() => setArchiveConfirm(null)}
                className="rounded-full border border-textMuted/20 px-4 py-2 text-sm font-medium text-textMuted hover:text-text"
              >
                Cancel
              </button>
              <button
                onClick={confirmArchive}
                className="rounded-full bg-secondary px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90"
              >
                Archive
              </button>
            </div>
          </div>
        </div>
      )}

      {paywallMsg && (
        <div className="mb-4 flex items-center justify-between rounded-xl bg-gradient-to-r from-accentSoft to-accent px-5 py-3">
          <p className="text-sm font-medium text-text">{paywallMsg}</p>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setPaywallMsg(null)}
              className="text-sm text-text/70 hover:text-text"
            >
              Dismiss
            </button>
            <button
              onClick={() => {
                setPaywallMsg(null);
                onPaywall?.();
              }}
              className="rounded-full bg-text px-4 py-1.5 text-sm font-semibold text-surface"
            >
              Upgrade
            </button>
          </div>
        </div>
      )}

      {/* Desktop board */}
      <div className="hidden lg:block">
        <DndContext
          sensors={sensors}
          collisionDetection={closestCorners}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {COLUMNS.map((col) => (
              <KanbanColumn
                key={col.id}
                id={col.id}
                label={col.label}
                accent={col.accent}
                emptyHint={col.emptyHint}
                items={grouped[col.id]}
                onOpenDrawer={setDrawerItem}
              />
            ))}
          </div>

          {/* Archived drop zone */}
          <div className="mt-4">
            <KanbanColumn
              id="archived"
              label="Archived"
              accent="border-textMuted/10"
              emptyHint="Drag grants here to archive them. You can undo right after."
              items={grouped.archived}
              onOpenDrawer={setDrawerItem}
            />
          </div>

          <DragOverlay>
            {activeItem ? (
              <KanbanCard item={activeItem} dragging onOpenDrawer={() => {}} />
            ) : null}
          </DragOverlay>
        </DndContext>
      </div>

      {/* Mobile pipeline: stage selector + vertical list */}
      <div className="space-y-4 lg:hidden">
        <div className="flex flex-wrap gap-2">
          {[...COLUMNS, { id: "archived" as AppStatus, label: "Archived" }].map((col) => (
            <button
              key={col.id}
              onClick={() => setMobileStage(col.id)}
              className={`rounded-full px-3 py-2 text-xs font-semibold transition ${
                mobileStage === col.id
                  ? "bg-primary text-surface"
                  : "bg-surfaceSubtle text-text hover:bg-surfaceSubtle/80"
              }`}
              aria-pressed={mobileStage === col.id}
            >
              {col.label}
              <span className="ml-1.5 rounded-full bg-text/10 px-1.5 py-0.5 text-[10px]">
                {grouped[col.id]?.length ?? 0}
              </span>
            </button>
          ))}
        </div>

        <div className="space-y-3">
          {grouped[mobileStage]?.length === 0 && (
            <p className="rounded-2xl bg-surfaceSubtle p-5 text-center text-sm text-textMuted">
              No {COLUMNS.find((c) => c.id === mobileStage)?.label.toLowerCase() ?? mobileStage} applications.
            </p>
          )}
          {grouped[mobileStage]?.map((item) => (
            <MobileKanbanCard
              key={item.id}
              item={item}
              onOpenDrawer={setDrawerItem}
              onMoveStage={(s) => applyStatusChange(item, s)}
            />
          ))}
        </div>
      </div>

      {/* Application Details & Documents drawer */}
      {drawerItem && (
        <ApplicationDrawer
          mode="vault"
          item={drawerItem}
          onClose={() => setDrawerItem(null)}
          onChanged={() => {
            onChanged?.();
            // Refresh the drawer item from the latest items list
            const updated = items.find((i) => i.id === drawerItem.id);
            if (updated) setDrawerItem(updated);
          }}
        />
      )}
    </div>
  );
}

function KanbanColumn({
  id,
  label,
  accent,
  emptyHint,
  items,
  onOpenDrawer,
}: {
  id: AppStatus;
  label: string;
  accent: string;
  emptyHint: string;
  items: UserScholarship[];
  onOpenDrawer: (item: UserScholarship) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });

  return (
    <div
      ref={setNodeRef}
      className={`rounded-2xl border-t-4 ${accent} bg-surfaceSubtle p-4 transition-all duration-150 ${
        isOver ? "ring-2 ring-accent bg-accent/5" : ""
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-serif text-sm font-semibold text-text">
          {label}
        </h3>
        <span className="rounded-full bg-textMuted/10 px-2 py-0.5 text-xs text-textMuted">
          {items.length}
        </span>
      </div>

      <div className="space-y-3">
        {items.length === 0 && (
          <div className="rounded-xl border border-dashed border-textMuted/15 py-8 px-4 text-center bg-white/50">
            <div className="mx-auto mb-3 h-12 w-12 bg-accent/10 border border-accent/20 flex items-center justify-center rounded-2xl text-secondary">
              <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
            </div>
            <p className="text-sm font-medium text-textMuted">
              Nothing here yet
            </p>
            <p className="mt-1 text-xs leading-relaxed text-textMuted/60">
              {emptyHint}
            </p>
          </div>
        )}
        {items.map((item) => (
          <KanbanCard key={item.id} item={item} onOpenDrawer={onOpenDrawer} />
        ))}
      </div>
    </div>
  );
}

function KanbanCard({
  item,
  dragging = false,
  onOpenDrawer,
}: {
  item: UserScholarship;
  dragging?: boolean;
  onOpenDrawer: (item: UserScholarship) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [notes, setNotes] = useState(item.user_notes ?? "");
  const [reminder, setReminder] = useState(
    item.custom_deadline_reminder ?? "",
  );
  const [saving, setSaving] = useState(false);

  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({ id: item.id });

  const style = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
      }
    : undefined;

  const scholarship = item.scholarship;
  const title = scholarship?.title ?? "Scholarship";
  const provider = scholarship?.provider ?? "";
  const amount = scholarship?.award_amount;
  const deadline = scholarship?.deadline ?? "";

  const handleSaveDetails = async () => {
    setSaving(true);
    try {
      await api.updateTracking(item.id, {
        user_notes: notes || null,
        custom_deadline_reminder: reminder || null,
      });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`rounded-xl bg-surface p-3.5 shadow-sm ${
        isDragging || dragging ? "opacity-60 shadow-lg" : ""
      } ${dragging ? "rotate-2" : ""}`}
    >
      {/* Drag handle header */}
      <div
        {...attributes}
        {...listeners}
        className="cursor-grab active:cursor-grabbing"
      >
        <h4 className="font-serif text-sm font-semibold leading-snug text-text">
          {title}
        </h4>
        {provider && (
          <p className="mt-0.5 text-xs text-textMuted">{provider}</p>
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-textMuted">
        {amount != null && (
          <span>
            <span className="font-semibold text-text">
              ${amount.toLocaleString()}
            </span>
          </span>
        )}
        {deadline && <span>Due: {deadline}</span>}
      </div>

      {/* Notes / reminder */}
      {editing ? (
        <div className="mt-3 space-y-2">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Notes…"
            rows={2}
            className="w-full rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
          />
          <input
            type="datetime-local"
            value={reminder ? reminder.slice(0, 16) : ""}
            onChange={(e) => setReminder(e.target.value)}
            className="w-full rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
          />
          <div className="flex gap-2">
            <button
              onClick={handleSaveDetails}
              disabled={saving}
              className="rounded-full bg-primary px-3 py-1 text-xs font-medium text-surface disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="rounded-full border border-textMuted/20 px-3 py-1 text-xs text-textMuted"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-2.5 flex items-center justify-between">
          <div className="text-xs">
            {item.user_notes && (
              <p className="text-textMuted line-clamp-1">
                Notes: {item.user_notes}
              </p>
            )}
            {item.custom_deadline_reminder && (
              <p className="text-textMuted line-clamp-1">
                Reminder: {item.custom_deadline_reminder.slice(0, 10)}
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2" data-tour="kanban-actions">
            {scholarship?.portal_url && (
              <a
                href={scholarship.portal_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-primary hover:underline"
                onClick={(e) => {
                  e.stopPropagation();
                  notifyTourKanbanAction();
                }}
              >
                Apply
              </a>
            )}
            <button
              onClick={() => {
                onOpenDrawer(item);
                notifyTourKanbanAction();
              }}
              className="text-xs text-primary hover:underline"
            >
              Details
            </button>
            <button
              onClick={() => setEditing(true)}
              className="text-xs text-primary hover:underline"
            >
              Edit
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function MobileKanbanCard({
  item,
  onOpenDrawer,
  onMoveStage,
}: {
  item: UserScholarship;
  onOpenDrawer: (item: UserScholarship) => void;
  onMoveStage: (status: AppStatus) => void;
}) {
  const scholarship = item.scholarship;
  const title = scholarship?.title ?? "Opportunity";
  const provider = scholarship?.provider ?? "";
  const amount = scholarship?.award_amount;
  const deadline = scholarship?.deadline ?? "";

  return (
    <div className="rounded-xl bg-surface p-3.5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h4 className="break-words font-serif text-sm font-semibold leading-snug text-text">
            {title}
          </h4>
          {provider && <p className="mt-0.5 break-words text-xs text-textMuted">{provider}</p>}
        </div>
        <select
          value={item.status}
          onChange={(e) => onMoveStage(e.target.value as AppStatus)}
          className="h-9 shrink-0 rounded-lg border border-textMuted/20 bg-surface px-2 text-xs text-text"
          aria-label="Move stage"
        >
          {COLUMNS.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
          <option value="archived">Archived</option>
        </select>
      </div>

      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-textMuted">
        {amount != null && (
          <span>
            <span className="font-semibold text-text">${amount.toLocaleString()}</span>
          </span>
        )}
        {deadline && <span>Due: {deadline}</span>}
      </div>

      {(item.user_notes || item.custom_deadline_reminder) && (
        <div className="mt-2 space-y-0.5 text-xs text-textMuted">
          {item.user_notes && <p className="break-words line-clamp-2">Notes: {item.user_notes}</p>}
          {item.custom_deadline_reminder && (
            <p>Reminder: {item.custom_deadline_reminder.slice(0, 10)}</p>
          )}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3" data-tour="kanban-actions">
        {scholarship?.portal_url && (
          <a
            href={scholarship.portal_url}
            target="_blank"
            rel="noopener noreferrer"
            className="min-h-[36px] rounded-full bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary"
            onClick={(e) => {
              e.stopPropagation();
              notifyTourKanbanAction();
            }}
          >
            Apply
          </a>
        )}
        <button
          onClick={() => {
            onOpenDrawer(item);
            notifyTourKanbanAction();
          }}
          className="min-h-[36px] rounded-full border border-textMuted/20 px-3 py-1.5 text-xs font-medium text-text"
        >
          Details
        </button>
      </div>
    </div>
  );
}


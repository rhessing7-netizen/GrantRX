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
import { ApplicationDrawer } from "./ApplicationDrawer";

const COLUMNS: { id: AppStatus; label: string; accent: string; emptyHint: string }[] = [
  { id: "saved", label: "Saved", accent: "border-textSecondary/20", emptyHint: "Bookmark grants from the Discovery Feed and they'll show up here for tracking." },
  { id: "in_progress", label: "In Progress", accent: "border-skyAqua", emptyHint: "Drag a saved grant here when you start working on your application." },
  { id: "submitted", label: "Submitted", accent: "border-blueEnergy", emptyHint: "Once you've submitted an application, drag it here to track the outcome." },
  { id: "awarded", label: "Awarded", accent: "border-aquamarine", emptyHint: "Your wins will land here. Keep applying — every award counts!" },
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
        colors: ["#73FBD3", "#44E5E7", "#59D2FE", "#4A8FE7", "#5C7AFF"],
      });
      setTimeout(
        () =>
          confetti({
            particleCount: 80,
            angle: 60,
            spread: 70,
            origin: { x: 0, y: 0.7 },
            colors: ["#73FBD3", "#44E5E7", "#59D2FE"],
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
            colors: ["#4A8FE7", "#5C7AFF", "#73FBD3"],
          }),
        450,
      );
    } else {
      // Smaller burst for a submission
      confetti({
        particleCount: 90,
        spread: 70,
        origin: { y: 0.75 },
        colors: ["#73FBD3", "#44E5E7", "#59D2FE", "#4A8FE7"],
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

  const handleDragEnd = async (e: DragEndEvent) => {
    setActiveId(null);
    const { active, over } = e;
    if (!over) return;

    const newStatus = over.id as AppStatus;
    const item = items.find((i) => i.id === active.id);
    if (!item || item.status === newStatus) return;

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
        <div className="mb-4 flex items-center justify-between rounded-xl bg-blueEnergy px-5 py-3 text-white shadow-md">
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
        <div className="mb-4 flex items-center justify-between rounded-xl bg-gradient-to-r from-aquamarine to-neonIce px-5 py-4 shadow-md">
          <div>
            <p className="text-sm font-bold text-textPrimary">
              🎉 Application Submitted!
            </p>
            <p className="mt-0.5 text-xs text-textPrimary/80">
              Great work taking action on your clinical education debt.
            </p>
          </div>
          <button
            onClick={() => setMilestone(null)}
            className="text-sm text-textPrimary/70 hover:text-textPrimary"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Milestone celebration toast — Awarded with award amount prompt */}
      {milestone?.type === "awarded" && (
        <div className="mb-4 rounded-xl bg-gradient-to-r from-aquamarine via-neonIce to-blueEnergy px-5 py-4 shadow-lg">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm font-bold text-textPrimary">
                🏆 Awarded! Congratulations on winning scholarship funding!
              </p>
              <p className="mt-0.5 text-xs text-textPrimary/80">
                Did this help? Let us know the award amount!
              </p>
            </div>
            <button
              onClick={() => setMilestone(null)}
              className="ml-3 shrink-0 text-sm text-textPrimary/70 hover:text-textPrimary"
            >
              Dismiss
            </button>
          </div>
          {!awardSubmitted ? (
            <div className="mt-3 flex items-center gap-2">
              <div className="relative flex-1 max-w-xs">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm font-medium text-textPrimary/60">$</span>
                <input
                  type="number"
                  value={awardInput}
                  onChange={(e) => setAwardInput(e.target.value)}
                  placeholder="Amount"
                  className="w-full rounded-full border border-textPrimary/20 bg-surfaceBg pl-7 pr-3 py-1.5 text-sm text-textPrimary"
                />
              </div>
              <button
                onClick={() => {
                  setAwardSubmitted(true);
                  setTimeout(() => setMilestone(null), 3000);
                }}
                disabled={!awardInput.trim()}
                className="rounded-full bg-textPrimary px-4 py-1.5 text-sm font-semibold text-surfaceBg disabled:opacity-40"
              >
                Submit
              </button>
            </div>
          ) : (
            <p className="mt-2 text-xs font-medium text-textPrimary">
              ✓ Thank you for sharing your win!
            </p>
          )}
        </div>
      )}

      {/* Archive confirmation */}
      {archiveConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-textPrimary/40 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl bg-surfaceBg p-6 shadow-2xl">
            <h3 className="font-serif text-lg font-semibold text-textPrimary">
              Archive this scholarship?
            </h3>
            <p className="mt-2 text-sm text-textSecondary">
              &ldquo;{archiveConfirm.title}&rdquo; will be moved to Archived.
              You can undo this action right after.
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button
                onClick={() => setArchiveConfirm(null)}
                className="rounded-full border border-textSecondary/20 px-4 py-2 text-sm font-medium text-textSecondary hover:text-textPrimary"
              >
                Cancel
              </button>
              <button
                onClick={confirmArchive}
                className="rounded-full bg-blueEnergy px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90"
              >
                Archive
              </button>
            </div>
          </div>
        </div>
      )}

      {paywallMsg && (
        <div className="mb-4 flex items-center justify-between rounded-xl bg-gradient-to-r from-aquamarine to-neonIce px-5 py-3">
          <p className="text-sm font-medium text-textPrimary">{paywallMsg}</p>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setPaywallMsg(null)}
              className="text-sm text-textPrimary/70 hover:text-textPrimary"
            >
              Dismiss
            </button>
            <button
              onClick={() => {
                setPaywallMsg(null);
                onPaywall?.();
              }}
              className="rounded-full bg-textPrimary px-4 py-1.5 text-sm font-semibold text-surfaceBg"
            >
              Upgrade
            </button>
          </div>
        </div>
      )}

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
            accent="border-textSecondary/10"
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

      {/* Application Details & Document Vault drawer */}
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
      className={`rounded-2xl border-t-4 ${accent} bg-cardBg p-4 transition-all duration-150 ${
        isOver ? "ring-2 ring-skyAqua bg-skyAqua/5" : ""
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-serif text-sm font-semibold text-textPrimary">
          {label}
        </h3>
        <span className="rounded-full bg-textSecondary/10 px-2 py-0.5 text-xs text-textSecondary">
          {items.length}
        </span>
      </div>

      <div className="space-y-3">
        {items.length === 0 && (
          <div className="rounded-xl border border-dashed border-textSecondary/15 py-8 px-4 text-center bg-white/50">
            <div className="mx-auto mb-3 h-12 w-12 bg-skyAqua/10 border border-skyAqua/20 flex items-center justify-center rounded-2xl text-blueEnergy">
              <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
            </div>
            <p className="text-sm font-medium text-textSecondary">
              Nothing here yet
            </p>
            <p className="mt-1 text-xs leading-relaxed text-textSecondary/60">
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
  const deadline = scholarship?.deadline ?? item.created_at?.slice(0, 10) ?? "";

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
      className={`rounded-xl bg-surfaceBg p-3.5 shadow-sm ${
        isDragging || dragging ? "opacity-60 shadow-lg" : ""
      } ${dragging ? "rotate-2" : ""}`}
    >
      {/* Drag handle header */}
      <div
        {...attributes}
        {...listeners}
        className="cursor-grab active:cursor-grabbing"
      >
        <h4 className="font-serif text-sm font-semibold leading-snug text-textPrimary">
          {title}
        </h4>
        {provider && (
          <p className="mt-0.5 text-xs text-textSecondary">{provider}</p>
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-textSecondary">
        {amount != null && (
          <span>
            <span className="font-semibold text-textPrimary">
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
            className="w-full rounded-lg border border-textSecondary/20 px-2.5 py-1.5 text-xs text-textPrimary"
          />
          <input
            type="datetime-local"
            value={reminder ? reminder.slice(0, 16) : ""}
            onChange={(e) => setReminder(e.target.value)}
            className="w-full rounded-lg border border-textSecondary/20 px-2.5 py-1.5 text-xs text-textPrimary"
          />
          <div className="flex gap-2">
            <button
              onClick={handleSaveDetails}
              disabled={saving}
              className="rounded-full bg-crayolaBlue px-3 py-1 text-xs font-medium text-surfaceBg disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="rounded-full border border-textSecondary/20 px-3 py-1 text-xs text-textSecondary"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-2.5 flex items-center justify-between">
          <div className="text-xs">
            {item.user_notes && (
              <p className="text-textSecondary line-clamp-1">
                📝 {item.user_notes}
              </p>
            )}
            {item.custom_deadline_reminder && (
              <p className="text-textSecondary line-clamp-1">
                ⏰ {item.custom_deadline_reminder.slice(0, 10)}
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={() => onOpenDrawer(item)}
              className="text-xs text-crayolaBlue hover:underline"
            >
              Vault
            </button>
            <button
              onClick={() => setEditing(true)}
              className="text-xs text-crayolaBlue hover:underline"
            >
              Edit
            </button>
          </div>
        </div>
      )}
    </div>
  );
}


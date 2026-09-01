"use client";

import { useMemo, useState } from "react";
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
import type { AppStatus, ChecklistItem, UserScholarship, VaultDocument } from "@/lib/types";
import { api } from "@/lib/api";

const COLUMNS: { id: AppStatus; label: string; accent: string; emptyHint: string }[] = [
  { id: "saved", label: "Saved", accent: "border-textSecondary/20", emptyHint: "No applications saved yet — bookmark grants from the Discovery feed." },
  { id: "in_progress", label: "In Progress", accent: "border-skyAqua", emptyHint: "Drag saved grants here when you start applying." },
  { id: "submitted", label: "Submitted", accent: "border-blueEnergy", emptyHint: "Applications you've submitted will appear here." },
  { id: "awarded", label: "Awarded", accent: "border-aquamarine", emptyHint: "Celebrate your wins — awarded grants land here." },
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
          <div className="rounded-xl border border-dashed border-textSecondary/15 py-8 px-4 text-center">
            <div className="mx-auto mb-3 h-13 w-13 bg-skyAqua/10 border border-skyAqua/20 flex items-center justify-center rounded-2xl text-blueEnergy">
              <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
            </div>
            <p className="text-sm font-medium text-textSecondary">
              No applications here yet
            </p>
            <p className="mt-1 text-xs text-textSecondary/60">
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


// ---------------------------------------------------------------------------
// Application Details & Document Vault drawer
// ---------------------------------------------------------------------------

const DOC_TYPES = [
  "Personal Statement",
  "Transcript",
  "Letter of Rec",
  "Resume / CV",
  "FAFSA / SAR",
  "Other",
];

const DEFAULT_CHECKLIST: ChecklistItem[] = [
  { id: "essay", text: "Draft Essay", completed: false },
  { id: "reference", text: "Request Reference", completed: false },
  { id: "transcript", text: "Submit Official Transcript", completed: false },
  { id: "fafsa", text: "Complete FAFSA / SAR", completed: false },
  { id: "submit", text: "Submit Application", completed: false },
];

function ApplicationDrawer({
  item,
  onClose,
  onChanged,
}: {
  item: UserScholarship;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [appNotes, setAppNotes] = useState(item.application_notes ?? "");
  const [documents, setDocuments] = useState<VaultDocument[]>(item.documents ?? []);
  const [checklist, setChecklist] = useState<ChecklistItem[]>(
    item.checklist?.length ? item.checklist : DEFAULT_CHECKLIST,
  );
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // New document form state
  const [docName, setDocName] = useState("");
  const [docUrl, setDocUrl] = useState("");
  const [docType, setDocType] = useState(DOC_TYPES[0]);

  // New checklist item state
  const [newChecklistText, setNewChecklistText] = useState("");

  const scholarship = item.scholarship;
  const title = scholarship?.title ?? "Scholarship";
  const provider = scholarship?.provider ?? "";
  const amount = scholarship?.award_amount;
  const deadline = scholarship?.deadline ?? "";

  const handleAddDocument = () => {
    if (!docName.trim() || !docUrl.trim()) return;
    const newDoc: VaultDocument = {
      name: docName.trim(),
      url: docUrl.trim(),
      uploaded_at: new Date().toISOString(),
      type: docType,
    };
    setDocuments((prev) => [...prev, newDoc]);
    setDocName("");
    setDocUrl("");
    setDocType(DOC_TYPES[0]);
  };

  const handleRemoveDocument = (idx: number) => {
    setDocuments((prev) => prev.filter((_, i) => i !== idx));
  };

  const toggleChecklistItem = (id: string) => {
    setChecklist((prev) =>
      prev.map((c) => (c.id === id ? { ...c, completed: !c.completed } : c)),
    );
  };

  const handleAddChecklistItem = () => {
    if (!newChecklistText.trim()) return;
    setChecklist((prev) => [
      ...prev,
      { id: `custom-${Date.now()}`, text: newChecklistText.trim(), completed: false },
    ]);
    setNewChecklistText("");
  };

  const handleRemoveChecklistItem = (id: string) => {
    setChecklist((prev) => prev.filter((c) => c.id !== id));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateTracking(item.id, {
        application_notes: appNotes || null,
        documents,
        checklist,
      });
      setSavedAt(Date.now());
      onChanged();
      setTimeout(() => setSavedAt(null), 2000);
    } finally {
      setSaving(false);
    }
  };

  const completedCount = checklist.filter((c) => c.completed).length;
  const checklistProgress = checklist.length > 0 ? Math.round((completedCount / checklist.length) * 100) : 0;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-textPrimary/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="h-full w-full max-w-md overflow-y-auto bg-surfaceBg shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-textSecondary/10 bg-surfaceBg/95 px-6 py-4 backdrop-blur">
          <div className="min-w-0">
            <h2 className="font-serif text-lg font-semibold text-textPrimary truncate">
              {title}
            </h2>
            {provider && (
              <p className="text-xs text-textSecondary truncate">{provider}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="ml-3 shrink-0 rounded-lg p-1.5 text-textSecondary hover:bg-slate-100 hover:text-textPrimary"
            aria-label="Close"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="space-y-6 px-6 py-5">
          {/* Quick facts */}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-textSecondary">
            {amount != null && (
              <span>
                Award:{" "}
                <span className="font-semibold text-textPrimary">
                  ${amount.toLocaleString()}
                </span>
              </span>
            )}
            {deadline && <span>Deadline: <span className="font-medium text-textPrimary">{deadline}</span></span>}
          </div>

          {/* Application Notes */}
          <section>
            <h3 className="mb-2 font-serif text-sm font-semibold text-textPrimary">
              Application Notes
            </h3>
            <textarea
              value={appNotes}
              onChange={(e) => setAppNotes(e.target.value)}
              placeholder="Jot down essay ideas, contact names, submission steps…"
              rows={4}
              className="w-full rounded-xl border border-textSecondary/20 px-3 py-2 text-sm text-textPrimary placeholder:text-textSecondary/40 focus:border-crayolaBlue focus:outline-none"
            />
          </section>

          {/* Document Vault */}
          <section>
            <h3 className="mb-2 font-serif text-sm font-semibold text-textPrimary">
              Document Vault
            </h3>
            <div className="space-y-2">
              {documents.length === 0 && (
                <p className="text-xs text-textSecondary/60">
                  No documents linked yet. Add Google Drive, Dropbox, or file links below.
                </p>
              )}
              {documents.map((doc, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between rounded-xl border border-textSecondary/10 bg-cardBg px-3 py-2"
                >
                  <div className="min-w-0 flex-1">
                    <a
                      href={doc.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block truncate text-sm font-medium text-crayolaBlue hover:underline"
                    >
                      {doc.name}
                    </a>
                    <p className="text-xs text-textSecondary">
                      {doc.type}
                      {doc.uploaded_at && ` · ${doc.uploaded_at.slice(0, 10)}`}
                    </p>
                  </div>
                  <button
                    onClick={() => handleRemoveDocument(idx)}
                    className="ml-2 shrink-0 text-textSecondary/40 hover:text-red-500"
                    aria-label="Remove document"
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>

            {/* Add document form */}
            <div className="mt-3 space-y-2 rounded-xl border border-dashed border-textSecondary/15 p-3">
              <input
                type="text"
                value={docName}
                onChange={(e) => setDocName(e.target.value)}
                placeholder="Document name (e.g., Personal Statement v2)"
                className="w-full rounded-lg border border-textSecondary/20 px-2.5 py-1.5 text-xs text-textPrimary"
              />
              <input
                type="url"
                value={docUrl}
                onChange={(e) => setDocUrl(e.target.value)}
                placeholder="https://drive.google.com/…"
                className="w-full rounded-lg border border-textSecondary/20 px-2.5 py-1.5 text-xs text-textPrimary"
              />
              <div className="flex gap-2">
                <select
                  value={docType}
                  onChange={(e) => setDocType(e.target.value)}
                  className="flex-1 rounded-lg border border-textSecondary/20 px-2.5 py-1.5 text-xs text-textPrimary"
                >
                  {DOC_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                <button
                  onClick={handleAddDocument}
                  disabled={!docName.trim() || !docUrl.trim()}
                  className="rounded-lg bg-crayolaBlue px-3 py-1.5 text-xs font-medium text-surfaceBg disabled:opacity-40"
                >
                  Add
                </button>
              </div>
            </div>
          </section>

          {/* Checklist */}
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="font-serif text-sm font-semibold text-textPrimary">
                Checklist
              </h3>
              <span className="text-xs text-textSecondary">
                {completedCount}/{checklist.length} · {checklistProgress}%
              </span>
            </div>
            <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-gradient-to-r from-skyAqua to-aquamarine transition-all duration-300"
                style={{ width: `${checklistProgress}%` }}
              />
            </div>
            <div className="space-y-1.5">
              {checklist.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-cardBg"
                >
                  <button
                    onClick={() => toggleChecklistItem(c.id)}
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition ${
                      c.completed
                        ? "border-aquamarine bg-aquamarine text-textPrimary"
                        : "border-textSecondary/30 hover:border-crayolaBlue"
                    }`}
                    aria-label={c.completed ? "Mark incomplete" : "Mark complete"}
                  >
                    {c.completed && (
                      <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={3} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </button>
                  <span
                    className={`flex-1 text-sm ${
                      c.completed ? "text-textSecondary line-through" : "text-textPrimary"
                    }`}
                  >
                    {c.text}
                  </span>
                  <button
                    onClick={() => handleRemoveChecklistItem(c.id)}
                    className="shrink-0 text-textSecondary/30 hover:text-red-500"
                    aria-label="Remove item"
                  >
                    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
            {/* Add checklist item */}
            <div className="mt-2 flex gap-2">
              <input
                type="text"
                value={newChecklistText}
                onChange={(e) => setNewChecklistText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAddChecklistItem()}
                placeholder="Add checklist item…"
                className="flex-1 rounded-lg border border-textSecondary/20 px-2.5 py-1.5 text-xs text-textPrimary"
              />
              <button
                onClick={handleAddChecklistItem}
                disabled={!newChecklistText.trim()}
                className="rounded-lg border border-textSecondary/20 px-3 py-1.5 text-xs font-medium text-textSecondary disabled:opacity-40"
              >
                Add
              </button>
            </div>
          </section>

          {/* Save bar */}
          <div className="sticky bottom-0 -mx-6 flex items-center justify-end gap-3 border-t border-textSecondary/10 bg-surfaceBg/95 px-6 py-3 backdrop-blur">
            {savedAt && (
              <span className="text-xs text-aquamarine">✓ Saved</span>
            )}
            <button
              onClick={onClose}
              className="rounded-full border border-textSecondary/20 px-4 py-2 text-sm font-medium text-textSecondary hover:text-textPrimary"
            >
              Close
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 rounded-full bg-gradient-to-r from-aquamarine to-neonIce px-5 py-2 text-sm font-bold text-textPrimary transition hover:opacity-90 disabled:opacity-50"
            >
              {saving ? (
                <>
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Saving…
                </>
              ) : (
                "Save Vault"
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

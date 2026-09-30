"use client";

import { useEffect, useState } from "react";
import type {
  ChecklistItem,
  EssayOutlineResponse,
  MatchedScholarship,
  Profile,
  UserScholarship,
  VaultDocument,
} from "@/lib/types";
import { api } from "@/lib/api";
import { getMetroShortName } from "@/lib/constants/metros";

// ---------------------------------------------------------------------------
// Constants
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

// ---------------------------------------------------------------------------
// Public props
// ---------------------------------------------------------------------------

export type ApplicationDrawerMode = "preview" | "vault";

export type ApplicationDrawerProps = {
  /** Render mode. `vault` (default) is the full interactive Kanban drawer;
   *  `preview` is the read-only Discovery Feed view. */
  mode?: ApplicationDrawerMode;
  /** Kanban tracking record (required for `vault` mode). */
  item?: UserScholarship | null;
  /** Discovery Feed match result (required for `preview` mode). */
  scholarship?: MatchedScholarship | null;
  /** Student profile used for the preview qualification breakdown. */
  profile?: Profile | null;
  isOpen?: boolean;
  onClose: () => void;
  /** Vault mode: fired after a successful PATCH. */
  onChanged?: () => void;
  /** Preview mode: "Save to Kanban" CTA. */
  onSave?: () => void;
  saving?: boolean;
};

export function ApplicationDrawer({
  mode = "vault",
  item,
  scholarship,
  profile,
  isOpen = true,
  onClose,
  onChanged,
  onSave,
  saving = false,
}: ApplicationDrawerProps) {
  if (!isOpen) return null;

  if (mode === "preview") {
    if (!scholarship) return null;
    return (
      <PreviewDrawer
        scholarship={scholarship}
        profile={profile ?? null}
        onClose={onClose}
        onSave={onSave}
        saving={saving}
      />
    );
  }

  if (!item) return null;
  return (
    <VaultDrawer
      key={item.id}
      item={item}
      onClose={onClose}
      onChanged={onChanged ?? (() => {})}
    />
  );
}

// ---------------------------------------------------------------------------
// Shared shell
// ---------------------------------------------------------------------------

function DrawerShell({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-text/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="h-full w-full max-w-md overflow-y-auto bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-textMuted/10 bg-surface/95 px-6 py-4 backdrop-blur">
          <div className="min-w-0">
            <h2 className="font-serif text-lg font-semibold text-text truncate">
              {title}
            </h2>
            {subtitle && (
              <p className="text-xs text-textMuted truncate">{subtitle}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="ml-3 shrink-0 rounded-lg p-1.5 text-textMuted hover:bg-surfaceSubtle hover:text-text"
            aria-label="Close"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Preview mode (Discovery Feed, read-only)
// ---------------------------------------------------------------------------

type CheckStatus = "met" | "unmet" | "unknown";

function formatDeadline(deadline: string | null): { label: string; daysLeft: number | null } {
  if (!deadline) return { label: "No deadline listed", daysLeft: null };
  const d = new Date(deadline);
  if (isNaN(d.getTime())) return { label: deadline, daysLeft: null };
  const label = d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
  const daysLeft = Math.ceil((d.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  return { label, daysLeft };
}

function humanize(v: string): string {
  return v.replace(/_/g, " ");
}

function buildQualificationChecks(s: MatchedScholarship, profile: Profile | null) {
  const missing = s.missing_criteria ?? [];
  const has = (needle: string) => missing.some((m) => m.toLowerCase().includes(needle));

  const disciplines = s.eligible_disciplines ?? [];
  const credentials = s.eligible_credentials ?? [];
  const states = s.state_restrictions ?? [];
  const metros = s.metro_restrictions ?? [];

  const gpaStatus: CheckStatus = has("gpa")
    ? "unmet"
    : s.min_gpa == null || s.min_gpa === 0
      ? "met"
      : profile?.gpa == null
        ? "unknown"
        : profile.gpa >= s.min_gpa
          ? "met"
          : "unmet";

  const geoRestricted = states.length > 0 || metros.length > 0;
  const userState = profile?.state_residence?.toUpperCase();
  const userMetro = profile?.metro_area;
  const geoMatch =
    (!!userState &&
      states.some((st) => st.toUpperCase() === userState)) ||
    (!!userMetro && metros.includes(userMetro));
  const geoStatus: CheckStatus = has("restricted to")
    ? "unmet"
    : !geoRestricted
      ? "met"
      : !userState && !userMetro
        ? "unknown"
        : geoMatch
          ? "met"
          : "unmet";

  const saiStatus: CheckStatus = has("sai") || has("financial need")
    ? "unmet"
    : s.max_sai == null
      ? "met"
      : profile?.sai_score == null
        ? "unknown"
        : profile.sai_score <= s.max_sai
          ? "met"
          : "unmet";

  // Discipline & credential are hard gates on the server — anything in the
  // feed already passed them, so both rows are always "met". The labels
  // distinguish unrestricted awards from ones that matched the student's track.
  const disciplineUnrestricted =
    s.is_general_major === true ||
    disciplines.length === 0 ||
    disciplines.some((d) => d.toLowerCase() === "any");
  const disciplineLabel = disciplineUnrestricted
    ? "Discipline: Open to all majors / unrestricted"
    : profile?.primary_discipline
      ? `Discipline: Matched your track (${humanize(profile.primary_discipline)})`
      : "Discipline: Matched your field of study";

  const credentialUnrestricted = credentials.length === 0;
  const credentialLabel = credentialUnrestricted
    ? "Credential: All degree levels eligible"
    : `Degree Track: Matches ${profile?.target_credential || "current program"}`;

  return [
    {
      label: disciplineLabel,
      status: "met" as CheckStatus,
      detail: disciplineUnrestricted
        ? "No major or field-of-study requirement"
        : disciplines.map(humanize).join(", "),
    },
    {
      label: credentialLabel,
      status: "met" as CheckStatus,
      detail: credentialUnrestricted
        ? "No credential restriction"
        : credentials.join(", "),
    },
    {
      label: "GPA floor",
      status: gpaStatus,
      detail:
        s.min_gpa && s.min_gpa > 0
          ? `Requires ${s.min_gpa.toFixed(2)}${profile?.gpa != null ? ` · yours ${profile.gpa.toFixed(2)}` : ""}`
          : "No minimum GPA",
    },
    {
      label: "State / metro residence",
      status: geoStatus,
      detail: geoRestricted
        ? [
            ...metros.map((m) => `${getMetroShortName(m)} area`),
            ...states,
          ].join(", ")
        : "No geographic restriction",
    },
    {
      label: "SAI threshold",
      status: saiStatus,
      detail:
        s.max_sai != null
          ? `Requires SAI ≤ ${s.max_sai}${profile?.sai_score != null ? ` · yours ${profile.sai_score}` : ""}`
          : "No financial-need requirement",
    },
  ];
}

function CheckIcon({ status }: { status: CheckStatus }) {
  if (status === "met") {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accentSoft text-text">
        <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={3} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </span>
    );
  }
  if (status === "unmet") {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-warningSoft text-warning border border-warning/40">
        <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={3} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01" />
        </svg>
      </span>
    );
  }
  return (
    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surfaceSubtle text-textMuted border border-border">
      <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={3} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 17h.01M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" />
      </svg>
    </span>
  );
}

function PreviewDrawer({
  scholarship: s,
  profile,
  onClose,
  onSave,
  saving,
}: {
  scholarship: MatchedScholarship;
  profile: Profile | null;
  onClose: () => void;
  onSave?: () => void;
  saving: boolean;
}) {
  const { label: deadlineLabel, daysLeft } = formatDeadline(s.deadline);
  const checks = buildQualificationChecks(s, profile);
  const unmet = s.missing_criteria ?? [];
  const isEmployerBenefit =
    s.funding_type === "tuition_reimbursement" ||
    s.funding_type === "employer_sponsorship" ||
    s.employment_required;

  return (
    <DrawerShell title={s.title} subtitle={s.provider} onClose={onClose}>
      <div className="space-y-6 px-6 py-5">
        {/* Narrative header */}
        <section className="rounded-2xl bg-gradient-to-br from-accent/15 via-accent/10 to-accentSoft/15 border border-accent/20 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wider text-textMuted">
                {s.funding_type ? humanize(s.funding_type) : "Scholarship"}
              </p>
              <p className="mt-1 font-serif text-2xl font-bold text-text">
                {s.award_amount != null && s.award_amount > 0 ? `$${s.award_amount.toLocaleString()}` : "Varies"}
              </p>
              {s.annual_benefit_cap != null && (
                <p className="text-xs text-textMuted">
                  Annual cap ${s.annual_benefit_cap.toLocaleString()}
                </p>
              )}
            </div>
            <span
              className={
                s.score >= 80
                  ? "bg-accentSoft text-text font-bold px-3 py-1 rounded-full text-xs shadow-xs shrink-0"
                  : "bg-white text-text border border-border font-semibold px-3 py-1 rounded-full text-xs shrink-0"
              }
            >
              {s.score}% Match
            </span>
          </div>
          {(s.has_service_commitment || isEmployerBenefit) && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {s.has_service_commitment && (
                <span className="rounded-full bg-accentSoft px-2.5 py-1 text-xs font-semibold text-secondary">
                  Service Obligation
                </span>
              )}
              {isEmployerBenefit && (
                <span className="rounded-full bg-successSoft px-2.5 py-1 text-xs font-semibold text-success">
                  Employer Benefit
                </span>
              )}
              {s.vendor_platform && (
                <span className="rounded-full bg-surfaceSubtle border border-border px-2.5 py-1 text-xs font-medium text-text">
                  via {s.vendor_platform}
                </span>
              )}
            </div>
          )}
          {/* Source-evidence trust state — "Source verified" only when key
              facts were independently located in the fetched source page.
              Eligibility criteria are not independently verified. */}
          <p className="mt-2 text-xs text-textMuted/70">
            {s.verification_status === "verified"
              ? "Source verified — key facts (title, award, deadline, GPA) confirmed on the source page."
              : "Verification pending — facts not yet independently confirmed against the source."}
          </p>
        </section>

        {/* Urgency & deadline */}
        <section>
          <h3 className="mb-2 font-serif text-sm font-semibold text-text">
            Deadline
          </h3>
          <div className="flex items-center justify-between rounded-xl border border-textMuted/10 bg-surfaceSubtle px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-text">{deadlineLabel}</p>
              {daysLeft !== null && daysLeft < 0 && (
                <p className="text-xs text-textMuted">This cycle has closed</p>
              )}
            </div>
            {daysLeft !== null && daysLeft >= 0 && (
              <span
                className={`rounded-full px-3 py-1 text-xs font-bold ${
                  daysLeft <= 7
                    ? "bg-warningSoft text-warning border border-warning/30"
                    : daysLeft <= 30
                      ? "bg-accent/20 text-text"
                      : "bg-surfaceSubtle text-text"
                }`}
              >
                {daysLeft === 0 ? "Due today" : `${daysLeft} day${daysLeft === 1 ? "" : "s"} left`}
              </span>
            )}
          </div>
        </section>

        {/* Provider alignment & mission */}
        {(s.provider_mission || (s.provider_core_values?.length ?? 0) > 0) && (
          <section>
            <h3 className="mb-2 font-serif text-sm font-semibold text-text">
              Provider Alignment &amp; Mission
            </h3>
            {s.provider_mission && (
              <div className="rounded-xl bg-secondary/5 border border-secondary/15 px-4 py-3">
                <p className="text-xs font-medium text-secondary">Mission</p>
                <p className="mt-1 text-sm leading-relaxed text-textMuted">
                  {s.provider_mission}
                </p>
              </div>
            )}
            {(s.provider_core_values?.length ?? 0) > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {s.provider_core_values!.map((v) => (
                  <span
                    key={v}
                    className="rounded-full bg-accentSoft/15 border border-accentSoft/30 px-2.5 py-1 text-xs text-text"
                  >
                    {v}
                  </span>
                ))}
              </div>
            )}
          </section>
        )}

        {/* Target disciplines & credentials */}
        <section>
          <h3 className="mb-2 font-serif text-sm font-semibold text-text">
            Target Disciplines &amp; Credentials
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {(s.eligible_disciplines?.length ?? 0) > 0 ? (
              s.eligible_disciplines!.map((d) => (
                <span
                  key={d}
                  className="rounded-full bg-primary/10 border border-primary/20 px-2.5 py-1 text-xs font-medium capitalize text-text"
                >
                  {humanize(d)}
                </span>
              ))
            ) : (
              <span className="text-xs text-textMuted">Open to all healthcare disciplines</span>
            )}
          </div>
          {(s.eligible_credentials?.length ?? 0) > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {s.eligible_credentials!.map((c) => (
                <span
                  key={c}
                  className="rounded-full bg-surfaceSubtle border border-border px-2.5 py-1 text-xs font-medium text-text"
                >
                  {c}
                </span>
              ))}
            </div>
          )}
        </section>

        {/* Match qualification breakdown */}
        <section>
          <h3 className="mb-2 font-serif text-sm font-semibold text-text">
            Match Qualification Breakdown
          </h3>
          <div className="divide-y divide-textMuted/10 rounded-xl border border-textMuted/10 bg-surfaceSubtle">
            {checks.map((c) => (
              <div key={c.label} className="flex items-start gap-3 px-4 py-2.5">
                <CheckIcon status={c.status} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-text">{c.label}</p>
                  <p className="text-xs text-textMuted">{c.detail}</p>
                </div>
              </div>
            ))}
          </div>
          {unmet.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {unmet.map((c) => (
                <span
                  key={c}
                  className="bg-warningSoft text-warning border border-warning/30/80 font-medium px-2.5 py-0.5 rounded-md text-xs"
                >
                  {c}
                </span>
              ))}
            </div>
          )}
        </section>

        {/* Actions */}
        <div className="sticky bottom-0 -mx-6 flex flex-wrap items-center gap-3 border-t border-textMuted/10 bg-surface/95 px-6 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur">
          {s.portal_url && (
            <a
              href={s.portal_url}
              target="_blank"
              rel="noopener noreferrer"
              className="min-w-[120px] flex-1 rounded-full bg-primary px-5 py-2.5 text-center text-sm font-semibold text-surface transition hover:bg-secondary"
            >
              Apply on Provider Site
            </a>
          )}
          <button
            onClick={onSave}
            disabled={saving || !onSave}
            className="min-w-[120px] flex-1 rounded-full bg-gradient-to-r from-accentSoft to-accent px-5 py-2.5 text-sm font-bold text-text transition hover:opacity-90 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save to My Applications"}
          </button>
        </div>
      </div>
    </DrawerShell>
  );
}

// ---------------------------------------------------------------------------
// Vault mode (Kanban, fully interactive)
// ---------------------------------------------------------------------------

function VaultDrawer({
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
  const [saveError, setSaveError] = useState<string | null>(null);

  // New document form state
  const [docName, setDocName] = useState("");
  const [docUrl, setDocUrl] = useState("");
  const [docType, setDocType] = useState(DOC_TYPES[0]);

  // New checklist item state
  const [newChecklistText, setNewChecklistText] = useState("");

  // Report inaccurate info state
  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState<"broken_link" | "inaccurate_deadline" | "expired">("broken_link");
  const [reportNotes, setReportNotes] = useState("");
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportSubmitted, setReportSubmitted] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  // AI Statement Coach state
  const [coachOpen, setCoachOpen] = useState(false);
  const [outlineLoading, setOutlineLoading] = useState(false);
  const [outline, setOutline] = useState<EssayOutlineResponse | null>(null);
  const [outlineError, setOutlineError] = useState<string | null>(null);
  const [essayPrompt, setEssayPrompt] = useState("");
  const [livedExperience, setLivedExperience] = useState("");
  const [workExperience, setWorkExperience] = useState("");
  const [academicTopics, setAcademicTopics] = useState("");

  const scholarship = item.scholarship;
  const title = scholarship?.title ?? "Opportunity";
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
    setSaveError(null);
    try {
      await api.updateTracking(item.id, {
        application_notes: appNotes || null,
        documents,
        checklist,
      });
      setSavedAt(Date.now());
      onChanged();
      setTimeout(() => setSavedAt(null), 2000);
    } catch {
      setSaveError("Couldn't save your changes — please try again.");
    } finally {
      setSaving(false);
    }
  };

  const handleGenerateOutline = async () => {
    if (!scholarship) return;
    setOutlineLoading(true);
    setOutlineError(null);
    try {
      const result = await api.generateEssayOutline(scholarship.id, {
        prompt: essayPrompt || undefined,
        lived_experience_notes: livedExperience || undefined,
        work_volunteer_experience: workExperience || undefined,
        academic_topics_of_interest: academicTopics || undefined,
      });
      setOutline(result);
    } catch {
      setOutlineError(
        "Couldn't generate an outline right now. Please try again in a moment.",
      );
    } finally {
      setOutlineLoading(false);
    }
  };

  const handleAppendOutline = async () => {
    if (!outline) return;
    const md = formatOutlineAsMarkdown(outline);
    const newNotes = appNotes ? `${appNotes}\n\n---\n\n${md}` : md;
    setAppNotes(newNotes);
    try {
      await api.updateTracking(item.id, {
        application_notes: newNotes,
      });
      onChanged();
    } catch {
      // Notes still updated locally
    }
  };

  const handleReportSubmit = async () => {
    if (!scholarship) return;
    setReportSubmitting(true);
    try {
      await api.reportScholarship(scholarship.id, reportReason, reportNotes || undefined);
      setReportSubmitted(true);
      setReportOpen(false);
      setReportNotes("");
    } catch {
      setReportError("Couldn't submit the report — please try again.");
    } finally {
      setReportSubmitting(false);
    }
  };

  const completedCount = checklist.filter((c) => c.completed).length;
  const checklistProgress = checklist.length > 0 ? Math.round((completedCount / checklist.length) * 100) : 0;

  return (
    <DrawerShell title={title} subtitle={provider || undefined} onClose={onClose}>
      <div className="space-y-6 px-6 py-5">
        {/* Quick facts */}
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-textMuted">
          {amount != null && (
            <span>
              Award:{" "}
              <span className="font-semibold text-text">
                ${amount.toLocaleString()}
              </span>
            </span>
          )}
          {deadline && <span>Deadline: <span className="font-medium text-text">{deadline}</span></span>}
        </div>

        {/* Report inaccurate info */}
        <div className="text-right">
          {reportSubmitted ? (
            <p className="text-xs text-accentSoft">✓ Report submitted — thank you!</p>
          ) : reportOpen ? (
            <div className="space-y-2 rounded-xl border border-textMuted/15 bg-surfaceSubtle px-3 py-2 text-left">
              <p className="text-xs font-medium text-text">Report inaccurate info</p>
              <select
                value={reportReason}
                onChange={(e) => setReportReason(e.target.value as typeof reportReason)}
                aria-label="Report reason"
                className="w-full rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
              >
                <option value="broken_link">Broken application link</option>
                <option value="inaccurate_deadline">Inaccurate deadline</option>
                <option value="expired">Scholarship has expired</option>
              </select>
              <input
                type="text"
                value={reportNotes}
                onChange={(e) => setReportNotes(e.target.value)}
                placeholder="Additional notes (optional)"
                aria-label="Additional report notes"
                className="w-full rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
              />
              {reportError && (
                <p role="alert" className="text-xs text-danger">{reportError}</p>
              )}
              <div className="flex gap-2">
                <button
                  onClick={() => setReportOpen(false)}
                  className="flex-1 rounded-lg border border-textMuted/20 px-3 py-1.5 text-xs text-textMuted"
                >
                  Cancel
                </button>
                <button
                  onClick={handleReportSubmit}
                  disabled={reportSubmitting}
                  className="flex-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-surface disabled:opacity-50"
                >
                  {reportSubmitting ? "Submitting…" : "Submit"}
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setReportOpen(true)}
              className="text-xs text-textMuted/50 hover:text-primary hover:underline"
            >
              ⚑ Report inaccurate info
            </button>
          )}
        </div>

        {/* Application Notes */}
        <section>
          <h3 className="mb-2 font-serif text-sm font-semibold text-text">
            Application Notes
          </h3>
          <textarea
            value={appNotes}
            onChange={(e) => setAppNotes(e.target.value)}
            aria-label="Application notes"
            placeholder="Jot down essay ideas, contact names, submission steps…"
            rows={4}
            className="w-full rounded-xl border border-textMuted/20 px-3 py-2 text-sm text-text placeholder:text-textMuted/40 focus:border-primary focus:outline-none"
          />
        </section>

        {/* Documents */}
        <section>
          <h3 className="mb-2 font-serif text-sm font-semibold text-text">
            Documents
          </h3>
          <div className="space-y-2">
            {documents.length === 0 && (
              <p className="text-xs text-textMuted/60">
                No documents linked yet. Add Google Drive, Dropbox, or file links below.
              </p>
            )}
            {documents.map((doc, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between rounded-xl border border-textMuted/10 bg-surfaceSubtle px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <a
                    href={doc.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block truncate text-sm font-medium text-primary hover:underline"
                  >
                    {doc.name}
                  </a>
                  <p className="text-xs text-textMuted">
                    {doc.type}
                    {doc.uploaded_at && ` · ${doc.uploaded_at.slice(0, 10)}`}
                  </p>
                </div>
                <button
                  onClick={() => handleRemoveDocument(idx)}
                  className="ml-2 shrink-0 text-textMuted/40 hover:text-danger"
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
          <div className="mt-3 space-y-2 rounded-xl border border-dashed border-textMuted/15 p-3">
            <input
              type="text"
              value={docName}
              onChange={(e) => setDocName(e.target.value)}
              placeholder="Document name (e.g., Personal Statement v2)"
              aria-label="Document name"
              className="w-full rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
            />
            <input
              type="url"
              value={docUrl}
              onChange={(e) => setDocUrl(e.target.value)}
              placeholder="https://drive.google.com/…"
              aria-label="Document link URL"
              className="w-full rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
            />
            <div className="flex gap-2">
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                aria-label="Document type"
                className="flex-1 rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
              >
                {DOC_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <button
                onClick={handleAddDocument}
                disabled={!docName.trim() || !docUrl.trim()}
                className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-surface disabled:opacity-40"
              >
                Add
              </button>
            </div>
          </div>
        </section>

        {/* Checklist */}
        <section>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-serif text-sm font-semibold text-text">
              Checklist
            </h3>
            <span className="text-xs text-textMuted">
              {completedCount}/{checklist.length} · {checklistProgress}%
            </span>
          </div>
          <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-surfaceSubtle">
            <div
              className="h-full rounded-full bg-gradient-to-r from-accent to-accentSoft transition-all duration-300"
              style={{ width: `${checklistProgress}%` }}
            />
          </div>
          <div className="space-y-1.5">
            {checklist.map((c) => (
              <div
                key={c.id}
                className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-surfaceSubtle"
              >
                <button
                  onClick={() => toggleChecklistItem(c.id)}
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition ${
                    c.completed
                      ? "border-accentSoft bg-accentSoft text-text"
                      : "border-textMuted/30 hover:border-primary"
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
                    c.completed ? "text-textMuted line-through" : "text-text"
                  }`}
                >
                  {c.text}
                </span>
                <button
                  onClick={() => handleRemoveChecklistItem(c.id)}
                  className="shrink-0 text-textMuted/30 hover:text-danger"
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
              aria-label="New checklist item"
              className="flex-1 rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
            />
            <button
              onClick={handleAddChecklistItem}
              disabled={!newChecklistText.trim()}
              className="rounded-lg border border-textMuted/20 px-3 py-1.5 text-xs font-medium text-textMuted disabled:opacity-40"
            >
              Add
            </button>
          </div>
        </section>

        {/* AI Statement Coach */}
        <section>
          <button
            onClick={() => setCoachOpen((v) => !v)}
            className="flex w-full items-center justify-between py-2"
          >
            <div className="flex items-center gap-2">
              <svg className="h-4 w-4 text-primary" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.5.8a2 2 0 11-3.473 0l.5-.8z" />
              </svg>
              <h3 className="font-serif text-sm font-semibold text-text">
                AI Statement Coach
              </h3>
            </div>
            <svg className={`h-4 w-4 text-textMuted transition-transform ${coachOpen ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {/* Academic honesty disclaimer — always visible */}
          <div className="mt-2 bg-warningSoft/70 border border-warning/30 rounded-xl p-3 text-xs text-warning">
            EdFintia Statement Coach is an educational brainstorming and
            outlining tool. It does not write essays for you, submit
            materials on your behalf, or guarantee award selection. Always
            abide by your institution&apos;s academic honesty policies.
          </div>

          {coachOpen && (
            <div className="mt-3 space-y-4">
              {/* Provider mission & core values */}
              {scholarship?.provider_mission && (
                <div className="rounded-xl bg-secondary/5 border border-secondary/15 px-3 py-2">
                  <p className="text-xs font-medium text-secondary">Provider Mission</p>
                  <p className="mt-1 text-xs text-textMuted">{scholarship.provider_mission}</p>
                </div>
              )}
              {scholarship?.provider_core_values && scholarship.provider_core_values.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {scholarship.provider_core_values.map((v) => (
                    <span key={v} className="rounded-full bg-accentSoft/15 border border-accentSoft/30 px-2 py-0.5 text-xs text-text">
                      {v}
                    </span>
                  ))}
                </div>
              )}

              {/* Input fields */}
              <div className="space-y-2">
                <input
                  type="text"
                  value={essayPrompt}
                  onChange={(e) => setEssayPrompt(e.target.value)}
                  placeholder="Essay prompt / topic (optional)"
                  aria-label="Essay prompt or topic"
                  className="w-full rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
                />
                <textarea
                  value={livedExperience}
                  onChange={(e) => setLivedExperience(e.target.value)}
                  placeholder="Personal upbringing & lived experience notes…"
                  aria-label="Personal upbringing and lived experience notes"
                  rows={2}
                  className="w-full rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
                />
                <textarea
                  value={workExperience}
                  onChange={(e) => setWorkExperience(e.target.value)}
                  placeholder="Work / clinical / volunteer experience…"
                  aria-label="Work, clinical, or volunteer experience"
                  rows={2}
                  className="w-full rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
                />
                <textarea
                  value={academicTopics}
                  onChange={(e) => setAcademicTopics(e.target.value)}
                  placeholder="Academic / research topics of interest…"
                  aria-label="Academic or research topics of interest"
                  rows={2}
                  className="w-full rounded-lg border border-textMuted/20 px-2.5 py-1.5 text-xs text-text"
                />
              </div>

              {/* Generate button */}
              <button
                onClick={handleGenerateOutline}
                disabled={outlineLoading}
                className="flex w-full items-center justify-center gap-2 rounded-full bg-gradient-to-r from-primary to-secondary px-4 py-2 text-xs font-semibold text-surface transition hover:opacity-90 disabled:opacity-50"
              >
                {outlineLoading ? (
                  <>
                    <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Generating Outline…
                  </>
                ) : (
                  "Generate 4-Part Outline"
                )}
              </button>

              {outlineError && (
                <p className="text-xs text-danger">{outlineError}</p>
              )}

              {/* Generated outline */}
              {outline && (
                <div className="space-y-3">
                  {/* Theme & mission alignment */}
                  <div className="rounded-xl bg-surface px-3 py-2">
                    <p className="text-xs font-semibold text-text">Suggested Theme</p>
                    <p className="mt-0.5 text-xs text-textMuted">{outline.suggested_theme}</p>
                  </div>
                  <div className="rounded-xl bg-secondary/5 border border-secondary/15 px-3 py-2">
                    <p className="text-xs font-semibold text-secondary">Mission Alignment</p>
                    <p className="mt-0.5 text-xs text-textMuted">{outline.mission_alignment_angle}</p>
                  </div>

                  {/* 4 narrative sections */}
                  {[
                    { label: "1. Personal Story", section: outline.part_1_personal_story },
                    { label: "2. Work & Volunteer", section: outline.part_2_work_experience },
                    { label: "3. Academic Foundation", section: outline.part_3_academic_citation },
                    { label: "4. Future Service", section: outline.part_4_future_service },
                  ].map(({ label, section }) => (
                    <div key={label} className="rounded-xl border border-textMuted/10 px-3 py-2">
                      <div className="flex items-center justify-between">
                        <p className="text-xs font-semibold text-text">{label}</p>
                        <span className="text-xs text-textMuted">~{section.estimated_word_count} words</span>
                      </div>
                      {section.talking_points.length > 0 && (
                        <ul className="mt-1.5 space-y-0.5">
                          {section.talking_points.map((tp, i) => (
                            <li key={i} className="text-xs text-textMuted">
                              • {tp}
                            </li>
                          ))}
                        </ul>
                      )}
                      {section.coaching_tips.length > 0 && (
                        <div className="mt-1.5 space-y-0.5">
                          {section.coaching_tips.map((tip, i) => (
                            <p key={i} className="text-xs italic text-secondary/70">
                              💡 {tip}
                            </p>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}

                  {/* Checklist */}
                  {outline.checklist.length > 0 && (
                    <div className="rounded-xl bg-accentSoft/5 border border-accentSoft/20 px-3 py-2">
                      <p className="text-xs font-semibold text-text">Pre-Submission Checklist</p>
                      <ul className="mt-1 space-y-0.5">
                        {outline.checklist.map((c, i) => (
                          <li key={i} className="text-xs text-textMuted">☐ {c}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Append to notes */}
                  <button
                    onClick={handleAppendOutline}
                    className="w-full rounded-full border border-primary px-4 py-2 text-xs font-medium text-primary hover:bg-primary/5"
                  >
                    Append Outline to Notes
                  </button>
                </div>
              )}
            </div>
          )}
        </section>

        {/* Save bar */}
        <div className="sticky bottom-0 -mx-6 flex flex-wrap items-center justify-end gap-3 border-t border-textMuted/10 bg-surface/95 px-6 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur">
          {saveError && (
            <span role="alert" className="text-xs text-danger">{saveError}</span>
          )}
          {savedAt && (
            <span className="text-xs text-accentSoft">✓ Saved</span>
          )}
          <button
            onClick={onClose}
            className="rounded-full border border-textMuted/20 px-4 py-2 text-sm font-medium text-textMuted hover:text-text"
          >
            Close
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 rounded-full bg-gradient-to-r from-accentSoft to-accent px-5 py-2 text-sm font-bold text-text transition hover:opacity-90 disabled:opacity-50"
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
              "Save"
            )}
          </button>
        </div>
      </div>
    </DrawerShell>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatOutlineAsMarkdown(outline: EssayOutlineResponse): string {
  const sections = [
    { label: "Part 1: Personal Story & Upbringing", section: outline.part_1_personal_story },
    { label: "Part 2: Work & Volunteer Track Record", section: outline.part_2_work_experience },
    { label: "Part 3: Academic Foundation & Citations", section: outline.part_3_academic_citation },
    { label: "Part 4: Future Service & Community Impact", section: outline.part_4_future_service },
  ];

  let md = `## AI Essay Outline\n\n`;
  md += `**Suggested Theme:** ${outline.suggested_theme}\n\n`;
  md += `**Mission Alignment:** ${outline.mission_alignment_angle}\n\n`;

  for (const { label, section } of sections) {
    md += `### ${label} (~${section.estimated_word_count} words)\n`;
    if (section.talking_points.length > 0) {
      md += `**Talking Points:**\n`;
      for (const tp of section.talking_points) {
        md += `- ${tp}\n`;
      }
    }
    if (section.coaching_tips.length > 0) {
      md += `**Coaching Tips:**\n`;
      for (const tip of section.coaching_tips) {
        md += `- ${tip}\n`;
      }
    }
    md += `\n`;
  }

  if (outline.checklist.length > 0) {
    md += `### Pre-Submission Checklist\n`;
    for (const c of outline.checklist) {
      md += `- [ ] ${c}\n`;
    }
  }

  return md;
}

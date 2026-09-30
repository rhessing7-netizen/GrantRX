"use client";

import { useEffect, useState } from "react";
import {
  AFFILIATION_OPTIONS,
  CREDENTIAL_OPTIONS,
  type Profile,
  type ProfileUpdate,
} from "@/lib/types";
import { getMetrosForState } from "@/lib/constants/metros";
import { MAJOR_CATEGORIES, mapMajorToClinicalDiscipline } from "@/lib/constants/disciplines";
import { levelForCredential, type DegreeLevel } from "@/lib/constants/credentials";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { MultiSelect } from "./MultiSelect";
import { GroupedMultiSelect } from "./GroupedMultiSelect";
import { CascadingCredentialSelect } from "./CascadingCredentialSelect";

export type ProfileEditModalProps = {
  open: boolean;
  onClose: () => void;
  profile: Profile;
  onSaved: (profile: Profile) => void;
  onDeleted?: () => void;
};

export function ProfileEditModal({ open, onClose, profile, onSaved, onDeleted }: ProfileEditModalProps) {
  const [disciplines, setDisciplines] = useState<string[]>(profile.disciplines ?? []);
  const [credentials, setCredentials] = useState<string[]>(profile.target_credentials ?? []);

  // Cascading credential selection — reverse-map the saved credential to its
  // degree level so the select restores the full path instead of hiding the
  // saved value.
  const [degreeLevel, setDegreeLevel] = useState<DegreeLevel | "">(
    profile.target_credential
      ? levelForCredential(profile.target_credential)
      : "",
  );
  const [selectedCredential, setSelectedCredential] = useState(profile.target_credential ?? "");
  const [clinicalPhase, setClinicalPhase] = useState(profile.clinical_phase ?? "");
  const [gpa, setGpa] = useState(profile.gpa != null ? String(profile.gpa) : "");
  const [stateResidence, setStateResidence] = useState(profile.state_residence ?? "");
  const [metroArea, setMetroArea] = useState(profile.metro_area ?? "");
  const [saiScore, setSaiScore] = useState(profile.sai_score != null ? String(profile.sai_score) : "");
  const [firstGen, setFirstGen] = useState(profile.first_gen ?? false);
  const [minorityFlag, setMinorityFlag] = useState(profile.minority_flag ?? false);
  const [affiliations, setAffiliations] = useState<string[]>(profile.professional_affiliations ?? []);
  const [hobbies, setHobbies] = useState((profile.hobbies ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Danger Zone state
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (confirmDeleteOpen) setConfirmDeleteOpen(false);
        else onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose, confirmDeleteOpen]);

  if (!open) return null;

  const toggleAffiliation = (a: string) => {
    setAffiliations((prev) =>
      prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a],
    );
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      // Stable-order dedup: the cascading credential may already be present
      // in the multi-select list after a previous save.
      const allCredentials = [
        ...new Set(
          selectedCredential ? [...credentials, selectedCredential] : credentials,
        ),
      ];
      // Explicit nulls clear optional fields on the backend; omitting a key
      // would leave the existing value unchanged.
      const payload: ProfileUpdate = {
        disciplines,
        target_credentials: allCredentials,
        first_gen: firstGen,
        minority_flag: minorityFlag,
        professional_affiliations: affiliations,
        hobbies: hobbies
          .split(",")
          .map((h) => h.trim())
          .filter(Boolean),
        // Map the first selected major to primary_discipline for backend matching
        primary_discipline:
          disciplines.length > 0
            ? mapMajorToClinicalDiscipline(disciplines[0])
            : null,
        target_credential: selectedCredential || null,
        clinical_phase: clinicalPhase || null,
        gpa: gpa ? parseFloat(gpa) : null,
        state_residence: stateResidence ? stateResidence.toUpperCase() : null,
        metro_area: metroArea || null,
        sai_score: saiScore ? parseInt(saiScore, 10) : null,
      };

      const updated = await api.updateProfile(payload);
      // Sync the cache with the server-confirmed result only after success
      try { localStorage.setItem("grantrx_profile", JSON.stringify(updated)); } catch {}
      onSaved(updated);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-text/40 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="mx-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-2xl bg-surface p-6 shadow-2xl sm:w-full sm:rounded-3xl sm:p-8"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Edit profile"
      >
        <div className="mb-6 flex items-center justify-between">
          <h2 className="font-serif text-2xl font-bold text-text">
            Edit Profile
          </h2>
          <button
            onClick={onClose}
            className="text-sm text-textMuted hover:text-text"
          >
            Close
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-xl bg-dangerSoft px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="space-y-5">
          {/* Multi-select majors (categorized) */}
          <GroupedMultiSelect
            label="Majors / Fields of Study"
            categories={MAJOR_CATEGORIES}
            selected={disciplines}
            onChange={setDisciplines}
            placeholder="Search and select your major…"
            maxHeight={320}
          />

          {/* Cascading credential selection */}
          <CascadingCredentialSelect
            label="Degree Level & Credential"
            selectedLevel={degreeLevel}
            selectedCredential={selectedCredential}
            onLevelChange={setDegreeLevel}
            onCredentialChange={setSelectedCredential}
          />

          {/* Additional multi-select credentials */}
          <MultiSelect
            label="Additional Credentials"
            options={CREDENTIAL_OPTIONS}
            selected={credentials}
            onChange={setCredentials}
            placeholder="Select additional credentials…"
            maxHeight={200}
          />

          {/* Academic details */}
          <div>
            <label className="block text-sm font-medium text-textMuted">
              Clinical Phase
            </label>
            <input
              value={clinicalPhase}
              onChange={(e) => setClinicalPhase(e.target.value)}
              placeholder="e.g. P1, P2, MS3"
              className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-textMuted">
                GPA
              </label>
              <input
                value={gpa}
                onChange={(e) => setGpa(e.target.value)}
                type="number"
                step="0.01"
                min="0"
                max="4"
                placeholder="3.75"
                className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-textMuted">
                State
              </label>
              <input
                value={stateResidence}
                onChange={(e) =>
                  setStateResidence(e.target.value.toUpperCase().slice(0, 2))
                }
                placeholder="CA"
                maxLength={2}
                className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-textMuted">
              SAI Score
            </label>
            <input
              value={saiScore}
              onChange={(e) => setSaiScore(e.target.value)}
              type="number"
              placeholder="e.g. 1200"
              className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-textMuted">
              Metropolitan Area
            </label>
            <select
              value={metroArea}
              onChange={(e) => setMetroArea(e.target.value)}
              className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
            >
              <option value="">Any / Not specified</option>
              {getMetrosForState(stateResidence).map((m) => (
                <option key={m.slug} value={m.name}>
                  {m.matchesState ? "\u2605 " : ""}{m.shortName} ({m.states.join(", ")})
                </option>
              ))}
            </select>
          </div>

          {/* Background */}
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm text-text">
              <input
                type="checkbox"
                checked={firstGen}
                onChange={(e) => setFirstGen(e.target.checked)}
                className="h-4 w-4 accent-primary"
              />
              First-Generation
            </label>
            <label className="flex items-center gap-2 text-sm text-text">
              <input
                type="checkbox"
                checked={minorityFlag}
                onChange={(e) => setMinorityFlag(e.target.checked)}
                className="h-4 w-4 accent-primary"
              />
              Minority / Underrepresented
            </label>
          </div>

          <div>
            <label className="block text-sm font-medium text-textMuted">
              Professional Affiliations
            </label>
            <div className="mt-2 flex flex-wrap gap-2">
              {AFFILIATION_OPTIONS.map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => toggleAffiliation(a)}
                  className={`rounded-full px-3 py-1.5 text-sm transition ${
                    affiliations.includes(a)
                      ? "bg-primary text-surface"
                      : "border border-textMuted/20 text-textMuted"
                  }`}
                >
                  {a}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-textMuted">
              Hobbies / Interests (comma-separated)
            </label>
            <input
              value={hobbies}
              onChange={(e) => setHobbies(e.target.value)}
              placeholder="research, volunteering, music"
              className="mt-2 w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
            />
          </div>
        </div>

        {/* Actions */}
        <div className="mt-8 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="text-sm text-textMuted hover:text-text"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>

        {/* Permanently Delete */}
        <div className="rounded-2xl border border-danger/30 bg-dangerSoft/40 p-5 mt-6">
          <h3 className="text-danger font-semibold text-sm mb-1">
            Permanently Delete
          </h3>
          <p className="mt-1 text-xs text-textMuted">
            Permanently delete your account, cancel any active subscription,
            and remove all tracked opportunities, budgets, and reports. This
            action cannot be undone.
          </p>
          <button
            onClick={() => setConfirmDeleteOpen(true)}
            disabled={deleting}
            className="mt-3 rounded-full border-2 border-danger px-5 py-2 text-sm font-medium text-danger transition hover:bg-danger hover:text-white disabled:opacity-50"
          >
            Delete Account & Data
          </button>
          {deleteError && (
            <p className="mt-2 text-xs text-danger">{deleteError}</p>
          )}
        </div>
      </div>

      {/* Confirmation modal */}
      {confirmDeleteOpen && (
        <div
          className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-text/50 p-4 backdrop-blur-sm"
          onClick={() => !deleting && setConfirmDeleteOpen(false)}
        >
          <div
            className="mx-auto w-[calc(100%-2rem)] max-w-md rounded-2xl bg-surface p-6 shadow-2xl sm:w-full sm:rounded-3xl"
            onClick={(e) => e.stopPropagation()}
            role="alertdialog"
            aria-modal="true"
            aria-label="Delete account confirmation"
          >
            <h3 className="font-serif text-lg font-bold text-danger">
              Delete Account?
            </h3>
            <p className="mt-2 break-words text-sm text-textMuted">
              Are you sure? This will immediately terminate any active
              subscription and permanently delete your profile, budget, and
              tracked opportunities. Type{" "}
              <span className="font-bold text-danger">DELETE</span> to confirm.
            </p>
            <input
              type="text"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="Type DELETE to confirm"
              aria-label="Type DELETE to confirm account deletion"
              className="mt-4 w-full rounded-xl border border-danger/30 bg-white px-4 py-2.5 text-sm text-text focus:border-danger focus:outline-none focus:ring-2 focus:ring-danger/20"
            />
            <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
              <button
                onClick={() => setConfirmDeleteOpen(false)}
                disabled={deleting}
                className="text-sm text-textMuted hover:text-text disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deleting || deleteConfirmText.trim() !== "DELETE"}
                className="rounded-full bg-danger px-5 py-2 text-sm font-medium text-white transition hover:bg-danger disabled:opacity-50"
              >
                {deleting ? "Deleting…" : "Yes, delete my account"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  async function handleDeleteAccount() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteAccount();
      // Clear the cached profile so deleted state never re-hydrates
      try { localStorage.removeItem("grantrx_profile"); } catch {}
      // Sign out of Supabase client auth
      if (supabase) {
        try {
          await supabase.auth.signOut();
        } catch {
          // Best-effort — backend already purged credentials
        }
      }
      setConfirmDeleteOpen(false);
      onDeleted?.();
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete account",
      );
    } finally {
      setDeleting(false);
    }
  }
}

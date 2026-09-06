"use client";

import { useState } from "react";
import {
  AFFILIATION_OPTIONS,
  CREDENTIAL_OPTIONS,
  type Profile,
  type ProfileUpdate,
} from "@/lib/types";
import { getMetrosForState } from "@/lib/constants/metros";
import { MAJOR_CATEGORIES, mapMajorToClinicalDiscipline } from "@/lib/constants/disciplines";
import { type DegreeLevel } from "@/lib/constants/credentials";
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

  // Cascading credential selection
  const [degreeLevel, setDegreeLevel] = useState<DegreeLevel | "">("");
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
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
      const allCredentials = selectedCredential
        ? [...credentials, selectedCredential]
        : credentials;
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
      };
      // Map the first selected major to primary_discipline for backend matching
      if (disciplines.length > 0) {
        payload.primary_discipline = mapMajorToClinicalDiscipline(disciplines[0]);
      }
      // Set target_credential from the cascading selection
      if (selectedCredential) payload.target_credential = selectedCredential;
      if (clinicalPhase) payload.clinical_phase = clinicalPhase;
      if (gpa) payload.gpa = parseFloat(gpa);
      if (stateResidence) payload.state_residence = stateResidence.toUpperCase();
      if (metroArea) payload.metro_area = metroArea;
      if (saiScore) payload.sai_score = parseInt(saiScore, 10);

      const updated = await api.updateProfile(payload);
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-textPrimary/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-3xl bg-surfaceBg p-8 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-6 flex items-center justify-between">
          <h2 className="font-serif text-2xl font-bold text-textPrimary">
            Edit Profile
          </h2>
          <button
            onClick={onClose}
            className="text-sm text-textSecondary hover:text-textPrimary"
          >
            Close
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">
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
            <label className="block text-sm font-medium text-textSecondary">
              Clinical Phase
            </label>
            <input
              value={clinicalPhase}
              onChange={(e) => setClinicalPhase(e.target.value)}
              placeholder="e.g. P1, P2, MS3"
              className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-textSecondary">
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
                className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-textSecondary">
                State
              </label>
              <input
                value={stateResidence}
                onChange={(e) =>
                  setStateResidence(e.target.value.toUpperCase().slice(0, 2))
                }
                placeholder="CA"
                maxLength={2}
                className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-textSecondary">
              SAI Score
            </label>
            <input
              value={saiScore}
              onChange={(e) => setSaiScore(e.target.value)}
              type="number"
              placeholder="e.g. 1200"
              className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-textSecondary">
              Metropolitan Area
            </label>
            <select
              value={metroArea}
              onChange={(e) => setMetroArea(e.target.value)}
              className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
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
            <label className="flex items-center gap-2 text-sm text-textPrimary">
              <input
                type="checkbox"
                checked={firstGen}
                onChange={(e) => setFirstGen(e.target.checked)}
                className="h-4 w-4 accent-crayolaBlue"
              />
              First-Generation
            </label>
            <label className="flex items-center gap-2 text-sm text-textPrimary">
              <input
                type="checkbox"
                checked={minorityFlag}
                onChange={(e) => setMinorityFlag(e.target.checked)}
                className="h-4 w-4 accent-crayolaBlue"
              />
              Minority / Underrepresented
            </label>
          </div>

          <div>
            <label className="block text-sm font-medium text-textSecondary">
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
                      ? "bg-crayolaBlue text-surfaceBg"
                      : "border border-textSecondary/20 text-textSecondary"
                  }`}
                >
                  {a}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-textSecondary">
              Hobbies / Interests (comma-separated)
            </label>
            <input
              value={hobbies}
              onChange={(e) => setHobbies(e.target.value)}
              placeholder="research, volunteering, music"
              className="mt-2 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-4 py-2.5 text-textPrimary"
            />
          </div>
        </div>

        {/* Actions */}
        <div className="mt-8 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="text-sm text-textSecondary hover:text-textPrimary"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-full bg-crayolaBlue px-6 py-2.5 text-sm font-medium text-surfaceBg disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>

        {/* Permanently Delete */}
        <div className="rounded-2xl border border-red-200/70 bg-red-50/40 p-5 mt-6">
          <h3 className="text-red-700 font-semibold text-sm mb-1">
            Permanently Delete
          </h3>
          <p className="mt-1 text-xs text-textSecondary">
            Permanently delete your account, cancel any active subscription,
            and remove all saved scholarships, budgets, and reports. This
            action cannot be undone.
          </p>
          <button
            onClick={() => setConfirmDeleteOpen(true)}
            disabled={deleting}
            className="mt-3 rounded-full border-2 border-red-500 px-5 py-2 text-sm font-medium text-red-600 transition hover:bg-red-500 hover:text-white disabled:opacity-50"
          >
            Delete Account & Data
          </button>
          {deleteError && (
            <p className="mt-2 text-xs text-red-600">{deleteError}</p>
          )}
        </div>
      </div>

      {/* Confirmation modal */}
      {confirmDeleteOpen && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-textPrimary/50 backdrop-blur-sm"
          onClick={() => !deleting && setConfirmDeleteOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-3xl bg-surfaceBg p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="font-serif text-lg font-bold text-red-700">
              Delete Account?
            </h3>
            <p className="mt-2 text-sm text-textSecondary">
              Are you sure? This will cancel your subscription immediately and
              permanently delete your profile, budget, and saved scholarships.
            </p>
            <div className="mt-5 flex items-center justify-end gap-3">
              <button
                onClick={() => setConfirmDeleteOpen(false)}
                disabled={deleting}
                className="text-sm text-textSecondary hover:text-textPrimary disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deleting}
                className="rounded-full bg-red-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-red-700 disabled:opacity-50"
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

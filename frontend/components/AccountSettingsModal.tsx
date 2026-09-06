"use client";

import { useState } from "react";
import { supabase } from "@/lib/supabase";
import { api } from "@/lib/api";
import type { Profile } from "@/lib/types";

export type AccountSettingsModalProps = {
  open: boolean;
  onClose: () => void;
  profile: Profile | null;
  onProfileUpdated?: (profile: Profile) => void;
  onDeleted?: () => void;
};

export function AccountSettingsModal({
  open,
  onClose,
  profile,
  onProfileUpdated,
  onDeleted,
}: AccountSettingsModalProps) {
  const [fullName, setFullName] = useState(profile?.full_name ?? "");
  const [email, setEmail] = useState(profile?.email ?? "");
  const [marketingOptIn, setMarketingOptIn] = useState(profile?.marketing_opt_in ?? false);
  const [deadlineAlerts, setDeadlineAlerts] = useState(true);

  // Password change state
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // UI state
  const [savingInfo, setSavingInfo] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Danger Zone state
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  if (!open) return null;

  const clearMessages = () => {
    setError(null);
    setSuccess(null);
  };

  const handleUpdateInfo = async () => {
    clearMessages();
    setSavingInfo(true);
    try {
      if (supabase) {
        const { error: updateErr } = await supabase.auth.updateUser({
          email: email.trim(),
          data: { full_name: fullName.trim() },
        });
        if (updateErr) {
          setError(updateErr.message);
          return;
        }
      }
      // Also update the profiles table
      if (supabase && profile?.id) {
        try {
          await supabase
            .from("profiles")
            .update({
              full_name: fullName.trim(),
              email: email.trim(),
              updated_at: new Date().toISOString(),
            })
            .eq("id", profile.id);
        } catch {
          // Best-effort — auth user is updated
        }
      }
      setSuccess("Account info updated successfully.");
      if (onProfileUpdated && profile) {
        onProfileUpdated({ ...profile, full_name: fullName.trim(), email: email.trim() });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update account info");
    } finally {
      setSavingInfo(false);
    }
  };

  const handleChangePassword = async () => {
    clearMessages();
    if (newPassword.length < 6) {
      setError("New password must be at least 6 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }
    setSavingPassword(true);
    try {
      if (supabase) {
        const { error: pwdErr } = await supabase.auth.updateUser({
          password: newPassword,
        });
        if (pwdErr) {
          setError(pwdErr.message);
          return;
        }
      }
      setSuccess("Password updated successfully.");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update password");
    } finally {
      setSavingPassword(false);
    }
  };

  const handleSavePrefs = async () => {
    clearMessages();
    setSavingPrefs(true);
    try {
      if (supabase && profile?.id) {
        try {
          await supabase
            .from("profiles")
            .update({
              marketing_opt_in: marketingOptIn,
              marketing_opt_in_at: marketingOptIn ? new Date().toISOString() : null,
              updated_at: new Date().toISOString(),
            })
            .eq("id", profile.id);
        } catch {
          // Best-effort
        }
      }
      setSuccess("Preferences saved.");
      if (onProfileUpdated && profile) {
        onProfileUpdated({ ...profile, marketing_opt_in: marketingOptIn });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save preferences");
    } finally {
      setSavingPrefs(false);
    }
  };

  const handleDeleteAccount = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteAccount();
      if (supabase) {
        try {
          await supabase.auth.signOut();
        } catch {
          // Best-effort
        }
      }
      try {
        localStorage.removeItem("grantrx_profile");
      } catch {
        // ignore
      }
      setConfirmDeleteOpen(false);
      onDeleted?.();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Failed to delete account");
    } finally {
      setDeleting(false);
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
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <h2 className="font-serif text-2xl font-bold text-textPrimary">
            Account Settings
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
        {success && (
          <div className="mb-4 rounded-xl bg-aquamarine/20 px-4 py-3 text-sm text-textPrimary">
            {success}
          </div>
        )}

        {/* User Info Section */}
        <section className="space-y-4">
          <h3 className="font-serif text-base font-semibold text-textPrimary">
            User Information
          </h3>
          <div>
            <label className="block text-sm font-medium text-textSecondary">
              Full Name
            </label>
            <input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="mt-1 w-full rounded-xl border border-textSecondary/20 bg-white px-4 py-2.5 text-textPrimary"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-textSecondary">
              Email Address
            </label>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              className="mt-1 w-full rounded-xl border border-textSecondary/20 bg-white px-4 py-2.5 text-textPrimary"
            />
          </div>
          <button
            onClick={handleUpdateInfo}
            disabled={savingInfo}
            className="rounded-full bg-crayolaBlue px-6 py-2 text-sm font-medium text-surfaceBg disabled:opacity-50"
          >
            {savingInfo ? "Saving…" : "Update Info"}
          </button>
        </section>

        <hr className="my-6 border-textSecondary/10" />

        {/* Security Section */}
        <section className="space-y-4">
          <h3 className="font-serif text-base font-semibold text-textPrimary">
            Security
          </h3>
          <div>
            <label className="block text-sm font-medium text-textSecondary">
              New Password
            </label>
            <input
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              type="password"
              placeholder="At least 6 characters"
              className="mt-1 w-full rounded-xl border border-textSecondary/20 bg-white px-4 py-2.5 text-textPrimary"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-textSecondary">
              Confirm New Password
            </label>
            <input
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              type="password"
              placeholder="Re-enter new password"
              className="mt-1 w-full rounded-xl border border-textSecondary/20 bg-white px-4 py-2.5 text-textPrimary"
            />
          </div>
          <button
            onClick={handleChangePassword}
            disabled={savingPassword}
            className="rounded-full bg-crayolaBlue px-6 py-2 text-sm font-medium text-surfaceBg disabled:opacity-50"
          >
            {savingPassword ? "Updating…" : "Change Password"}
          </button>
        </section>

        <hr className="my-6 border-textSecondary/10" />

        {/* Preferences Section */}
        <section className="space-y-4">
          <h3 className="font-serif text-base font-semibold text-textPrimary">
            Preferences
          </h3>
          <label className="flex items-start gap-2 text-xs text-slate-600 leading-normal">
            <input
              type="checkbox"
              checked={marketingOptIn}
              onChange={(e) => setMarketingOptIn(e.target.checked)}
              className="h-4 w-4 shrink-0 rounded border-slate-300 text-blueEnergy focus:ring-blueEnergy/30 focus:ring-offset-0"
            />
            <span>
              I opt in to receive marketing emails, scholarship alerts, and
              updates from GrantRx.
            </span>
          </label>
          <label className="flex items-start gap-2 text-xs text-slate-600 leading-normal">
            <input
              type="checkbox"
              checked={deadlineAlerts}
              onChange={(e) => setDeadlineAlerts(e.target.checked)}
              className="h-4 w-4 shrink-0 rounded border-slate-300 text-blueEnergy focus:ring-blueEnergy/30 focus:ring-offset-0"
            />
            <span>
              Send me weekly deadline reminders for scholarships I&apos;m
              tracking.
            </span>
          </label>
          <button
            onClick={handleSavePrefs}
            disabled={savingPrefs}
            className="rounded-full bg-crayolaBlue px-6 py-2 text-sm font-medium text-surfaceBg disabled:opacity-50"
          >
            {savingPrefs ? "Saving…" : "Save Preferences"}
          </button>
        </section>

        <hr className="my-6 border-textSecondary/10" />

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
}

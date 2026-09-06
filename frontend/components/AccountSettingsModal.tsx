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
  onUpgrade?: () => void;
};

type SettingsTab = "general" | "subscription" | "security";

export function AccountSettingsModal({
  open,
  onClose,
  profile,
  onProfileUpdated,
  onDeleted,
  onUpgrade,
}: AccountSettingsModalProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");

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

  // Billing portal state
  const [portalLoading, setPortalLoading] = useState(false);

  // Account deletion state
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
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

  const handleManageSubscription = async () => {
    clearMessages();
    setPortalLoading(true);
    try {
      const { url } = await api.createBillingPortalSession();
      if (url) {
        window.location.href = url;
      } else {
        setError("Failed to open billing portal. Please try again.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to open billing portal.");
    } finally {
      setPortalLoading(false);
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

  const isPremium = profile?.subscription_tier === "premium";
  const stripeStatus = profile?.stripe_subscription_status;

  const TABS: { id: SettingsTab; label: string }[] = [
    { id: "general", label: "General & Profile" },
    { id: "subscription", label: "Subscription & Billing" },
    { id: "security", label: "Security & Danger Zone" },
  ];

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

        {/* Tab Navigation */}
        <div className="mb-6 flex gap-1 rounded-xl bg-textSecondary/10 p-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => { setActiveTab(tab.id); clearMessages(); }}
              className={`flex-1 rounded-lg px-3 py-2 text-xs font-medium transition ${
                activeTab === tab.id
                  ? "bg-crayolaBlue text-surfaceBg"
                  : "text-textSecondary hover:text-textPrimary"
              }`}
            >
              {tab.label}
            </button>
          ))}
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

        {/* ─────────────────────────────────────────────────────────────── */}
        {/* Tab 1: General & Profile */}
        {/* ─────────────────────────────────────────────────────────────── */}
        {activeTab === "general" && (
          <div className="space-y-6">
            {/* User Info */}
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

            <hr className="border-textSecondary/10" />

            {/* Degree / Discipline preferences (read-only summary) */}
            <section className="space-y-2">
              <h3 className="font-serif text-base font-semibold text-textPrimary">
                Degree & Discipline
              </h3>
              <p className="text-sm text-textSecondary">
                {profile?.primary_discipline
                  ? `Primary discipline: ${profile.primary_discipline}`
                  : "No primary discipline set."}
              </p>
              <p className="text-sm text-textSecondary">
                {profile?.target_credential
                  ? `Target credential: ${profile.target_credential}`
                  : "No target credential set."}
              </p>
              <p className="text-xs text-textSecondary">
                Update these in the Profile Edit modal from the Left Panel.
              </p>
            </section>

            <hr className="border-textSecondary/10" />

            {/* Communication Preferences */}
            <section className="space-y-4">
              <h3 className="font-serif text-base font-semibold text-textPrimary">
                Communication Preferences
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
          </div>
        )}

        {/* ─────────────────────────────────────────────────────────────── */}
        {/* Tab 2: Subscription & Billing */}
        {/* ─────────────────────────────────────────────────────────────── */}
        {activeTab === "subscription" && (
          <div className="space-y-6">
            {/* Current Plan Status */}
            <section className="space-y-3">
              <h3 className="font-serif text-base font-semibold text-textPrimary">
                Current Plan
              </h3>
              <div className="flex items-center gap-3">
                <span
                  className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                    isPremium
                      ? "bg-aquamarine/20 text-textPrimary"
                      : "bg-textSecondary/10 text-textSecondary"
                  }`}
                >
                  {isPremium ? "GrantRx Premium" : "Free Tier"}
                </span>
                <span className="text-xs text-textSecondary">
                  {isPremium ? "$10/mo or $79/yr" : "Limited searches & features"}
                </span>
              </div>
              {isPremium && stripeStatus && (
                <p className="text-xs text-textSecondary">
                  Subscription status:{" "}
                  <span className="font-medium text-textPrimary">
                    {stripeStatus}
                  </span>
                </p>
              )}
            </section>

            <hr className="border-textSecondary/10" />

            {/* Free users — upgrade CTA */}
            {!isPremium && (
              <section className="space-y-4">
                <h3 className="font-serif text-base font-semibold text-textPrimary">
                  Upgrade to Premium
                </h3>
                <ul className="space-y-2 text-sm text-textSecondary">
                  <li className="flex items-start gap-2">
                    <svg className="mt-0.5 h-4 w-4 shrink-0 text-aquamarine" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.854 3.853 7.146-9.427a.75.75 0 011.05-.143z" clipRule="evenodd" />
                    </svg>
                    Unlimited keyword searches
                  </li>
                  <li className="flex items-start gap-2">
                    <svg className="mt-0.5 h-4 w-4 shrink-0 text-aquamarine" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.854 3.853 7.146-9.427a.75.75 0 011.05-.143z" clipRule="evenodd" />
                    </svg>
                    Full Kanban application pipeline
                  </li>
                  <li className="flex items-start gap-2">
                    <svg className="mt-0.5 h-4 w-4 shrink-0 text-aquamarine" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.854 3.853 7.146-9.427a.75.75 0 011.05-.143z" clipRule="evenodd" />
                    </svg>
                    Calendar sync (.ics) and deadline reminders
                  </li>
                </ul>
                <button
                  onClick={() => {
                    onClose();
                    onUpgrade?.();
                  }}
                  className="rounded-full bg-crayolaBlue px-6 py-2.5 text-sm font-medium text-surfaceBg"
                >
                  Upgrade to Premium
                </button>
              </section>
            )}

            {/* Premium users — manage subscription */}
            {isPremium && (
              <section className="space-y-4">
                <h3 className="font-serif text-base font-semibold text-textPrimary">
                  Manage Subscription
                </h3>
                <p className="text-sm text-textSecondary">
                  Update your payment method, change billing plans, or cancel
                  your subscription via the Stripe billing portal.
                </p>
                <button
                  onClick={handleManageSubscription}
                  disabled={portalLoading}
                  className="rounded-full bg-crayolaBlue px-6 py-2.5 text-sm font-medium text-surfaceBg disabled:opacity-50"
                >
                  {portalLoading ? "Opening…" : "Manage Subscription & Billing"}
                </button>

                {/* Cancel Subscription */}
                <div className="pt-2">
                  <button
                    onClick={handleManageSubscription}
                    disabled={portalLoading}
                    className="text-sm font-medium text-textSecondary underline hover:text-textPrimary disabled:opacity-50"
                  >
                    Cancel Subscription
                  </button>
                  <p className="mt-1 text-xs text-textSecondary">
                    To cancel or pause your plan without losing your data until
                    the end of your billing cycle, proceed to your billing
                    portal.
                  </p>
                </div>
              </section>
            )}
          </div>
        )}

        {/* ─────────────────────────────────────────────────────────────── */}
        {/* Tab 3: Security & Danger Zone */}
        {/* ─────────────────────────────────────────────────────────────── */}
        {activeTab === "security" && (
          <div className="space-y-6">
            {/* Password Update */}
            <section className="space-y-4">
              <h3 className="font-serif text-base font-semibold text-textPrimary">
                Change Password
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

            {/* Danger Zone — Account Deletion */}
            <div className="rounded-xl border border-red-200 bg-red-50/50 p-5 mt-6">
              <h3 className="text-red-700 font-semibold text-sm mb-1">
                Delete Account
              </h3>
              <p className="mt-1 text-xs text-textSecondary">
                Permanently purge your account, saved scholarships, budget
                details, and immediately terminate any active subscription.
                This action cannot be undone.
              </p>
              <button
                onClick={() => {
                  setConfirmDeleteOpen(true);
                  setDeleteConfirmText("");
                  setDeleteError(null);
                }}
                disabled={deleting}
                className="mt-3 rounded-full bg-red-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                Delete My Account & Data
              </button>
              {deleteError && (
                <p className="mt-2 text-xs text-red-600">{deleteError}</p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Confirmation modal — requires typing DELETE */}
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
              Are you sure? This will immediately terminate any active
              subscription and permanently delete your profile, budget, and
              saved scholarships. Type{" "}
              <span className="font-bold text-red-700">DELETE</span> to confirm.
            </p>
            <input
              type="text"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="Type DELETE to confirm"
              className="mt-4 w-full rounded-xl border border-red-200 bg-white px-4 py-2.5 text-sm text-textPrimary focus:border-red-500 focus:outline-none focus:ring-2 focus:ring-red-100"
            />
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
                disabled={deleting || deleteConfirmText.trim() !== "DELETE"}
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

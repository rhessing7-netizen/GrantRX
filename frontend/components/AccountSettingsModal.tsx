"use client";

import { useEffect, useState } from "react";
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

/** Friendly labels for raw Stripe subscription status enums. */
const STRIPE_STATUS_LABELS: Record<string, string> = {
  active: "Active",
  trialing: "Trial",
  past_due: "Payment past due",
  unpaid: "Payment overdue",
  canceled: "Cancelled",
  incomplete: "Setup incomplete",
  incomplete_expired: "Setup expired",
  paused: "Paused",
};

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

  const clearMessages = () => {
    setError(null);
    setSuccess(null);
  };

  const handleUpdateInfo = async () => {
    clearMessages();
    if (!supabase) {
      setError("Account updates are temporarily unavailable. Please try again later.");
      return;
    }
    setSavingInfo(true);
    const emailChanged = email.trim().toLowerCase() !== (profile?.email ?? "").toLowerCase();
    try {
      const { error: updateErr } = await supabase.auth.updateUser({
        email: email.trim(),
        data: { full_name: fullName.trim() },
      });
      if (updateErr) {
        setError(updateErr.message);
        return;
      }
      if (profile?.id) {
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
      setSuccess(
        emailChanged
          ? "Account info updated. Check your new email inbox to confirm the address change."
          : "Account info updated successfully.",
      );
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
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-text/40 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="mx-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-2xl bg-surface p-6 shadow-2xl sm:w-full sm:rounded-3xl sm:p-8"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Account settings"
      >
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <h2 className="font-serif text-2xl font-bold text-text">
            Account Settings
          </h2>
          <button
            onClick={onClose}
            className="text-sm text-textMuted hover:text-text"
          >
            Close
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="mb-6 flex flex-wrap gap-1 rounded-xl bg-textMuted/10 p-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => { setActiveTab(tab.id); clearMessages(); }}
              className={`flex-1 rounded-lg px-3 py-2 text-xs font-medium transition ${
                activeTab === tab.id
                  ? "bg-primary text-surface"
                  : "text-textMuted hover:text-text"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {error && (
          <div className="mb-4 rounded-xl bg-dangerSoft px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}
        {success && (
          <div className="mb-4 rounded-xl bg-accentSoft/20 px-4 py-3 text-sm text-text">
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
              <h3 className="font-serif text-base font-semibold text-text">
                User Information
              </h3>
              <div>
                <label className="block text-sm font-medium text-textMuted">
                  Full Name
                </label>
                <input
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="mt-1 w-full rounded-xl border border-textMuted/20 bg-white px-4 py-2.5 text-text"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-textMuted">
                  Email Address
                </label>
                <input
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  type="email"
                  className="mt-1 w-full rounded-xl border border-textMuted/20 bg-white px-4 py-2.5 text-text"
                />
              </div>
              <button
                onClick={handleUpdateInfo}
                disabled={savingInfo}
                className="rounded-full bg-primary px-6 py-2 text-sm font-medium text-surface disabled:opacity-50"
              >
                {savingInfo ? "Saving…" : "Update Info"}
              </button>
            </section>

            <hr className="border-textMuted/10" />

            {/* Degree / Discipline preferences (read-only summary) */}
            <section className="space-y-2">
              <h3 className="font-serif text-base font-semibold text-text">
                Degree & Discipline
              </h3>
              <p className="text-sm text-textMuted">
                {profile?.primary_discipline
                  ? `Primary discipline: ${profile.primary_discipline}`
                  : "No primary discipline set."}
              </p>
              <p className="text-sm text-textMuted">
                {profile?.target_credential
                  ? `Target credential: ${profile.target_credential}`
                  : "No target credential set."}
              </p>
              <p className="text-xs text-textMuted">
                Update these via Edit in your profile panel.
              </p>
            </section>

            <hr className="border-textMuted/10" />

            {/* Communication Preferences */}
            <section className="space-y-4">
              <h3 className="font-serif text-base font-semibold text-text">
                Communication Preferences
              </h3>
              <label className="flex items-start gap-2 text-xs text-textMuted leading-normal">
                <input
                  type="checkbox"
                  checked={marketingOptIn}
                  onChange={(e) => setMarketingOptIn(e.target.checked)}
                  className="h-4 w-4 shrink-0 rounded border-border text-secondary focus:ring-secondary/30 focus:ring-offset-0"
                />
                <span>
                  I opt in to receive funding alerts, weekly deadline
                  reminders for opportunities I&apos;m tracking, and email
                  updates from EdFintia.
                </span>
              </label>
              <button
                onClick={handleSavePrefs}
                disabled={savingPrefs}
                className="rounded-full bg-primary px-6 py-2 text-sm font-medium text-surface disabled:opacity-50"
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
              <h3 className="font-serif text-base font-semibold text-text">
                Current Plan
              </h3>
              <div className="flex items-center gap-3">
                <span
                  className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                    isPremium
                      ? "bg-accentSoft/20 text-text"
                      : "bg-textMuted/10 text-textMuted"
                  }`}
                >
                  {isPremium ? "EdFintia Premium" : "Free Tier"}
                </span>
                <span className="text-xs text-textMuted">
                  {isPremium
                    ? "$10/mo or $79/yr"
                    : "10 keyword searches per 7 days · 3 active applications"}
                </span>
              </div>
              {isPremium && stripeStatus && (
                <p className="text-xs text-textMuted">
                  Subscription status:{" "}
                  <span className="font-medium text-text">
                    {STRIPE_STATUS_LABELS[stripeStatus] ??
                      stripeStatus.replace(/_/g, " ")}
                  </span>
                </p>
              )}
            </section>

            <hr className="border-textMuted/10" />

            {/* Free users — upgrade CTA */}
            {!isPremium && (
              <section className="space-y-4">
                <h3 className="font-serif text-base font-semibold text-text">
                  Upgrade to Premium
                </h3>
                <ul className="space-y-2 text-sm text-textMuted">
                  <li className="flex items-start gap-2">
                    <svg className="mt-0.5 h-4 w-4 shrink-0 text-accentSoft" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.854 3.853 7.146-9.427a.75.75 0 011.05-.143z" clipRule="evenodd" />
                    </svg>
                    Unlimited keyword searches
                  </li>
                  <li className="flex items-start gap-2">
                    <svg className="mt-0.5 h-4 w-4 shrink-0 text-accentSoft" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.854 3.853 7.146-9.427a.75.75 0 011.05-.143z" clipRule="evenodd" />
                    </svg>
                    Unlimited active applications
                  </li>
                  <li className="flex items-start gap-2">
                    <svg className="mt-0.5 h-4 w-4 shrink-0 text-accentSoft" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.854 3.853 7.146-9.427a.75.75 0 011.05-.143z" clipRule="evenodd" />
                    </svg>
                    All matched results unmasked
                  </li>
                </ul>
                <button
                  onClick={() => {
                    onClose();
                    onUpgrade?.();
                  }}
                  className="rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface"
                >
                  Upgrade to Premium
                </button>
              </section>
            )}

            {/* Premium users — manage subscription */}
            {isPremium && (
              <section className="space-y-4">
                <h3 className="font-serif text-base font-semibold text-text">
                  Manage Subscription
                </h3>
                <p className="text-sm text-textMuted">
                  Update your payment method, change billing plans, or cancel
                  your subscription via the Stripe billing portal.
                </p>
                <button
                  onClick={handleManageSubscription}
                  disabled={portalLoading}
                  className="rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface disabled:opacity-50"
                >
                  {portalLoading ? "Opening…" : "Manage Subscription & Billing"}
                </button>

                {/* Cancel Subscription */}
                <div className="pt-2">
                  <button
                    onClick={handleManageSubscription}
                    disabled={portalLoading}
                    className="text-sm font-medium text-textMuted underline hover:text-text disabled:opacity-50"
                  >
                    Cancel Subscription
                  </button>
                  <p className="mt-1 text-xs text-textMuted">
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
              <h3 className="font-serif text-base font-semibold text-text">
                Change Password
              </h3>
              <div>
                <label className="block text-sm font-medium text-textMuted">
                  New Password
                </label>
                <input
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  type="password"
                  placeholder="At least 6 characters"
                  className="mt-1 w-full rounded-xl border border-textMuted/20 bg-white px-4 py-2.5 text-text"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-textMuted">
                  Confirm New Password
                </label>
                <input
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  type="password"
                  placeholder="Re-enter new password"
                  className="mt-1 w-full rounded-xl border border-textMuted/20 bg-white px-4 py-2.5 text-text"
                />
              </div>
              <button
                onClick={handleChangePassword}
                disabled={savingPassword}
                className="rounded-full bg-primary px-6 py-2 text-sm font-medium text-surface disabled:opacity-50"
              >
                {savingPassword ? "Updating…" : "Change Password"}
              </button>
            </section>

            {/* Danger Zone — Account Deletion */}
            <div className="rounded-xl border border-danger/30 bg-dangerSoft/50 p-5 mt-6">
              <h3 className="text-danger font-semibold text-sm mb-1">
                Delete Account
              </h3>
              <p className="mt-1 text-xs text-textMuted">
                Permanently purge your account, tracked opportunities, budget
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
                className="mt-3 rounded-full bg-danger px-5 py-2 text-sm font-medium text-white transition hover:bg-danger disabled:opacity-50"
              >
                Delete My Account & Data
              </button>
              {deleteError && (
                <p className="mt-2 text-xs text-danger">{deleteError}</p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Confirmation modal — requires typing DELETE */}
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
}

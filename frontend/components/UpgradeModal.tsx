"use client";

import { useEffect, useState } from "react";
import type { BillingPlan } from "@/lib/types";
import { api } from "@/lib/api";

export type UpgradeModalProps = {
  open: boolean;
  onClose: () => void;
  reason?: string;
};

const FEATURES = [
  { label: "Keyword Searches", free: "10 / week", premium: "Unlimited" },
  { label: "Unmasked Direct Links", free: "Top 3 only", premium: "All results" },
  { label: "Application Tracking", free: "3 active apps", premium: "Unlimited" },
  { label: "Calendar Sync (.ics)", free: "Included", premium: "Included" },
  { label: "Deadline Reminders", free: "Included", premium: "Included" },
  { label: "Missing-Criteria Feedback", free: "Included", premium: "Included" },
];

const PLANS: {
  id: BillingPlan;
  label: string;
  price: string;
  period: string;
  highlight?: boolean;
}[] = [
  { id: "monthly", label: "Monthly", price: "$9", period: "/mo" },
  { id: "annual", label: "Annual", price: "$79", period: "/yr", highlight: true },
];

export function UpgradeModal({ open, onClose, reason }: UpgradeModalProps) {
  const [selectedPlan, setSelectedPlan] = useState<BillingPlan>("annual");
  const [redirecting, setRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !redirecting) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose, redirecting]);

  if (!open) return null;

  const handleCheckout = async () => {
    setRedirecting(true);
    setError(null);
    try {
      const successUrl = `${window.location.origin}/?upgraded=true`;
      const cancelUrl = `${window.location.origin}`;
      const resp = await api.createCheckout(selectedPlan, successUrl, cancelUrl);
      window.location.href = resp.checkout_url;
    } catch (err) {
      const e = err as Error & { status?: number };
      if (e.status === 409) {
        setError("You're already on Premium. Try refreshing the page.");
      } else {
        setError(e.message || "Failed to start checkout. Please try again.");
      }
    } finally {
      setRedirecting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-text/40 p-4 backdrop-blur-sm"
      onClick={redirecting ? undefined : onClose}
    >
      <div
        className="mx-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl bg-surface p-6 shadow-2xl sm:w-full sm:rounded-3xl sm:p-8"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Upgrade to Premium"
      >
        {/* Header */}
        <div className="mb-6 text-center">
          <h2 className="font-serif text-2xl font-bold text-text">
            Upgrade to EdFintia Premium
          </h2>
          {reason && (
            <p className="mt-2 text-sm text-textMuted">{reason}</p>
          )}
        </div>

        {error && (
          <div className="mb-4 rounded-xl bg-dangerSoft px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        {/* Plan selector */}
        <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {PLANS.map((plan) => (
            <button
              key={plan.id}
              onClick={() => setSelectedPlan(plan.id)}
              disabled={redirecting}
              className={`relative rounded-2xl border-2 p-4 text-center transition disabled:opacity-60 ${
                selectedPlan === plan.id
                  ? "border-primary bg-primary/5"
                  : "border-textMuted/15 hover:border-primary/40"
              }`}
            >
              {plan.highlight && (
                <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 rounded-full bg-accentSoft px-3 py-0.5 text-[10px] font-bold text-text">
                  SAVE 27%
                </span>
              )}
              <p className="text-sm font-medium text-textMuted">{plan.label}</p>
              <p className="mt-1 font-serif text-2xl font-bold text-text">
                {plan.price}
                <span className="text-sm font-normal text-textMuted">
                  {plan.period}
                </span>
              </p>
            </button>
          ))}
        </div>

        {/* Feature comparison */}
        <div className="mb-6 overflow-x-auto rounded-2xl border border-textMuted/10">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="bg-surfaceSubtle">
                <th className="px-4 py-2.5 text-left font-medium text-textMuted">
                  Feature
                </th>
                <th className="px-4 py-2.5 text-center font-medium text-textMuted">
                  Free
                </th>
                <th className="px-4 py-2.5 text-center font-semibold text-primary">
                  Premium
                </th>
              </tr>
            </thead>
            <tbody>
              {FEATURES.map((f, i) => (
                <tr
                  key={f.label}
                  className={i % 2 === 0 ? "bg-surface" : "bg-surfaceSubtle/50"}
                >
                  <td className="px-4 py-2.5 text-text">{f.label}</td>
                  <td className="px-4 py-2.5 text-center text-textMuted">
                    {f.free}
                  </td>
                  <td className="px-4 py-2.5 text-center font-medium text-text">
                    {f.premium}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* CTA */}
        <p className="mb-3 text-xs text-textMuted leading-relaxed text-center">
          Subscription automatically renews{" "}
          {selectedPlan === "monthly" ? "monthly at $9.00/mo" : "annually at $79.00/yr"}{" "}
          until canceled. You can cancel online at any time with 1 click via
          your billing settings. No minimum commitment or phone calls required.
        </p>
        <button
          onClick={handleCheckout}
          disabled={redirecting}
          className="flex w-full items-center justify-center gap-2 rounded-full bg-gradient-to-r from-accentSoft to-accent py-3 text-sm font-bold text-text transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {redirecting ? (
            <>
              <svg
                className="h-4 w-4 animate-spin"
                fill="none"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
              Redirecting to secure checkout…
            </>
          ) : (
            `Upgrade with ${selectedPlan === "monthly" ? "$9/mo" : "$79/yr"}`
          )}
        </button>

        <button
          onClick={onClose}
          disabled={redirecting}
          className="mt-3 w-full text-center text-xs text-textMuted hover:text-text disabled:opacity-50"
        >
          Maybe later
        </button>
      </div>
    </div>
  );
}

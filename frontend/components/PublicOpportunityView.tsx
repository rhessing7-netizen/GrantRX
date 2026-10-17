"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, getAuthToken, setAuthToken } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { AuthModal } from "@/components/AuthModal";
import type { PublicOpportunity } from "@/lib/types";

/** EdFintia-hosted public opportunity detail.
 *
 * Anonymous visitors read a real, whitelisted catalog summary — the
 * external application URL is never in the page, the DOM, or client
 * state. Signing in (free or premium) reveals the official apply link via
 * the authenticated application-link endpoint, without navigating away.
 */

type LoadState = "loading" | "ready" | "notfound" | "error";

function formatDeadline(iso: string | null): string {
  if (!iso) return "No deadline listed";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return "No deadline listed";
  return d.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function humanize(raw: string | null | undefined): string | null {
  if (!raw) return null;
  return raw
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function formatMoney(amount: number | null): string | null {
  if (amount == null) return null;
  return `$${amount.toLocaleString()}`;
}

function Fact({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wider text-textMuted">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm text-text">{value}</dd>
    </div>
  );
}

function TagList({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((t) => (
        <li
          key={t}
          className="rounded-full border border-border px-2.5 py-1 text-xs font-medium text-textMuted"
        >
          {humanize(t) ?? t}
        </li>
      ))}
    </ul>
  );
}

export function PublicOpportunityView({ id }: { id: string }) {
  const [state, setState] = useState<LoadState>("loading");
  const [opp, setOpp] = useState<PublicOpportunity | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  // The official apply URL — populated ONLY after a valid authenticated
  // response; never present in anonymous state.
  const [appUrl, setAppUrl] = useState<string | null>(null);
  const [appLinkLoading, setAppLinkLoading] = useState(false);
  const [appLinkFailed, setAppLinkFailed] = useState(false);

  const load = useCallback(() => {
    setState("loading");
    setRetrying(false);
    api
      .getShowcaseItem(id, { onRetry: () => setRetrying(true) })
      .then((o) => {
        setOpp(o);
        setState("ready");
      })
      .catch((e: Error & { status?: number }) => {
        setState(e.status === 404 ? "notfound" : "error");
      });
  }, [id]);

  const loadAppLink = useCallback(() => {
    setAppLinkLoading(true);
    setAppLinkFailed(false);
    api
      .getApplicationLink(id)
      .then((l) => setAppUrl(l.url))
      .catch((e: Error & { status?: number }) => {
        if (e.status === 401) {
          // Expired/invalid token — treat as anonymous again.
          setAppUrl(null);
        } else if (e.status !== 404) {
          setAppLinkFailed(true);
        }
      })
      .finally(() => setAppLinkLoading(false));
  }, [id]);

  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  // If a session already exists (returning signed-in visitor, or an OAuth
  // round-trip landing back on this page), reveal the apply link — the
  // same flow a fresh in-page sign-in triggers.
  useEffect(() => {
    queueMicrotask(() => {
      if (getAuthToken()) {
        loadAppLink();
        return;
      }
      supabase?.auth
        .getSession()
        .then(({ data }) => {
          if (data.session?.access_token) {
            setAuthToken(data.session.access_token);
            loadAppLink();
          }
        })
        .catch(() => {});
    });
  }, [loadAppLink]);

  const handleAuthSuccess = useCallback(() => {
    setAuthOpen(false);
    loadAppLink();
  }, [loadAppLink]);

  const verified = opp?.verification_status === "verified";
  const locations = opp
    ? [
        ...opp.state_restrictions,
        ...opp.county_restrictions,
        ...opp.city_restrictions,
        ...opp.metro_restrictions,
      ]
    : [];
  const commitments: string[] = opp
    ? [
        opp.has_service_commitment
          ? `Service commitment${
              opp.service_commitment_duration_months
                ? ` (${opp.service_commitment_duration_months} months)`
                : ""
            }`
          : "",
        opp.employment_required
          ? `Employment required${
              opp.min_employment_tenure_months
                ? ` (minimum ${opp.min_employment_tenure_months} months tenure)`
                : ""
            }`
          : "",
      ].filter(Boolean)
    : [];

  return (
    <div className="min-h-screen bg-surface">
      {/* Branded header — same chrome as the other public pages */}
      <header className="border-b border-textMuted/10 bg-white/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
          <Link
            href="/"
            className="font-serif text-lg font-semibold text-text transition hover:text-primary"
          >
            ← Back to EdFintia
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-10" aria-busy={state === "loading"}>
        {state === "loading" && (
          <div className="animate-pulse space-y-4" aria-label="Loading opportunity details">
            <div className="h-8 w-2/3 rounded bg-textMuted/10" />
            <div className="h-4 w-1/3 rounded bg-textMuted/10" />
            <div className="h-24 rounded-2xl bg-textMuted/10" />
            <div className="h-40 rounded-2xl bg-textMuted/10" />
            {retrying && (
              <p className="text-sm text-textMuted">Still waking up the server…</p>
            )}
          </div>
        )}

        {state === "notfound" && (
          <div className="rounded-2xl bg-surfaceSubtle p-10 text-center">
            <h1 className="font-serif text-2xl font-bold text-text">
              Opportunity not available
            </h1>
            <p className="mt-2 text-sm text-textMuted">
              This opportunity is no longer listed — it may have closed or been
              removed from the catalog.
            </p>
            <Link
              href="/"
              className="mt-5 inline-block rounded-full bg-primary px-5 py-2 text-sm font-medium text-surface transition hover:opacity-90"
            >
              Browse opportunities
            </Link>
          </div>
        )}

        {state === "error" && (
          <div className="rounded-2xl bg-surfaceSubtle p-10 text-center">
            <h1 className="font-serif text-2xl font-bold text-text">
              Something went wrong
            </h1>
            <p className="mt-2 text-sm text-textMuted">
              We&apos;re having trouble loading this opportunity right now.
            </p>
            <button
              type="button"
              onClick={load}
              className="mt-5 rounded-full border border-primary px-5 py-2 text-sm font-medium text-primary transition hover:bg-primary/5"
            >
              Try again
            </button>
          </div>
        )}

        {state === "ready" && opp && (
          <article className="space-y-8">
            {/* Title block */}
            <div>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h1 className="font-serif text-3xl font-bold leading-tight text-text">
                    {opp.title}
                  </h1>
                  <p className="mt-1 text-sm font-semibold uppercase tracking-wider text-textMuted">
                    {opp.provider}
                  </p>
                </div>
                <span
                  className={`mt-1 inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-semibold ${
                    verified
                      ? "bg-successSoft text-success"
                      : "bg-surfaceSubtle text-textMuted"
                  }`}
                >
                  {verified ? "Source verified" : "Verification pending"}
                </span>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {opp.award_amount != null && (
                  <span className="rounded-full bg-primary px-3 py-1 text-sm font-semibold text-surface">
                    {formatMoney(opp.award_amount)}
                  </span>
                )}
                <span className="rounded-full bg-accentSoft px-3 py-1 text-sm font-semibold text-secondary">
                  {formatDeadline(opp.deadline)}
                </span>
                {humanize(opp.funding_type) && (
                  <span className="rounded-full bg-surfaceSubtle px-3 py-1 text-sm font-semibold text-textMuted">
                    {humanize(opp.funding_type)}
                  </span>
                )}
              </div>
            </div>

            {/* Scholarship Description — the persisted grounded narrative.
                Omitted entirely when the catalog has no description; never
                substituted with placeholder text. */}
            {opp.public_description && (
              <section aria-labelledby="description-heading">
                <h2
                  id="description-heading"
                  className="font-serif text-xl font-semibold text-text"
                >
                  Scholarship Description
                </h2>
                <div className="mt-3 space-y-3">
                  {opp.public_description
                    .split(/\n{2,}/)
                    .filter((p) => p.trim())
                    .map((p, i) => (
                      <p key={i} className="text-sm leading-relaxed text-textMuted">
                        {p}
                      </p>
                    ))}
                </div>
              </section>
            )}

            {/* Opportunity overview — composed only from stored fields */}
            <section aria-labelledby="overview-heading">
              <h2 id="overview-heading" className="font-serif text-xl font-semibold text-text">
                Opportunity Overview
              </h2>
              {opp.provider_mission && (
                <p className="mt-3 text-sm leading-relaxed text-textMuted">
                  {opp.provider_mission}
                </p>
              )}
              <dl className="mt-4 grid grid-cols-1 gap-4 rounded-2xl bg-surfaceSubtle p-5 sm:grid-cols-2">
                <Fact label="Award" value={formatMoney(opp.award_amount) ?? "Varies"} />
                <Fact
                  label="Deadline"
                  value={
                    opp.deadline
                      ? formatDeadline(opp.deadline)
                      : opp.estimated_next_cycle
                        ? `Next cycle est. ${formatDeadline(opp.estimated_next_cycle)}`
                        : "No deadline listed"
                  }
                />
                <Fact label="Funding type" value={humanize(opp.funding_type)} />
                <Fact
                  label="Competition"
                  value={humanize(opp.competition_level)}
                />
                <Fact
                  label="Minimum GPA"
                  value={opp.min_gpa > 0 ? opp.min_gpa.toFixed(1) : null}
                />
                <Fact
                  label="Max Student Aid Index"
                  value={opp.max_sai != null ? opp.max_sai.toLocaleString() : null}
                />
                <Fact
                  label="Annual benefit cap"
                  value={formatMoney(opp.annual_benefit_cap)}
                />
                <Fact
                  label="Coverage model"
                  value={humanize(opp.benefit_coverage_model)}
                />
                <Fact label="Partner network" value={opp.partner_network} />
                <Fact label="Platform" value={opp.vendor_platform} />
              </dl>
            </section>

            {/* Eligibility */}
            {(opp.eligible_disciplines.length > 0 ||
              opp.eligible_credentials.length > 0 ||
              opp.academic_levels.length > 0 ||
              opp.is_general_major ||
              opp.citizenship_requirement ||
              opp.enrollment_statuses.length > 0 ||
              opp.institution_restrictions.length > 0 ||
              opp.required_affiliations.length > 0 ||
              opp.military_affiliation_requirement) && (
              <section aria-labelledby="eligibility-heading">
                <h2 id="eligibility-heading" className="font-serif text-xl font-semibold text-text">
                  Eligibility
                </h2>
                <div className="mt-3 space-y-4">
                  {opp.eligible_disciplines.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-text">Fields of study</h3>
                      <div className="mt-2">
                        <TagList items={opp.eligible_disciplines} />
                      </div>
                    </div>
                  )}
                  {opp.is_general_major && (
                    <p className="text-sm text-textMuted">Open to all majors.</p>
                  )}
                  {opp.eligible_credentials.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-text">Credentials</h3>
                      <div className="mt-2">
                        <TagList items={opp.eligible_credentials} />
                      </div>
                    </div>
                  )}
                  {opp.academic_levels.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-text">Academic level</h3>
                      <div className="mt-2">
                        <TagList items={opp.academic_levels} />
                      </div>
                    </div>
                  )}
                  {opp.enrollment_statuses.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-text">Enrollment status</h3>
                      <div className="mt-2">
                        <TagList items={opp.enrollment_statuses} />
                      </div>
                    </div>
                  )}
                  {opp.institution_restrictions.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-text">Institutions</h3>
                      <div className="mt-2">
                        <TagList items={opp.institution_restrictions} />
                      </div>
                    </div>
                  )}
                  <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Fact label="Citizenship" value={humanize(opp.citizenship_requirement)} />
                    <Fact
                      label="Military affiliation"
                      value={humanize(opp.military_affiliation_requirement)}
                    />
                  </dl>
                  {opp.required_affiliations.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-text">Required affiliations</h3>
                      <div className="mt-2">
                        <TagList items={opp.required_affiliations} />
                      </div>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Location */}
            {(opp.scope || locations.length > 0) && (
              <section aria-labelledby="location-heading">
                <h2 id="location-heading" className="font-serif text-xl font-semibold text-text">
                  Location
                </h2>
                <div className="mt-3 space-y-3">
                  <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Fact label="Geographic scope" value={humanize(opp.scope)} />
                  </dl>
                  {locations.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-text">
                        Restricted to
                      </h3>
                      <div className="mt-2">
                        <TagList items={locations} />
                      </div>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Commitments */}
            {commitments.length > 0 && (
              <section aria-labelledby="commitments-heading">
                <h2 id="commitments-heading" className="font-serif text-xl font-semibold text-text">
                  Requirements &amp; Commitments
                </h2>
                <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-textMuted">
                  {commitments.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </section>
            )}

            {/* Provider */}
            {(opp.provider_type ||
              opp.provider_core_values.length > 0 ||
              opp.target_community) && (
              <section aria-labelledby="provider-heading">
                <h2 id="provider-heading" className="font-serif text-xl font-semibold text-text">
                  About the Provider
                </h2>
                <div className="mt-3 space-y-3">
                  <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Fact label="Provider type" value={humanize(opp.provider_type)} />
                    <Fact label="Community served" value={opp.target_community} />
                  </dl>
                  {opp.provider_core_values.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-text">Values</h3>
                      <div className="mt-2">
                        <TagList items={opp.provider_core_values} />
                      </div>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Apply CTA — anonymous: opens auth; authenticated: official link.
                Rendered AFTER the informational sections so visitors read the
                opportunity before seeing the application action. */}
            <section
              aria-labelledby="apply-heading"
              className="rounded-2xl border border-primary/20 bg-primary/5 p-6"
            >
              <h2 id="apply-heading" className="font-serif text-lg font-semibold text-text">
                Ready to apply?
              </h2>
              {appUrl ? (
                <>
                  <p className="mt-1 text-sm text-textMuted">
                    You&apos;ll complete this application on the provider&apos;s
                    official website.
                  </p>
                  <a
                    href={appUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-4 inline-block rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface transition hover:opacity-90"
                  >
                    Apply on the official site ↗
                  </a>
                </>
              ) : appLinkLoading ? (
                <p className="mt-3 text-sm text-textMuted">Checking your account…</p>
              ) : appLinkFailed && getAuthToken() ? (
                <>
                  <p className="mt-1 text-sm text-textMuted">
                    We couldn&apos;t load the application link.
                  </p>
                  <button
                    type="button"
                    onClick={loadAppLink}
                    className="mt-4 rounded-full border border-primary px-5 py-2 text-sm font-medium text-primary transition hover:bg-primary/5"
                  >
                    Try again
                  </button>
                </>
              ) : (
                <>
                  <p className="mt-1 text-sm text-textMuted">
                    The official application link is available with any free
                    EdFintia account.
                  </p>
                  <button
                    type="button"
                    onClick={() => setAuthOpen(true)}
                    className="mt-4 rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-surface transition hover:opacity-90"
                  >
                    Sign In / Create Free Account to Apply
                  </button>
                </>
              )}
            </section>

            {opp.matching_tags.length > 0 && (
              <section aria-labelledby="tags-heading">
                <h2 id="tags-heading" className="sr-only">
                  Tags
                </h2>
                <TagList items={opp.matching_tags} />
              </section>
            )}

            {/* Required disclaimer */}
            <p className="rounded-xl border border-border/60 bg-surfaceSubtle p-4 text-xs leading-relaxed text-textMuted">
              EdFintia summarizes opportunity information to help you discover
              education funding. Eligibility requirements and deadlines can
              change. Review the official provider application before
              submitting.
            </p>
          </article>
        )}
      </main>

      <AuthModal
        open={authOpen}
        onClose={() => setAuthOpen(false)}
        onAuthSuccess={handleAuthSuccess}
      />
    </div>
  );
}

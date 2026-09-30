import type { Metadata } from "next";
import Link from "next/link";
import { BrandMark } from "@/components/Brand";
import { EarlyAccessForm } from "@/components/EarlyAccessForm";

export const metadata: Metadata = {
  title: "Early Access",
  description:
    "Join the EdFintia early-access list. Discover legitimate scholarships, grants, fellowships, tuition assistance, and other education-funding opportunities you may qualify for — in one place.",
};

const CATEGORIES: { icon: string; label: string }[] = [
  { icon: "/brand/icons/scholarships.svg", label: "Scholarships" },
  { icon: "/brand/icons/grants.svg", label: "Grants" },
  { icon: "/brand/icons/fellowships.svg", label: "Fellowships" },
  { icon: "/brand/icons/tuition-assistance.svg", label: "Tuition assistance" },
  { icon: "/brand/icons/employer-programs.svg", label: "Employer education benefits" },
  { icon: "/brand/icons/healthcare-education.svg", label: "Healthcare workforce programs" },
  { icon: "/brand/icons/state-federal-programs.svg", label: "State & federal programs" },
];

const STEPS: { title: string; body: string }[] = [
  {
    title: "Join the list",
    body: "Tell us your name, email, and who you are — that's it. No lengthy profile, no sensitive questions.",
  },
  {
    title: "Get notified at launch",
    body: "We'll email you when early access opens so you're first through the door.",
  },
  {
    title: "See what you may qualify for",
    body: "Build a short profile at launch and get matched to opportunities worth your time.",
  },
];

export default function EarlyAccessPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" aria-label="EdFintia home">
            <BrandMark className="h-7 sm:h-8" />
          </Link>
          <Link
            href="/"
            className="text-sm font-medium text-textMuted transition hover:text-primary"
          >
            Sign in
          </Link>
        </div>
      </header>

      <main>
        {/* Hero + signup */}
        <section className="mx-auto grid max-w-6xl items-start gap-10 px-6 py-12 sm:py-16 lg:grid-cols-2 lg:gap-14">
          <div>
            <p className="font-editorial text-lg italic text-secondary">
              Your prescription for education funding.
            </p>
            <h1 className="mt-3 font-serif text-4xl font-bold leading-tight text-text sm:text-5xl">
              Education funding, without the scavenger hunt.
            </h1>
            <p className="mt-4 max-w-xl text-base leading-relaxed text-textMuted">
              Legitimate funding is scattered across hundreds of portals,
              associations, and employer programs. EdFintia brings it together
              and helps you find the opportunities you may actually qualify
              for — launching soon.
            </p>
            <ul className="mt-6 space-y-3 text-sm text-text">
              {[
                "One matched feed instead of dozens of fragmented sources",
                "Scholarships, grants, fellowships, tuition assistance, and more",
                "Deadline tracking and application tools from day one",
              ].map((item) => (
                <li key={item} className="flex items-start gap-3">
                  <span
                    aria-hidden="true"
                    className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accentSoft/60 text-xs font-bold text-navy"
                  >
                    ✓
                  </span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Signup card */}
          <div
            id="signup"
            className="rounded-2xl border border-border bg-surface p-6 shadow-sm sm:p-8"
          >
            <h2 className="font-serif text-2xl font-bold text-text">
              Join the early-access list
            </h2>
            <p className="mt-1 mb-5 text-sm text-textMuted">
              Be first in line when EdFintia opens.
            </p>
            <EarlyAccessForm />
          </div>
        </section>

        {/* Coverage */}
        <section className="border-y border-border bg-surfaceSubtle/60">
          <div className="mx-auto max-w-6xl px-6 py-12 sm:py-16">
            <h2 className="text-center font-serif text-3xl font-bold text-text">
              More than scholarships
            </h2>
            <p className="mx-auto mt-3 max-w-2xl text-center text-sm leading-relaxed text-textMuted">
              EdFintia covers the full landscape of legitimate education
              funding — so you stop missing programs you never knew existed.
            </p>
            <ul className="mx-auto mt-8 grid max-w-4xl grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
              {CATEGORIES.map((c) => (
                <li
                  key={c.label}
                  className="flex flex-col items-center gap-3 rounded-xl border border-border bg-surface px-4 py-5 text-center"
                >
                  <img src={c.icon} alt="" aria-hidden="true" className="h-9 w-9" />
                  <span className="text-sm font-medium text-text">{c.label}</span>
                </li>
              ))}
              <li className="flex flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-accent/50 bg-surface px-4 py-5 text-center">
                <span className="text-sm font-medium text-secondary">
                  Professional associations
                </span>
                <span className="text-xs text-textMuted">
                  service-based &amp; loan-repayment programs, and more
                </span>
              </li>
            </ul>
          </div>
        </section>

        {/* How it works */}
        <section className="mx-auto max-w-6xl px-6 py-12 sm:py-16">
          <h2 className="text-center font-serif text-3xl font-bold text-text">
            How early access works
          </h2>
          <ol className="mx-auto mt-8 grid max-w-4xl gap-6 sm:grid-cols-3">
            {STEPS.map((step, i) => (
              <li
                key={step.title}
                className="rounded-xl border border-border bg-surface p-6"
              >
                <span
                  aria-hidden="true"
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 font-serif text-sm font-bold text-primary"
                >
                  {i + 1}
                </span>
                <h3 className="mt-3 font-serif text-lg font-semibold text-text">
                  {step.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-textMuted">
                  {step.body}
                </p>
              </li>
            ))}
          </ol>
        </section>

        {/* Fine print */}
        <section className="mx-auto max-w-3xl px-6 pb-14">
          <p className="rounded-xl bg-surfaceSubtle px-5 py-4 text-center text-xs leading-relaxed text-textMuted">
            EdFintia helps you discover legitimate education-funding
            opportunities you may qualify for. Eligibility and awards are
            determined by each program&rsquo;s provider — funding is never
            guaranteed.
          </p>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 py-8 sm:flex-row">
          <BrandMark size="sm" />
          <nav className="flex gap-6 text-sm text-textMuted" aria-label="Legal">
            <Link href="/privacy" className="transition hover:text-primary">
              Privacy
            </Link>
            <Link href="/terms" className="transition hover:text-primary">
              Terms
            </Link>
            <Link href="/" className="transition hover:text-primary">
              Home
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}

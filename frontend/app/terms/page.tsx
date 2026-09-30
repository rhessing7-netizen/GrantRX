import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Terms of Service — EdFintia",
  description: "EdFintia Terms of Service and user agreement.",
};

export default function TermsPage() {
  return (
    <div className="min-h-screen bg-surface">
      {/* Header */}
      <header className="border-b border-textMuted/10 bg-white/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
          <Link
            href="/"
            className="font-serif text-lg font-semibold text-text hover:text-primary transition"
          >
            ← Back to EdFintia
          </Link>
          <span className="text-xs text-textMuted">Last updated: September 2026</span>
        </div>
      </header>

      {/* Body */}
      <main className="mx-auto max-w-3xl px-6 py-12">
        <h1 className="font-serif text-3xl font-bold text-text">
          Terms of Service
        </h1>
        <p className="mt-2 text-sm text-textMuted">
          These terms govern your use of EdFintia. By creating an account, you
          agree to the terms below.
        </p>

        <div className="mt-10 space-y-8">
          {/* 1. Service Description */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              1. Service Description
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              EdFintia is an educational platform that helps students and
              professionals discover legitimate education-funding
              opportunities — including scholarships, grants, fellowships,
              tuition assistance, employer-sponsored education benefits,
              workforce programs, and loan-repayment programs. The Service
              provides AI-powered matching based on user-provided academic
              and demographic profile information, an application tracker,
              deadline calendar reminders, and curated discovery feeds. EdFintia does not directly award funding and
              is not affiliated with any opportunity provider unless
              explicitly stated.
            </p>
          </section>

          {/* 2. Eligibility */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              2. Eligibility
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              EdFintia is designed for students enrolled in or applying to
              postsecondary education, professional training, and workforce
              programs across a broad range of fields — with particular depth
              in clinical and healthcare programs, including but not limited
              to pharmacy, medicine, nursing, therapeutic rehabilitation,
              diagnostic imaging, and public health &amp; emergency medicine.
              You must be at least 13 years of
              age to create an account. If you are under 18, you represent that
              you have obtained parental or guardian consent to use the Service.
            </p>
          </section>

          {/* 3. User Accounts */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              3. User Accounts
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              You are responsible for maintaining the confidentiality of your
              account credentials and for all activities that occur under your
              account. You agree to provide accurate, current, and complete
              information during registration and to update such information to
              keep it accurate. EdFintia reserves the right to suspend or
              terminate accounts that provide false information or violate
              these Terms.
            </p>
          </section>

          {/* 4. Free Tier & Paid Subscriptions */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              4. Free Tier Limits &amp; Paid Subscriptions
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              EdFintia offers a Free tier and a Premium subscription:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textMuted">
              <li>
                <strong className="text-text">Free Tier:</strong> Includes
                up to 10 keyword searches per rolling 7-day cycle, visibility of
                the top 3 matched results per search, tracking of up to 3 active
                applications, and basic missing-criteria feedback.
              </li>
              <li>
                <strong className="text-text">Premium Subscription:</strong>{" "}
                Billed at $10/month or $79/year via Stripe. Includes unlimited
                keyword searches, full unmasked result visibility, and
                unlimited application tracking.
              </li>
            </ul>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              Subscription fees are billed in advance on a recurring basis
              (monthly or annually, depending on your selected plan). You may
              cancel your subscription at any time; cancellation takes effect at
              the end of the current billing period. Refunds are issued at
              EdFintia&apos;s sole discretion. Pricing is subject to change with
              at least 30 days&apos; notice before the next billing cycle.
            </p>
          </section>

          {/* 5. Disclaimers */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              5. Disclaimers
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              EdFintia provides education-funding matching based on the
              information you provide and publicly available data. EdFintia does
              not guarantee that you will receive any scholarship, grant,
              tuition benefit, or other funding award.
              Match results are algorithmic recommendations and should not be
              construed as an endorsement or guarantee of eligibility. You are
              solely responsible for verifying eligibility requirements,
              deadlines, and application instructions with the opportunity
              provider. EdFintia is not liable for missed deadlines, incorrect
              information, or any outcomes resulting from the use of the Service.
            </p>
          </section>

          {/* 6. Intellectual Property */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              6. Intellectual Property
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              The Service, including its design, matching algorithms, software
              code, branding, and content, is the intellectual property of
              EdFintia and its licensors. You may not copy, modify, distribute,
              reverse-engineer, or create derivative works from the Service
              without prior written consent. Education-funding data aggregated by
              EdFintia is sourced from public providers; respective rights remain
              with the original publishers.
            </p>
          </section>

          {/* 7. Termination */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              7. Termination
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              You may delete your account at any time by contacting EdFintia
              support. EdFintia reserves the right to suspend or terminate your
              access to the Service for any violation of these Terms, fraudulent
              activity, or abusive behavior. Upon termination, your right to use
              the Service ceases immediately. Sections relating to
              disclaimers, intellectual property, and liability shall survive
              termination.
            </p>
          </section>
        </div>

        {/* Footer */}
        <footer className="mt-16 border-t border-textMuted/10 pt-6 text-center text-xs text-textMuted">
          <p>
            © 2026 EdFintia. All rights reserved.{" "}
            <Link href="/privacy" className="text-primary underline">
              Privacy Policy
            </Link>
          </p>
        </footer>
      </main>
    </div>
  );
}

import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy — GrantRx",
  description: "GrantRx Privacy Policy and data handling practices.",
};

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-surfaceBg">
      {/* Header */}
      <header className="border-b border-textSecondary/10 bg-white/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
          <Link
            href="/"
            className="font-serif text-lg font-semibold text-textPrimary hover:text-crayolaBlue transition"
          >
            ← Back to GrantRx
          </Link>
          <span className="text-xs text-textSecondary">Last updated: September 2026</span>
        </div>
      </header>

      {/* Body */}
      <main className="mx-auto max-w-3xl px-6 py-12">
        <h1 className="font-serif text-3xl font-bold text-textPrimary">
          Privacy Policy
        </h1>
        <p className="mt-2 text-sm text-textSecondary">
          This policy describes how GrantRx collects, uses, and protects your
          personal information.
        </p>

        <div className="mt-10 space-y-8">
          {/* 1. Information Collected */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-textPrimary">
              1. Information We Collect
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textSecondary">
              When you create a GrantRx account and complete your profile, we
              collect the following categories of information:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textSecondary">
              <li>
                <strong className="text-textPrimary">Identity:</strong> Full
                name and email address (used for authentication and
                communication).
              </li>
              <li>
                <strong className="text-textPrimary">Academic Profile:</strong>{" "}
                Clinical discipline, target credential, clinical phase, GPA,
                and state of residence.
              </li>
              <li>
                <strong className="text-textPrimary">Financial Aid:</strong>{" "}
                Student Aid Index (SAI) score, used to match need-based
                scholarships.
              </li>
              <li>
                <strong className="text-textPrimary">Demographics:</strong>{" "}
                First-generation status and minority flag (optional, used to
                match diversity and affinity scholarships).
              </li>
              <li>
                <strong className="text-textPrimary">Affiliations:</strong>{" "}
                Professional memberships (e.g., APhA, AMA) used to match
                association-sponsored grants.
              </li>
              <li>
                <strong className="text-textPrimary">Application Data:</strong>{" "}
                Scholarship tracking status, application notes, document links,
                and checklists you save in the Kanban tracker.
              </li>
            </ul>
          </section>

          {/* 2. How We Use Data */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-textPrimary">
              2. How We Use Your Data
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textSecondary">
              GrantRx uses your profile information to power our matching
              algorithm, which scores scholarships against your academic,
              demographic, and financial criteria. We also use your data to:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textSecondary">
              <li>Generate personalized scholarship match results and rankings.</li>
              <li>Send deadline reminder emails for tracked scholarships.</li>
              <li>Provide missing-criteria feedback to improve your eligibility.</li>
              <li>Maintain your Kanban application tracker and document vault.</li>
              <li>Improve matching accuracy and scholarship coverage over time.</li>
            </ul>
          </section>

          {/* 3. Third-Party Sharing */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-textPrimary">
              3. Third-Party Sharing
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textSecondary">
              GrantRx does not sell your personal information. We share data
              only with the following service providers, under their respective
              privacy policies:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textSecondary">
              <li>
                <strong className="text-textPrimary">Supabase:</strong> Handles
                user authentication, including OAuth sign-in via Google and
                LinkedIn. Supabase stores your email and hashed password; it
                does not access your academic profile data.
              </li>
              <li>
                <strong className="text-textPrimary">Stripe:</strong> Processes
                Premium subscription payments. Stripe receives your email and
                billing information; it does not receive your academic or
                demographic data.
              </li>
              <li>
                <strong className="text-textPrimary">Resend / SendGrid:</strong>{" "}
                Sends transactional and marketing emails (deadline digests,
                account notifications) on our behalf.
              </li>
            </ul>
          </section>

          {/* 4. Marketing Communications & Opt-Outs */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-textPrimary">
              4. Marketing Communications &amp; Opt-Outs
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textSecondary">
              GrantRx complies with the CAN-SPAM Act. We send marketing emails
              (including deadline digest notifications) only to users who have
              explicitly opted in during registration or in their profile
              settings. You may opt out at any time by:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textSecondary">
              <li>Unchecking the marketing opt-in box in your profile settings.</li>
              <li>Clicking the unsubscribe link at the bottom of any marketing email.</li>
              <li>Contacting us directly to request removal from our mailing list.</li>
            </ul>
            <p className="mt-3 text-sm leading-relaxed text-textSecondary">
              Transactional emails (account verification, password resets,
              payment receipts) are sent regardless of marketing preferences,
              as they are necessary for the Service to function.
            </p>
          </section>

          {/* 5. Data Retention */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-textPrimary">
              5. Data Retention
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textSecondary">
              We retain your profile data for as long as your account is active.
              If you delete your account, we remove your personal information
              from our primary databases within 30 days, except where retention
              is required by law (e.g., financial transaction records retained
              for tax compliance). Anonymous, aggregated data that cannot
              identify you may be retained indefinitely for analytics purposes.
            </p>
          </section>

          {/* 6. User Rights */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-textPrimary">
              6. Your Rights
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textSecondary">
              Depending on your jurisdiction, you may have the following rights
              regarding your personal data:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textSecondary">
              <li><strong className="text-textPrimary">Access:</strong> Request a copy of the data we hold about you.</li>
              <li><strong className="text-textPrimary">Correction:</strong> Update inaccurate or incomplete information.</li>
              <li><strong className="text-textPrimary">Deletion:</strong> Request deletion of your account and associated data.</li>
              <li><strong className="text-textPrimary">Portability:</strong> Receive your data in a machine-readable format.</li>
              <li><strong className="text-textPrimary">Opt-Out:</strong> Unsubscribe from marketing communications at any time.</li>
            </ul>
            <p className="mt-3 text-sm leading-relaxed text-textSecondary">
              To exercise any of these rights, contact us at
              <a href="mailto:privacy@grantrx.app" className="text-crayolaBlue hover:underline"> privacy@grantrx.app</a>.
              We will respond within 30 days.
            </p>
          </section>
        </div>

        {/* Footer */}
        <footer className="mt-16 border-t border-textSecondary/10 pt-6 text-center text-xs text-textSecondary">
          <p>
            © 2026 GrantRx. All rights reserved.{" "}
            <Link href="/terms" className="text-crayolaBlue hover:underline">
              Terms of Service
            </Link>
          </p>
        </footer>
      </main>
    </div>
  );
}

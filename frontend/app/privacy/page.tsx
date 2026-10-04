import type { Metadata } from "next";
import Link from "next/link";
import { PRIVACY_EMAIL } from "@/lib/config";

export const metadata: Metadata = {
  title: "Privacy Policy — EdFintia",
  description: "EdFintia Privacy Policy and data handling practices.",
};

export default function PrivacyPage() {
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
          <span className="text-xs text-textMuted">Last updated: October 2026</span>
        </div>
      </header>

      {/* Body */}
      <main className="mx-auto max-w-3xl px-6 py-12">
        <h1 className="font-serif text-3xl font-bold text-text">
          Privacy Policy
        </h1>
        <p className="mt-2 text-sm text-textMuted">
          This policy describes how EdFintia collects, uses, and protects your
          personal information.
        </p>

        <div className="mt-10 space-y-8">
          {/* 1. Information Collected */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              1. Information We Collect
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              When you create an EdFintia account and complete your profile, we
              collect the following categories of information:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textMuted">
              <li>
                <strong className="text-text">Identity:</strong> Full
                name and email address (used for authentication and
                communication).
              </li>
              <li>
                <strong className="text-text">Academic Profile:</strong>{" "}
                Fields of study, target credential, education stage, GPA,
                and state of residence.
              </li>
              <li>
                <strong className="text-text">Financial Aid:</strong>{" "}
                Student Aid Index (SAI) score, used to match need-based
                funding opportunities.
              </li>
              <li>
                <strong className="text-text">Demographics:</strong>{" "}
                First-generation status and minority flag (optional, used to
                match diversity and affinity opportunities).
              </li>
              <li>
                <strong className="text-text">Affiliations:</strong>{" "}
                Professional memberships (e.g., APhA, AMA) used to match
                association-sponsored funding.
              </li>
              <li>
                <strong className="text-text">Application Data:</strong>{" "}
                Application tracking status, notes, document links,
                and checklists you save in the application tracker.
              </li>
              <li>
                <strong className="text-text">Early-Access Signups:</strong>{" "}
                If you join our early-access or waitlist before creating an
                account, we collect your first name, email address, the
                audience type you select, and (optionally) your education
                path, along with a record of your consent and referral/UTM
                attribution from the link you arrived on.
              </li>
            </ul>
          </section>

          {/* 2. How We Use Data */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              2. How We Use Your Data
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              EdFintia uses your profile information to power our matching
              algorithm, which scores funding opportunities against your academic,
              demographic, and financial criteria. We also use your data to:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textMuted">
              <li>Generate personalized match results and rankings.</li>
              <li>Send deadline reminder emails for tracked opportunities.</li>
              <li>Provide missing-criteria feedback to improve your eligibility.</li>
              <li>Maintain your application tracker and linked documents.</li>
              <li>Improve matching accuracy and opportunity coverage over time.</li>
            </ul>
          </section>

          {/* 3. Third-Party Sharing */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              3. Third-Party Sharing
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              EdFintia does not sell your personal information. We share data
              only with the following service providers, under their respective
              privacy policies:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textMuted">
              <li>
                <strong className="text-text">Supabase:</strong> Provides
                user authentication (including OAuth sign-in via Google and
                LinkedIn) and hosts the application database that stores your
                account, profile, and application-tracker data.
              </li>
              <li>
                <strong className="text-text">Stripe:</strong> Processes
                Premium subscription payments. Stripe receives your email and
                billing information; it does not receive your academic or
                demographic data.
              </li>
              <li>
                <strong className="text-text">Resend:</strong>{" "}
                Sends transactional and marketing emails (welcome messages,
                payment receipts, deadline digests, and account notifications)
                on our behalf, using your email address, name, and the
                content of each email. Deadline digests may alternatively be
                delivered through a configured SMTP relay.
              </li>
              <li>
                <strong className="text-text">EmailOctopus:</strong>{" "}
                Hosts our early-access/waitlist contact list and sends launch
                announcements and product updates to subscribers who opted in.
                It receives your email address, first name, and the audience
                type you select.
              </li>
              <li>
                <strong className="text-text">OpenAI:</strong>{" "}
                Powers our AI features — the Statement Coach essay outliner
                and the in-app Support Assistant. When you use them, OpenAI
                processes the scholarship details and notes you provide for
                an outline, or the messages you send the Support Assistant.
              </li>
              <li>
                <strong className="text-text">Google Analytics:</strong>{" "}
                When enabled, measures site usage (page views and anonymous
                early-access funnel events) with IP anonymization turned on.
              </li>
              <li>
                <strong className="text-text">Vercel &amp; Render:</strong>{" "}
                Host the EdFintia website and API.
              </li>
            </ul>
          </section>

          {/* 4. Marketing Communications & Opt-Outs */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              4. Marketing Communications &amp; Opt-Outs
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              EdFintia complies with the CAN-SPAM Act. We send marketing emails
              (including deadline digest notifications) only to users who have
              explicitly opted in during registration, in their profile
              settings, or on the early-access signup form. You may opt out at
              any time by:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textMuted">
              <li>Unchecking the marketing opt-in box in your profile settings.</li>
              <li>Clicking the unsubscribe link at the bottom of any marketing email.</li>
              <li>Contacting us directly to request removal from our mailing list.</li>
            </ul>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              Transactional emails (account verification, password resets,
              payment receipts) are sent regardless of marketing preferences,
              as they are necessary for the Service to function.
            </p>
          </section>

          {/* 5. Data Retention */}
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">
              5. Data Retention
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
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
            <h2 className="font-serif text-xl font-semibold text-text">
              6. Your Rights
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              Depending on your jurisdiction, you may have the following rights
              regarding your personal data:
            </p>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textMuted">
              <li><strong className="text-text">Access:</strong> Request a copy of the data we hold about you.</li>
              <li><strong className="text-text">Correction:</strong> Update inaccurate or incomplete information.</li>
              <li><strong className="text-text">Deletion:</strong> Request deletion of your account and associated data.</li>
              <li><strong className="text-text">Portability:</strong> Receive your data in a machine-readable format.</li>
              <li><strong className="text-text">Opt-Out:</strong> Unsubscribe from marketing communications at any time.</li>
            </ul>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              To exercise any of these rights, contact us at
              <a href={`mailto:${PRIVACY_EMAIL}`} className="text-primary underline"> {PRIVACY_EMAIL}</a>.
              We will respond within 30 days.
            </p>
          </section>
        </div>

        {/* Footer */}
        <footer className="mt-16 border-t border-textMuted/10 pt-6 text-center text-xs text-textMuted">
          <p>
            © 2026 EdFintia. All rights reserved.{" "}
            <Link href="/terms" className="text-primary underline">
              Terms of Service
            </Link>
          </p>
        </footer>
      </main>
    </div>
  );
}

import type { Metadata } from "next";
import Link from "next/link";
import { CRAWLER_CONTACT_EMAIL } from "@/lib/config";

export const metadata: Metadata = {
  title: "EdFintiaBot — Crawler Information",
  description: "Information for website operators about EdFintiaBot, the EdFintia web crawler.",
};

export default function CrawlerPage() {
  return (
    <div className="min-h-screen bg-surface">
      <header className="border-b border-textMuted/10 bg-white/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
          <Link
            href="/"
            className="font-serif text-lg font-semibold text-text hover:text-primary transition"
          >
            ← Home
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-12">
        <h1 className="font-serif text-3xl font-bold text-text">EdFintiaBot</h1>
        <p className="mt-2 text-sm text-textMuted">
          Information for website operators who see EdFintiaBot in their server logs.
        </p>

        <div className="mt-10 space-y-8">
          <section>
            <h2 className="font-serif text-xl font-semibold text-text">What it is</h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              EdFintiaBot is the web crawler operated by EdFintia. It identifies itself with the
              user agent:
            </p>
            <pre className="mt-3 overflow-x-auto rounded bg-white px-4 py-3 text-xs text-text">
              EdFintiaBot/1.0 (+https://edfintia.com/crawler)
            </pre>
          </section>

          <section>
            <h2 className="font-serif text-xl font-semibold text-text">Why it visits</h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              EdFintiaBot discovers and keeps current publicly available information about
              education-funding opportunities for the EdFintia funding-discovery service. This can
              include scholarships, grants, fellowships, tuition assistance, workforce education
              programs, service-based funding, and other education-related funding programs.
              EdFintia is not affiliated with the organizations whose programs it lists.
            </p>
          </section>

          <section>
            <h2 className="font-serif text-xl font-semibold text-text">How it behaves</h2>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-textMuted">
              <li>
                It checks <code>robots.txt</code> before fetching pages and follows rules addressed
                to <code>EdFintiaBot</code> or to all crawlers (<code>*</code>), including{" "}
                <code>Crawl-delay</code>.
              </li>
              <li>
                Requests are deliberately rate-limited per site, with limited concurrency, and
                retries are bounded.
              </li>
              <li>
                It does not try to bypass access controls, CAPTCHAs, logins, or explicit crawler
                restrictions, and it does not disguise itself as a regular browser.
              </li>
              <li>It only reads publicly accessible pages.</li>
            </ul>
          </section>

          <section>
            <h2 className="font-serif text-xl font-semibold text-text">Blocking or limiting it</h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              To stop EdFintiaBot from crawling your site, add the following to your{" "}
              <code>robots.txt</code>:
            </p>
            <pre className="mt-3 overflow-x-auto rounded bg-white px-4 py-3 text-xs text-text">
{`User-agent: EdFintiaBot
Disallow: /`}
            </pre>
          </section>

          <section>
            <h2 className="font-serif text-xl font-semibold text-text">Contact</h2>
            <p className="mt-3 text-sm leading-relaxed text-textMuted">
              Questions or concerns about crawler behavior on your site can be sent to
              <a href={`mailto:${CRAWLER_CONTACT_EMAIL}`} className="text-primary hover:underline">
                {" "}
                {CRAWLER_CONTACT_EMAIL}
              </a>
              .
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}

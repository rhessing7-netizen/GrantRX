"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { BrandMark } from "@/components/Brand";
import { api } from "@/lib/api";

type Status = "confirm" | "submitting" | "success" | "invalid" | "error";

function UnsubscribeCard() {
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const [status, setStatus] = useState<Status>(token ? "confirm" : "invalid");

  async function handleUnsubscribe() {
    setStatus("submitting");
    try {
      await api.unsubscribeMarketing(token);
      setStatus("success");
    } catch (err) {
      const code = (err as { status?: number }).status;
      setStatus(code === 400 || code === 422 ? "invalid" : "error");
    }
  }

  return (
    <div className="mx-auto w-full max-w-md rounded-3xl border border-border bg-surface p-8 text-center shadow-sm">
      {status === "confirm" || status === "submitting" ? (
        <>
          <h1 className="font-serif text-2xl font-bold text-text">
            Unsubscribe from marketing emails?
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-textMuted">
            You&apos;ll stop receiving EdFintia deadline digests and product
            updates. Important account emails — like receipts and security
            notices — will still be sent.
          </p>
          <button
            onClick={handleUnsubscribe}
            disabled={status === "submitting"}
            className="mt-6 w-full rounded-full bg-primary px-6 py-3 text-sm font-semibold text-surface transition hover:opacity-90 disabled:opacity-60"
          >
            {status === "submitting" ? "Unsubscribing…" : "Yes, unsubscribe me"}
          </button>
        </>
      ) : status === "success" ? (
        <>
          <h1 className="font-serif text-2xl font-bold text-text">
            You&apos;re unsubscribed
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-textMuted">
            You&apos;ve been unsubscribed from EdFintia marketing emails. You can
            turn them back on anytime in Account Settings.
          </p>
        </>
      ) : status === "invalid" ? (
        <>
          <h1 className="font-serif text-2xl font-bold text-text">
            This link doesn&apos;t work
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-textMuted">
            This unsubscribe link is invalid or has expired. You can manage
            email preferences in Account Settings, or contact support for help.
          </p>
        </>
      ) : (
        <>
          <h1 className="font-serif text-2xl font-bold text-text">
            Something went wrong
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-textMuted">
            We couldn&apos;t process your unsubscribe request right now. Please
            try again in a few minutes.
          </p>
          <button
            onClick={handleUnsubscribe}
            className="mt-6 w-full rounded-full bg-primary px-6 py-3 text-sm font-semibold text-surface transition hover:opacity-90"
          >
            Try again
          </button>
        </>
      )}
      <p className="mt-6 text-xs text-textMuted">
        <Link href="/" className="underline transition hover:text-primary">
          Back to EdFintia
        </Link>
      </p>
    </div>
  );
}

export default function UnsubscribePage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center px-6 py-4">
          <Link href="/" aria-label="EdFintia home">
            <BrandMark className="h-7 sm:h-8" />
          </Link>
        </div>
      </header>
      <main className="flex flex-1 items-center justify-center px-6 py-16">
        <Suspense
          fallback={
            <div className="text-sm text-textMuted">Loading…</div>
          }
        >
          <UnsubscribeCard />
        </Suspense>
      </main>
      <footer className="border-t border-border px-6 py-6 text-center text-xs text-textMuted">
        <p>
          © {new Date().getFullYear()} EdFintia ·{" "}
          <Link href="/privacy" className="underline transition hover:text-primary">
            Privacy
          </Link>{" "}
          ·{" "}
          <Link href="/terms" className="underline transition hover:text-primary">
            Terms
          </Link>
        </p>
      </footer>
    </div>
  );
}

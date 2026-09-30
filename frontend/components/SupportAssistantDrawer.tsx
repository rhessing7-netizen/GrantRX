"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { Session } from "@supabase/supabase-js";
import type { SupportMessage } from "@/lib/types";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";

const MAX_TURNS = 4;
const WELCOME_REPLY =
  "Hi! I'm the EdFintia Support Assistant. Ask me about search quotas, match scoring, the application tracker, linked documents, deadline calendars, or subscriptions. How can I help?";
const GUEST_WELCOME_REPLY =
  "Hi! I'm the EdFintia Support Assistant. To protect your account details and route tickets to your student profile, please sign in or create an account.";
const GUEST_SIGNIN_PROMPT = "Please sign in to continue chatting with support.";
const SUPPORT_MAILTO =
  "mailto:phuturecliciansphoundation@gmail.com?subject=%5BEdFintia%20Guest%20Inquiry%5D";
const SUPPORT_MAILTO_MEMBER =
  "mailto:phuturecliciansphoundation@gmail.com?subject=%5BEdFintia%20Support%5D";

export function SupportAssistantDrawer() {
  const [isOpen, setIsOpen] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<SupportMessage[]>([
    { role: "assistant", content: GUEST_WELCOME_REPLY },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turnCount, setTurnCount] = useState(0);
  const [turnsRemaining, setTurnsRemaining] = useState(MAX_TURNS);
  const [isEscalated, setIsEscalated] = useState(false);
  const [escalating, setEscalating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pathname = usePathname();
  const router = useRouter();
  // On the app shell (/), the MobileBottomNav is present on mobile widths.
  const appShell = pathname === "/";

  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Read the Supabase auth session and subscribe to auth state changes.
  useEffect(() => {
    if (!supabase) return;

    // Swap the placeholder welcome for the correct variant whenever the auth
    // session resolves or changes, preserving any real conversation.
    const applyWelcomeForSession = (sess: Session | null) => {
      setMessages((prev) => {
        if (!sess) {
          // Replace only the very first assistant message if it is still the
          // authenticated welcome — preserve any user/assistant conversation.
          if (prev.length === 1 && prev[0].role === "assistant" && prev[0].content === WELCOME_REPLY) {
            return [{ role: "assistant", content: GUEST_WELCOME_REPLY }];
          }
          return prev;
        }
        // Authenticated: restore the standard welcome if the only message is the guest welcome.
        if (prev.length === 1 && prev[0].role === "assistant" && prev[0].content === GUEST_WELCOME_REPLY) {
          return [{ role: "assistant", content: WELCOME_REPLY }];
        }
        return prev;
      });
    };

    supabase.auth
      .getSession()
      .then(({ data }) => {
        setSession(data.session);
        applyWelcomeForSession(data.session);
      })
      .catch(() => {
        // getSession may fail if Supabase is unreachable — treat as guest
      });
    const { data } = supabase.auth.onAuthStateChange(
      (_event, sess) => {
        setSession(sess);
        applyWelcomeForSession(sess);
      },
    );
    return () => {
      data.subscription.unsubscribe();
    };
  }, []);

  const isGuest = !session;

  // Auto-scroll to the latest message.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen]);

  const chatDisabled = isEscalated || turnCount >= MAX_TURNS || sending || isGuest;

  const handleSend = async () => {
    const text = input.trim();
    if (!text || chatDisabled) return;

    // Guest guard: never hit the backend for unauthenticated users.
    if (isGuest) {
      setMessages((prev) => [
        ...prev,
        { role: "user", content: text },
        { role: "assistant", content: GUEST_SIGNIN_PROMPT },
      ]);
      setInput("");
      openAuth();
      return;
    }

    setError(null);
    const userMsg: SupportMessage = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);
    try {
      const res = await api.supportChat(text, conversationId ?? undefined);
      setConversationId(res.conversation_id);
      setTurnCount(res.turn_count);
      setTurnsRemaining(res.turns_remaining);
      setIsEscalated(res.is_escalated);
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Something went wrong. Please try again.";
      setError(msg);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "I had trouble reaching the support service. Please try again, or use \u201cEmail Support Instead\u201d to reach our team directly.",
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  const handleEscalate = async () => {
    setError(null);
    setEscalating(true);
    try {
      const res = await api.supportEscalate(conversationId ?? undefined);
      setIsEscalated(true);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.message },
      ]);
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Escalation failed. Please try again.";
      setError(msg);
    } finally {
      setEscalating(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const openAuth = () => {
    if (appShell) {
      // page.tsx listens for this event and opens the auth modal.
      window.dispatchEvent(new CustomEvent("grantrx:auth:open"));
    } else {
      // On public pages (terms, privacy, early-access) nothing listens —
      // bounce to the app shell, which opens the modal on ?signin=1.
      router.push("/?signin=1");
    }
  };

  return (
    <>
      {/* Floating launcher button */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          aria-label="Open EdFintia Support Assistant"
          title="Support Assistant"
          className={`fixed right-6 z-40 rounded-full border border-accent/50 bg-accent/20 p-3 text-text shadow-md transition hover:bg-accent/30 lg:bottom-6 ${appShell ? "bottom-20" : "bottom-6"}`}
        >
          <svg
            className="h-6 w-6"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            viewBox="0 0 24 24"
          >
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
            <circle cx="12" cy="9.5" r="0.5" fill="currentColor" />
            <path d="M9.2 9.4c.3-.6 1-1 1.8-1 .9 0 1.6.4 1.8 1" />
          </svg>
        </button>
      )}

      {/* Slide-over drawer */}
      {isOpen && (
        <div
          className="fixed inset-0 z-50 flex justify-end bg-text/40 backdrop-blur-sm"
          onClick={() => setIsOpen(false)}
        >
          <div
            className="flex h-full w-full max-w-md flex-col bg-surface shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="EdFintia Support Assistant"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-textMuted/10 bg-surface/95 px-5 py-4 backdrop-blur">
              <div className="min-w-0">
                <h2 className="font-serif text-lg font-semibold text-text">
                  EdFintia Assistant
                </h2>
                <p className="text-xs text-textMuted">
                  {isGuest
                    ? "Guest Mode"
                    : isEscalated || turnCount >= MAX_TURNS
                      ? "Escalated to human support"
                      : `${turnsRemaining}/${MAX_TURNS} queries remaining`}
                </p>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="ml-3 shrink-0 rounded-lg p-1.5 text-textMuted hover:bg-surfaceSubtle hover:text-text"
                aria-label="Close"
              >
                <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Message feed */}
            <div
              ref={scrollRef}
              className="flex-1 space-y-3 overflow-y-auto px-5 py-4"
            >
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={
                    m.role === "user"
                      ? "flex justify-end"
                      : "flex justify-start"
                  }
                >
                  <div
                    className={
                      m.role === "user"
                        ? "max-w-[85%] rounded-2xl rounded-br-sm bg-secondary px-3.5 py-2 text-sm text-white"
                        : "max-w-[85%] rounded-2xl rounded-bl-sm border border-border bg-white px-3.5 py-2 text-sm text-text"
                    }
                  >
                    {m.content}
                  </div>
                </div>
              ))}
              {sending && (
                <div className="flex justify-start">
                  <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-border bg-white px-3.5 py-2 text-sm text-textMuted">
                    <span className="inline-flex gap-1">
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-textMuted [animation-delay:-0.3s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-textMuted [animation-delay:-0.15s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-textMuted" />
                    </span>
                  </div>
                </div>
              )}

              {/* Guest sign-in CTA card */}
              {isGuest && (
                <div className="rounded-xl border border-secondary/30 bg-secondary/5 px-4 py-4 text-sm">
                  <p className="font-semibold text-text">
                    Sign in to continue
                  </p>
                  <p className="mt-1 text-textMuted">
                    To protect your account details and route tickets to your
                    student profile, please sign in or create an account.
                  </p>
                  <button
                    onClick={openAuth}
                    className="mt-3 w-full rounded-full bg-secondary px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90"
                  >
                    Sign In / Create Account
                  </button>
                  <a
                    href={SUPPORT_MAILTO}
                    className="mt-2 block text-center text-xs font-medium text-secondary hover:underline"
                  >
                    Email Support Instead
                  </a>
                </div>
              )}

              {/* Escalation card */}
              {!isGuest && (isEscalated || turnCount >= MAX_TURNS) && (
                <div className="rounded-xl border border-accentSoft/40 bg-accentSoft/10 px-4 py-3 text-sm text-text">
                  <p className="font-semibold text-secondary">
                    You&rsquo;ve reached the automated assistant limit.
                  </p>
                  <p className="mt-1 text-textMuted">
                    A support ticket and email transcript have been sent to our
                    support team. We&rsquo;ll follow up with you shortly.
                  </p>
                </div>
              )}

              {error && (
                <p className="text-xs text-warning">{error}</p>
              )}
            </div>

            {/* Input + actions */}
            <div className="border-t border-textMuted/10 bg-surface/95 px-5 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur">
              {isGuest ? (
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs text-textMuted">
                    Sign in to chat with the assistant.
                  </p>
                  <button
                    onClick={openAuth}
                    className="rounded-full bg-secondary px-4 py-2 text-xs font-semibold text-white transition hover:opacity-90"
                  >
                    Sign In / Create Account
                  </button>
                </div>
              ) : chatDisabled ? (
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs text-textMuted">
                    Chat disabled — conversation escalated.
                  </p>
                  {isEscalated ? (
                    <a
                      href={SUPPORT_MAILTO_MEMBER}
                      className="rounded-full bg-gradient-to-r from-accentSoft to-accent px-4 py-2 text-xs font-semibold text-text transition hover:opacity-90"
                    >
                      Email Support Team
                    </a>
                  ) : (
                    <button
                      onClick={handleEscalate}
                      disabled={escalating}
                      className="rounded-full bg-gradient-to-r from-accentSoft to-accent px-4 py-2 text-xs font-semibold text-text transition hover:opacity-90 disabled:opacity-50"
                    >
                      {escalating ? "Sending\u2026" : "Email Support Instead"}
                    </button>
                  )}
                </div>
              ) : (
                <>
                  <div className="flex items-end gap-2">
                    <textarea
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={1}
                      placeholder="Ask about quotas, scoring, tracking..."
                      className="max-h-32 flex-1 resize-none rounded-xl border border-textMuted/20 bg-white px-3 py-2 text-sm text-text placeholder:text-textMuted/60 focus:border-secondary focus:outline-none focus:ring-1 focus:ring-secondary"
                    />
                    <button
                      onClick={handleSend}
                      disabled={!input.trim() || sending}
                      className="shrink-0 rounded-full bg-secondary px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                    >
                      Send
                    </button>
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <p className="text-[11px] text-textMuted">
                      {turnsRemaining} of {MAX_TURNS} queries left
                    </p>
                    <button
                      onClick={handleEscalate}
                      disabled={escalating}
                      className="text-[11px] font-medium text-secondary hover:underline disabled:opacity-50"
                    >
                      Email Support Instead
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import type { SupportMessage } from "@/lib/types";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";

const MAX_TURNS = 4;
const WELCOME_REPLY =
  "Hi! I'm the GrantRx Support Assistant. Ask me about search quotas, match scoring, the Kanban board, document vault, deadline calendars, or subscriptions. How can I help?";
const GUEST_WELCOME_REPLY =
  "Hi! I'm the GrantRx Support Assistant. To protect your account details and route tickets to your student profile, please sign in or create an account.";
const GUEST_SIGNIN_PROMPT = "Please sign in to continue chatting with support.";
const SUPPORT_MAILTO =
  "mailto:phuturecliciansphoundation@gmail.com?subject=%5BGrantRx%20Guest%20Inquiry%5D";

export function SupportAssistantDrawer() {
  const [isOpen, setIsOpen] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<SupportMessage[]>([
    { role: "assistant", content: WELCOME_REPLY },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turnCount, setTurnCount] = useState(0);
  const [turnsRemaining, setTurnsRemaining] = useState(MAX_TURNS);
  const [isEscalated, setIsEscalated] = useState(false);
  const [escalating, setEscalating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Read the Supabase auth session and subscribe to auth state changes.
  useEffect(() => {
    if (!supabase) return;
    supabase.auth
      .getSession()
      .then(({ data }) => setSession(data.session))
      .catch(() => {
        // getSession may fail if Supabase is unreachable — treat as guest
      });
    const { data } = supabase.auth.onAuthStateChange(
      (_event, sess) => {
        setSession(sess);
      },
    );
    return () => {
      data.subscription.unsubscribe();
    };
  }, []);

  const isGuest = !session;

  // When the auth state changes, swap the initial welcome message so guests
  // see the sign-in prompt instead of the authenticated welcome.
  useEffect(() => {
    setMessages((prev) => {
      if (isGuest) {
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
  }, [isGuest]);

  // Auto-scroll to the latest message.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, isOpen]);

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
      window.dispatchEvent(new CustomEvent("grantrx:auth:open"));
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
    window.dispatchEvent(new CustomEvent("grantrx:auth:open"));
  };

  return (
    <>
      {/* Floating launcher button */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          aria-label="Open GrantRx Support Assistant"
          title="Support Assistant"
          className="fixed bottom-6 right-6 z-40 rounded-full border border-skyAqua/50 bg-skyAqua/20 p-3 text-slate-800 shadow-md transition hover:bg-skyAqua/30"
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
          className="fixed inset-0 z-50 flex justify-end bg-textPrimary/40 backdrop-blur-sm"
          onClick={() => setIsOpen(false)}
        >
          <div
            className="flex h-full w-full max-w-md flex-col bg-surfaceBg shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="GrantRx Support Assistant"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-textSecondary/10 bg-surfaceBg/95 px-5 py-4 backdrop-blur">
              <div className="min-w-0">
                <h2 className="font-serif text-lg font-semibold text-textPrimary">
                  GrantRx Assistant
                </h2>
                <p className="text-xs text-textSecondary">
                  {isGuest
                    ? "Guest Mode"
                    : isEscalated || turnCount >= MAX_TURNS
                      ? "Escalated to human support"
                      : `${turnsRemaining}/${MAX_TURNS} queries remaining`}
                </p>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="ml-3 shrink-0 rounded-lg p-1.5 text-textSecondary hover:bg-slate-100 hover:text-textPrimary"
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
                        ? "max-w-[85%] rounded-2xl rounded-br-sm bg-blueEnergy px-3.5 py-2 text-sm text-white"
                        : "max-w-[85%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3.5 py-2 text-sm text-textPrimary"
                    }
                  >
                    {m.content}
                  </div>
                </div>
              ))}
              {sending && (
                <div className="flex justify-start">
                  <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3.5 py-2 text-sm text-textSecondary">
                    <span className="inline-flex gap-1">
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
                    </span>
                  </div>
                </div>
              )}

              {/* Guest sign-in CTA card */}
              {isGuest && (
                <div className="rounded-xl border border-blueEnergy/30 bg-blueEnergy/5 px-4 py-4 text-sm">
                  <p className="font-semibold text-textPrimary">
                    Sign in to continue
                  </p>
                  <p className="mt-1 text-textSecondary">
                    To protect your account details and route tickets to your
                    student profile, please sign in or create an account.
                  </p>
                  <button
                    onClick={openAuth}
                    className="mt-3 w-full rounded-full bg-blueEnergy px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90"
                  >
                    Sign In / Create Account
                  </button>
                  <a
                    href={SUPPORT_MAILTO}
                    className="mt-2 block text-center text-xs font-medium text-blueEnergy hover:underline"
                  >
                    Email Support Instead
                  </a>
                </div>
              )}

              {/* Escalation card */}
              {!isGuest && (isEscalated || turnCount >= MAX_TURNS) && (
                <div className="rounded-xl border border-aquamarine/40 bg-aquamarine/10 px-4 py-3 text-sm text-textPrimary">
                  <p className="font-semibold text-blueEnergy">
                    You&rsquo;ve reached the automated assistant limit.
                  </p>
                  <p className="mt-1 text-textSecondary">
                    A support ticket and email transcript have been sent to our
                    support team. We&rsquo;ll follow up with you shortly.
                  </p>
                </div>
              )}

              {error && (
                <p className="text-xs text-amber-700">{error}</p>
              )}
            </div>

            {/* Input + actions */}
            <div className="border-t border-textSecondary/10 bg-surfaceBg/95 px-5 py-3 backdrop-blur">
              {isGuest ? (
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs text-textSecondary">
                    Sign in to chat with the assistant.
                  </p>
                  <button
                    onClick={openAuth}
                    className="rounded-full bg-blueEnergy px-4 py-2 text-xs font-semibold text-white transition hover:opacity-90"
                  >
                    Sign In / Create Account
                  </button>
                </div>
              ) : chatDisabled ? (
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs text-textSecondary">
                    Chat disabled — conversation escalated.
                  </p>
                  <button
                    onClick={handleEscalate}
                    disabled={escalating}
                    className="rounded-full bg-gradient-to-r from-aquamarine to-neonIce px-4 py-2 text-xs font-semibold text-textPrimary transition hover:opacity-90 disabled:opacity-50"
                  >
                    {escalating ? "Sending\u2026" : "Email Support Instead"}
                  </button>
                </div>
              ) : (
                <>
                  <div className="flex items-end gap-2">
                    <textarea
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={1}
                      placeholder="Ask about quotas, scoring, Kanban..."
                      className="max-h-32 flex-1 resize-none rounded-xl border border-textSecondary/20 bg-white px-3 py-2 text-sm text-textPrimary placeholder:text-textSecondary/60 focus:border-blueEnergy focus:outline-none focus:ring-1 focus:ring-blueEnergy"
                    />
                    <button
                      onClick={handleSend}
                      disabled={!input.trim() || sending}
                      className="shrink-0 rounded-full bg-blueEnergy px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                    >
                      Send
                    </button>
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <p className="text-[11px] text-textSecondary">
                      {turnsRemaining} of {MAX_TURNS} queries left
                    </p>
                    <button
                      onClick={handleEscalate}
                      disabled={escalating}
                      className="text-[11px] font-medium text-blueEnergy hover:underline disabled:opacity-50"
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

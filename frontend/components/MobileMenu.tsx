"use client";

import { useEffect, type ReactNode } from "react";

export type MobileMenuProps = {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
};

export function MobileMenu({ open, onClose, children }: MobileMenuProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div
        className="absolute inset-0 bg-text/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="absolute left-0 top-0 h-full w-[85%] max-w-sm bg-surface shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label="Menu"
      >
        <div className="flex h-full flex-col pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="font-serif text-base font-semibold text-text">Menu</span>
            <button
              onClick={onClose}
              className="flex h-11 w-11 items-center justify-center rounded-xl text-text transition hover:bg-surfaceSubtle"
              aria-label="Close menu"
            >
              <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-4">{children}</div>
        </div>
      </div>
    </div>
  );
}

"use client";

import type { ReactNode } from "react";

export type MobileTab = "discover" | "kanban" | "calendar";

export type MobileBottomNavProps = {
  activeTab: MobileTab | null;
  onTabChange: (tab: MobileTab) => void;
  onOpenMenu: () => void;
};

const TABS: { id: MobileTab; label: string; icon: ReactNode }[] = [
  {
    id: "discover",
    label: "Discover",
    icon: (
      <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    ),
  },
  {
    id: "kanban",
    label: "Applications",
    icon: (
      <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
      </svg>
    ),
  },
  {
    id: "calendar",
    label: "Calendar",
    icon: (
      <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
    ),
  },
];

export function MobileBottomNav({ activeTab, onTabChange, onOpenMenu }: MobileBottomNavProps) {
  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-40 border-t border-border bg-surface/90 px-2 pt-2 backdrop-blur-md lg:hidden"
      aria-label="Primary"
      style={{ paddingBottom: "max(0.5rem, env(safe-area-inset-bottom))" }}
    >
      <div className="mx-auto flex h-16 max-w-md items-center justify-around">
        {TABS.map((tab) => {
          const active = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`flex min-w-[64px] flex-col items-center justify-center gap-1 rounded-xl px-3 py-2 transition ${
                active
                  ? "bg-primary/10 text-primary"
                  : "text-textMuted hover:bg-surfaceSubtle hover:text-text"
              }`}
              aria-current={active ? "page" : undefined}
              aria-label={tab.label}
            >
              {tab.icon}
              <span className="text-[11px] font-medium">{tab.label}</span>
            </button>
          );
        })}
        <button
          onClick={onOpenMenu}
          className="flex min-w-[64px] flex-col items-center justify-center gap-1 rounded-xl px-3 py-2 text-textMuted transition hover:bg-surfaceSubtle hover:text-text"
          aria-label="More menu"
        >
          <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0z" />
          </svg>
          <span className="text-[11px] font-medium">More</span>
        </button>
      </div>
    </nav>
  );
}

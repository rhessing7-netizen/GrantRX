"use client";

import Link from "next/link";
import { BrandMark } from "@/components/Brand";

export type MobileHeaderProps = {
  onOpenMenu: () => void;
  onOpenAccount?: () => void;
};

export function MobileHeader({ onOpenMenu, onOpenAccount }: MobileHeaderProps) {
  return (
    <header className="sticky top-0 z-40 flex items-center justify-between border-b border-border bg-surface/90 px-4 py-3 backdrop-blur-md lg:hidden">
      <button
        onClick={onOpenMenu}
        className="flex h-11 w-11 items-center justify-center rounded-xl text-text transition hover:bg-surfaceSubtle"
        aria-label="Open menu"
      >
        <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      <Link href="/" className="absolute left-1/2 -translate-x-1/2">
        <BrandMark size="sm" className="h-7" alt="EdFintia" />
      </Link>

      {onOpenAccount && (
        <button
          onClick={onOpenAccount}
          className="flex h-11 w-11 items-center justify-center rounded-xl text-text transition hover:bg-surfaceSubtle"
          aria-label="Account"
        >
          <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
        </button>
      )}
    </header>
  );
}

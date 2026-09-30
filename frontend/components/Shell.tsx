import type { ReactNode } from "react";

export type ShellProps = {
  left: ReactNode;
  right: ReactNode;
};

export function Shell({ left, right }: ShellProps) {
  return (
    <div className="relative min-h-[100dvh] lg:h-[100dvh] overflow-x-clip lg:overflow-hidden flex flex-col lg:flex-row bg-gradient-to-br from-background via-surfaceSubtle to-accentSoft/20">
      {/* Atmospheric radial glow accent */}
      <div className="pointer-events-none absolute -top-32 -right-32 h-96 w-96 rounded-full bg-accent/15 blur-3xl" />
      <div className="pointer-events-none absolute top-1/2 -left-32 h-80 w-80 rounded-full bg-accentSoft/15 blur-3xl" />

      <aside className="relative hidden w-full lg:block lg:w-[35%] lg:sticky lg:top-0 lg:h-[100dvh] lg:overflow-y-auto bg-surface/70 backdrop-blur-xl border-b lg:border-b-0 lg:border-r border-border p-6">
        {left}
      </aside>
      <main className="relative w-full lg:w-[65%] lg:h-[100dvh] lg:overflow-y-auto p-6 pb-[calc(1.5rem+4rem+env(safe-area-inset-bottom))] lg:pb-6">
        {right}
      </main>
    </div>
  );
}

import type { ReactNode } from "react";

export type ShellProps = {
  left: ReactNode;
  right: ReactNode;
};

export function Shell({ left, right }: ShellProps) {
  return (
    <div className="relative min-h-screen lg:h-screen lg:overflow-hidden flex flex-col lg:flex-row bg-gradient-to-br from-[#F8FAFC] via-[#F1F5F9] to-[#E2E8F0]/40">
      {/* Atmospheric radial glow accent */}
      <div className="pointer-events-none absolute -top-32 -right-32 h-96 w-96 rounded-full bg-skyAqua/10 blur-3xl" />
      <div className="pointer-events-none absolute top-1/2 -left-32 h-80 w-80 rounded-full bg-aquamarine/5 blur-3xl" />

      <aside className="relative w-full lg:w-[35%] lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto bg-white/60 backdrop-blur-xl border-b lg:border-b-0 lg:border-r border-slate-200/60 p-6">
        {left}
      </aside>
      <main className="relative w-full lg:w-[65%] lg:h-screen lg:overflow-y-auto p-6">
        {right}
      </main>
    </div>
  );
}

import type { ReactNode } from "react";

export type ShellProps = {
  left: ReactNode;
  right: ReactNode;
};

export function Shell({ left, right }: ShellProps) {
  return (
    <div className="min-h-screen lg:h-screen lg:overflow-hidden flex flex-col lg:flex-row bg-surfaceBg">
      <aside className="w-full lg:w-[35%] lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto bg-cardBg border-b lg:border-b-0 lg:border-r border-textSecondary/10 p-6">
        {left}
      </aside>
      <main className="w-full lg:w-[65%] lg:h-screen lg:overflow-y-auto p-6">
        {right}
      </main>
    </div>
  );
}

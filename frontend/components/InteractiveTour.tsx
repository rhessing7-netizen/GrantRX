"use client";

import { useEffect, useRef, useState } from "react";
import { driver, type Driver } from "driver.js";
import "driver.js/dist/driver.css";
import { api } from "@/lib/api";
import type { Profile } from "@/lib/types";

type Tab = "discover" | "kanban" | "calendar" | "planner";

export type InteractiveTourProps = {
  /** True when the discovery feed has loaded and the tour is eligible. */
  shouldStart: boolean;
  /** Current active tab — used to know when kanban is visible. */
  tab: Tab;
  /** Switch the main tab (used by Step 3 to jump to My Applications). */
  onSwitchTab: (tab: Tab) => void;
  /** Authenticated user profile. The tour never auto-starts for guests. */
  profile: Profile | null;
};

const TOUR_KEY = "grantrx_tour_completed";
const SAVE_EVENT = "grantrx:tour:save-fired";
const KANBAN_ACTION_EVENT = "grantrx:tour:kanban-action-fired";
const START_EVENT = "grantrx:tour:start";

/** CSS overrides for the driver.js popover using the EdFintia palette. */
const TOUR_STYLES = `
.driver-popover {
  --driver-popover-color: #23203B;
  --driver-popover-bg: #ffffff;
  --driver-popover-border: #E4E0F0;
  font-family: var(--font-inter), 'Inter', sans-serif;
  border-radius: 16px;
  box-shadow: 0 12px 40px -8px rgba(87,74,226,0.25);
}
.driver-popover-title {
  font-family: var(--font-fraunces), 'Fraunces', serif;
  color: #23203B;
  font-weight: 700;
  font-size: 15px;
}
.driver-popover-description {
  color: #5C577A;
  font-size: 14px;
  line-height: 1.55;
}
.driver-popover-progress-btn {
  background: #E2ADF2;
  color: #222A68;
  font-weight: 600;
  border-radius: 6px;
  padding: 2px 8px;
}
.driver-popover-next-btn,
.driver-popover-done-btn {
  background: #574AE2;
  color: #ffffff;
  border-radius: 12px;
  font-weight: 600;
  padding: 8px 18px;
  border: none;
  text-shadow: none;
  transition: background 0.15s ease;
}
.driver-popover-next-btn:hover,
.driver-popover-done-btn:hover {
  background: #4438C8;
}
.driver-popover-prev-btn {
  color: #5C577A;
  border: 1px solid #E4E0F0;
  border-radius: 12px;
  padding: 8px 14px;
  text-shadow: none;
}
.driver-popover-close-btn {
  color: #9A95B5;
}
.tour-skip-btn {
  background: none;
  border: none;
  color: #9A95B5;
  font-size: 12px;
  text-decoration: underline;
  cursor: pointer;
  padding: 8px 4px;
  font-family: var(--font-inter), 'Inter', sans-serif;
}
.tour-skip-btn:hover {
  color: #5C577A;
}
.driver-popover-arrow-side-bottom.driver-popover-arrow {
  border-bottom-color: #ffffff;
}
.driver-popover-arrow-side-top.driver-popover-arrow {
  border-top-color: #ffffff;
}
.driver-popover-arrow-side-left.driver-popover-arrow {
  border-left-color: #ffffff;
}
.driver-popover-arrow-side-right.driver-popover-arrow {
  border-right-color: #ffffff;
}
`;

/** Resolve a tour target only when it is actually rendered. A hidden or
 *  absent element (e.g. the desktop-only kanban tab on a phone) degrades
 *  to driver.js's centered modal popover instead of a mispositioned
 *  tooltip anchored to a zero-size rect. */
const visibleTourEl = (selector: string) => () => {
  const el = document.querySelector<HTMLElement>(selector);
  return el && el.getClientRects().length > 0
    ? el
    : (undefined as unknown as Element);
};

function persistCompletion() {
  try {
    localStorage.setItem(TOUR_KEY, "true");
  } catch {
    // localStorage may be unavailable — ignore
  }
  // Best-effort PATCH — never block on failure
  api.updateProfile({ has_completed_tour: true }).catch(() => {
    // Silent — the localStorage flag is the primary gate
  });
}

export function InteractiveTour({ shouldStart, tab, onSwitchTab, profile }: InteractiveTourProps) {
  const driverRef = useRef<Driver | null>(null);
  const [active, setActive] = useState(false);
  const saveListenerRef = useRef<((e: Event) => void) | null>(null);
  const kanbanListenerRef = useRef<((e: Event) => void) | null>(null);
  const tabRef = useRef(tab);
  // Element focused before the tour opened — focus is returned here on close.
  const prevFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    tabRef.current = tab;
  }, [tab]);

  const cleanupListeners = () => {
    if (saveListenerRef.current) {
      window.removeEventListener(SAVE_EVENT, saveListenerRef.current);
      saveListenerRef.current = null;
    }
    if (kanbanListenerRef.current) {
      window.removeEventListener(KANBAN_ACTION_EVENT, kanbanListenerRef.current);
      kanbanListenerRef.current = null;
    }
  };

  const startTour = (manual = false) => {
    if (driverRef.current?.isActive()) return;
    // Auto-start only gates: the completion flag prevents unsolicited
    // replays, and the viewport guard keeps auto-start desktop-only. A
    // deliberate manual launch bypasses both — the tour must work
    // wherever the user asks for it (hidden targets degrade to centered
    // modal popovers via visibleTourEl).
    if (!manual && typeof window !== "undefined" && localStorage.getItem(TOUR_KEY) === "true") return;
    if (!manual && typeof window !== "undefined" && window.innerWidth < 1024) return;

    const driverObj = driver({
      showProgress: true,
      progressText: "Step {{current}} of {{total}}",
      allowClose: true,
      // Keyboard control is on by default — explicit for clarity. Escape
      // closes (via allowClose); arrow keys navigate between steps.
      allowKeyboardControl: true,
      prevBtnText: "Back",
      smoothScroll: true,
      overlayColor: "#0F172A",
      overlayOpacity: 0.45,
      onDestroyed: () => {
        cleanupListeners();
        driverRef.current = null;
        setActive(false);
        // Return focus to whatever launched the tour when possible.
        prevFocusRef.current?.focus?.();
        prevFocusRef.current = null;
      },
      onHighlighted: (_el, _step, opts) => {
        const idx = opts.index ?? 0;
        cleanupListeners();

        if (idx === 1) {
          // Step 2 — interactive save. A successful save auto-advances
          // exactly one step; manual navigation remains fully available.
          const handler = () => {
            driverObj.moveNext();
          };
          saveListenerRef.current = handler;
          window.addEventListener(SAVE_EVENT, handler);
        } else if (idx === 3) {
          // Step 4 — interactive kanban action. Listen for apply/vault.
          const handler = () => {
            driverObj.moveNext();
          };
          kanbanListenerRef.current = handler;
          window.addEventListener(KANBAN_ACTION_EVENT, handler);
        }
      },
      onDeselected: () => {
        cleanupListeners();
      },
      onPopoverRender: (popover) => {
        // Dialog semantics + a "Skip tour" affordance on every step —
        // driver.js only renders next/previous/close buttons natively.
        popover.wrapper.setAttribute("role", "dialog");
        popover.wrapper.setAttribute("aria-modal", "true");
        if (!popover.footerButtons.querySelector(".tour-skip-btn")) {
          const skip = document.createElement("button");
          skip.type = "button";
          skip.className = "tour-skip-btn";
          skip.textContent = "Skip tour";
          skip.setAttribute("aria-label", "Skip the product tour");
          skip.addEventListener("click", () => {
            persistCompletion();
            driverObj.destroy();
          });
          popover.footerButtons.appendChild(skip);
        }
        // Move focus into the popover so keyboard users land in the tour.
        const primary = popover.nextButton.offsetParent
          ? popover.nextButton
          : popover.closeButton;
        primary?.focus();
      },
      onNextClick: (_el, _step, opts) => {
        const idx = opts.index ?? 0;
        if (idx === 2) {
          // Step 3 → switch to Kanban tab, wait for render, then advance.
          onSwitchTab("kanban");
          setTimeout(() => driverObj.moveNext(), 600);
          return;
        }
        driverObj.moveNext();
      },
      onPrevClick: (_el, _step, opts) => {
        const idx = opts.index ?? 0;
        if (idx === 2) {
          // Back from Step 3 → return to Discover so Step 2's save-button
          // target exists again. Back never reverses product actions.
          onSwitchTab("discover");
          setTimeout(() => driverObj.movePrevious(), 600);
          return;
        }
        driverObj.movePrevious();
      },
      onDoneClick: () => {
        persistCompletion();
        driverObj.destroy();
      },
      onCloseClick: () => {
        // Skipping the tour also persists completion so it doesn't reappear.
        persistCompletion();
        driverObj.destroy();
      },
      steps: [
        // Step 1 — Discovery feed match card. Next / Skip Tour / X.
        {
          element: visibleTourEl('[data-tour="match-card"]'),
          popover: {
            title: "Your Matched Opportunities",
            description:
              "Here are your scored funding matches based on your discipline, GPA, and residency.",
            nextBtnText: "Next →",
          },
        },
        // Step 2 — Save to My Applications. A successful save auto-advances
        // one step; Back/Next/Skip/X always provide a way out.
        {
          element: visibleTourEl('[data-tour="save-btn"]'),
          disableActiveInteraction: false,
          popover: {
            title: "Save to Your Pipeline",
            description:
              "Click 'Save to My Applications' to add this award to your personal application tracker — or press Next to keep going.",
            nextBtnText: "Next →",
            showButtons: ["previous", "next", "close"],
          },
        },
        // Step 3 — Navigate to Kanban tab. Back / Next / Skip / X.
        {
          element: visibleTourEl('[data-tour="kanban-tab"]'),
          popover: {
            title: "Your Application Pipeline",
            description:
              "Nice! Your application is now in your pipeline. Let's look at your board.",
            nextBtnText: "View My Applications →",
            showButtons: ["previous", "next", "close"],
          },
        },
        // Step 4 — Apply / AI outline. Action auto-advances; manual nav too.
        {
          element: visibleTourEl('[data-tour="kanban-actions"]'),
          disableActiveInteraction: false,
          popover: {
            title: "Apply or Draft with AI",
            description:
              "When you're ready, click 'Apply' to open the provider portal, or open 'Details' to draft a 4-part outline with the AI Statement Coach — or press Next to keep going.",
            nextBtnText: "Next →",
            showButtons: ["previous", "next", "close"],
          },
        },
        // Step 5 — Profile strength + finish. Back / Finish / X.
        {
          element: visibleTourEl('[data-tour="profile-strength"]'),
          popover: {
            title: "You're All Set!",
            description:
              "Track deadlines and manage your keyword searches here — free accounts get 3 searches every 7 days.",
            doneBtnText: "Finish Tour",
            showButtons: ["previous", "next", "close"],
          },
        },
      ],
    });

    prevFocusRef.current = document.activeElement as HTMLElement | null;
    driverRef.current = driverObj;
    setActive(true);
    driverObj.drive();
  };

  // Auto-start 600ms after the feed loads — ONLY for authenticated users who
  // have not yet completed the tour. Guests never trigger the auto-tour.
  useEffect(() => {
    if (!shouldStart) return;
    // Strict profile guard: require an authenticated profile with an ID.
    if (!profile || !profile.id) return;
    if (profile.has_completed_tour) return;
    if (typeof window !== "undefined" && localStorage.getItem(TOUR_KEY) === "true") return;
    const timer = setTimeout(() => {
      // Verify the first target element exists before starting.
      if (document.querySelector('[data-tour="match-card"]')) {
        startTour();
      }
    }, 600);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shouldStart, profile]);

  // Listen for manual restart requests (from the LeftPanel button).
  useEffect(() => {
    const handleStart = () => {
      // Clear the completion flag so the tour can run again.
      try {
        localStorage.removeItem(TOUR_KEY);
      } catch {
        // ignore
      }
      // If we're not on the discover tab, switch back so step 1's element exists.
      if (tabRef.current !== "discover") {
        onSwitchTab("discover");
        setTimeout(() => startTour(true), 600);
      } else {
        startTour(true);
      }
    };
    window.addEventListener(START_EVENT, handleStart);
    return () => window.removeEventListener(START_EVENT, handleStart);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanupListeners();
      driverRef.current?.destroy();
    };
  }, []);

  return (
    <>
      {active && <style dangerouslySetInnerHTML={{ __html: TOUR_STYLES }} />}
    </>
  );
}

/** Dispatch a custom event to notify the tour that a save action fired. */
export function notifyTourSave() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(SAVE_EVENT));
  }
}

/** Dispatch a custom event to notify the tour that a kanban apply/vault fired. */
export function notifyTourKanbanAction() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(KANBAN_ACTION_EVENT));
  }
}

/** Dispatch a custom event to (re)start the tour from the LeftPanel button. */
export function startProductTour() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(START_EVENT));
  }
}

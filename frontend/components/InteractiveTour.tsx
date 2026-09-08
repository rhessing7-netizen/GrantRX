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

/** CSS overrides for the driver.js popover using the Breeze palette. */
const TOUR_STYLES = `
.driver-popover {
  --driver-popover-color: #0f172a;
  --driver-popover-bg: #ffffff;
  --driver-popover-border: #e2e8f0;
  font-family: var(--font-sora), 'Sora', sans-serif;
  border-radius: 16px;
  box-shadow: 0 12px 40px -8px rgba(74,143,231,0.25);
}
.driver-popover-title {
  font-family: var(--font-sora), 'Sora', sans-serif;
  color: #0f172a;
  font-weight: 700;
  font-size: 15px;
}
.driver-popover-description {
  color: #334155;
  font-size: 14px;
  line-height: 1.55;
}
.driver-popover-progress-btn {
  background: #73FBD3;
  color: #0f172a;
  font-weight: 600;
  border-radius: 6px;
  padding: 2px 8px;
}
.driver-popover-next-btn,
.driver-popover-done-btn {
  background: #4A8FE7;
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
  background: #3b74c4;
}
.driver-popover-prev-btn {
  color: #475569;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 8px 14px;
  text-shadow: none;
}
.driver-popover-close-btn {
  color: #94a3b8;
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

  const startTour = () => {
    if (driverRef.current?.isActive()) return;
    if (typeof window !== "undefined" && localStorage.getItem(TOUR_KEY) === "true") return;

    const driverObj = driver({
      showProgress: true,
      progressText: "Step {{current}} of {{total}}",
      allowClose: true,
      smoothScroll: true,
      overlayColor: "#0F172A",
      overlayOpacity: 0.45,
      onDestroyed: () => {
        cleanupListeners();
        driverRef.current = null;
        setActive(false);
      },
      onHighlighted: (_el, _step, opts) => {
        const idx = opts.index ?? 0;
        cleanupListeners();

        if (idx === 1) {
          // Step 2 — interactive save. Hide Next, listen for save action.
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
        // Step 1 — Discovery feed match card
        {
          element: '[data-tour="match-card"]',
          popover: {
            title: "Your Matched Scholarships",
            description:
              "Here are your scored clinical matches based on your discipline, GPA, and residency.",
            nextBtnText: "Next \u2192",
          },
        },
        // Step 2 — Interactive: Save to Kanban (no Next button)
        {
          element: '[data-tour="save-btn"]',
          disableActiveInteraction: false,
          popover: {
            title: "Save to Your Pipeline",
            description:
              "Click 'Save to Kanban' to add this award to your personal application tracker.",
            showButtons: ["close"],
          },
        },
        // Step 3 — Navigate to Kanban tab
        {
          element: '[data-tour="kanban-tab"]',
          popover: {
            title: "Your Application Pipeline",
            description:
              "Nice! Your application is now in your pipeline. Let's look at your board.",
            nextBtnText: "View My Applications \u2192",
          },
        },
        // Step 4 — Interactive: Apply or Vault (no Next button)
        {
          element: '[data-tour="kanban-actions"]',
          disableActiveInteraction: false,
          popover: {
            title: "Apply or Draft with AI",
            description:
              "When you're ready, click 'Apply' to open the provider portal, or open 'Vault' to draft a 4-part outline with the AI Statement Coach.",
            showButtons: ["close"],
          },
        },
        // Step 5 — Profile strength + finish
        {
          element: '[data-tour="profile-strength"]',
          popover: {
            title: "You're All Set!",
            description:
              "Track deadlines, monitor your weekly search quota, and unlock state grants here.",
            doneBtnText: "Finish Tour",
            showButtons: ["close"],
          },
        },
      ],
    });

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
        setTimeout(() => startTour(), 600);
      } else {
        startTour();
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

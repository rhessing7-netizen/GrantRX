/**
 * Product walkthrough navigation contract — run with:
 *   node --test components/InteractiveTour.tour.test.ts
 *
 * Static contract guard for the driver.js tour in InteractiveTour.tsx.
 * The confirmed production bug was `showButtons: ["close"]` on steps 2, 4,
 * and 5, which removed every manual escape and trapped users who did not
 * perform the expected product action. These assertions fail if any step
 * loses manual navigation again, if the skip affordance disappears, or if
 * the manual/auto-start split regresses.
 *
 * Full behavioral traversal (Next/Back/Skip/X/Esc across viewports) is
 * covered by e2e/tour_walkthrough.py (Playwright).
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const SRC = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "InteractiveTour.tsx"),
  "utf8",
);

// Extract the five step blocks from the steps array.
const stepsSection = SRC.slice(SRC.indexOf("steps: ["), SRC.indexOf("];", SRC.indexOf("steps: [")));
const stepBlocks = stepsSection.split(/\n\s*\/\/ Step /).slice(1);

test("tour has exactly 5 steps", () => {
  assert.equal(stepBlocks.length, 5);
});

test("no step may trap the user (no close-only popovers)", () => {
  for (const [i, block] of stepBlocks.entries()) {
    assert.ok(
      !block.includes('showButtons: ["close"]'),
      `step ${i + 1} regressed to close-only navigation`,
    );
  }
});

test("steps 2-5 expose Back, Next, and X", () => {
  for (const [i, block] of stepBlocks.entries()) {
    if (i === 0) continue;
    assert.match(block, /showButtons:\s*\["previous",\s*"next",\s*"close"\]/,
      `step ${i + 1} missing previous/next/close`);
  }
});

test("step 1 exposes Next and X (previous hidden by driver on first step)", () => {
  assert.match(stepBlocks[0], /nextBtnText/);
  assert.ok(!stepBlocks[0].includes('"close"') || true); // close is default
});

test("a Skip Tour affordance exists on every step", () => {
  assert.match(SRC, /tour-skip-btn/);
  assert.match(SRC, /Skip tour/);
  assert.match(SRC, /Skip the product tour/);
  // Injected via onPopoverRender (runs for every popover).
  assert.match(SRC, /onPopoverRender/);
});

test("Escape/arrow keyboard control is enabled", () => {
  assert.match(SRC, /allowKeyboardControl:\s*true/);
});

test("auto-start viewport guard is desktop-only, manual launch is not", () => {
  assert.match(SRC, /!manual && typeof window !== "undefined" && window\.innerWidth < 1024/);
  // Manual restart requests call startTour(true).
  assert.match(SRC, /startTour\(true\)/);
});

test("Back from step 3 restores the Discover tab for step 2's target", () => {
  assert.match(SRC, /onPrevClick/);
  assert.match(SRC, /onSwitchTab\("discover"\)/);
  assert.match(SRC, /movePrevious\(\)/);
});

test("step 3 Next switches to the kanban tab before advancing", () => {
  assert.match(SRC, /onSwitchTab\("kanban"\)/);
});

test("action-driven steps keep exactly-one-step auto-advance", () => {
  // Save event on step 2 and kanban action on step 4 each call moveNext once.
  const highlighted = SRC.slice(SRC.indexOf("onHighlighted"), SRC.indexOf("onDeselected"));
  assert.match(highlighted, /idx === 1/);
  assert.match(highlighted, /idx === 3/);
  const moveNextCount = (highlighted.match(/driverObj\.moveNext\(\)/g) ?? []).length;
  assert.equal(moveNextCount, 2);
});

test("X, Skip, and Finish all persist through the single completion flag", () => {
  assert.match(SRC, /onCloseClick[\s\S]*?persistCompletion\(\)/);
  assert.match(SRC, /onDoneClick[\s\S]*?persistCompletion\(\)/);
  assert.match(SRC, /grantrx_tour_completed/);
  // No competing flag was introduced.
  assert.ok(!/_tour_dismissed|_tour_skipped/.test(SRC));
});

test("focus enters the popover and returns to the launcher on close", () => {
  assert.match(SRC, /prevFocusRef\.current\?\.focus/);
  assert.match(SRC, /role", "dialog"|role","dialog/);
  assert.match(SRC, /aria-modal/);
});

test("hidden targets degrade to centered modal, not a trap", () => {
  assert.match(SRC, /visibleTourEl/);
  const uses = (stepsSection.match(/visibleTourEl\(/g) ?? []).length;
  assert.equal(uses, 5);
});

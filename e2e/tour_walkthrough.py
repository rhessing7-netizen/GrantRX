"""Product Walkthrough navigation E2E (Checkpoint C) — Playwright/Chromium.

Covers the confirmed trap fix: every step must be manually navigable.

  A. Full manual traversal 1→5 via Next → Finish → closed (no product actions)
  B. Back: step 3 → Back → step 2
  C. Skip Tour on a middle step → closed
  D. X on a middle step → closed
  E. Escape → closed
  F. Restart: after close/finish, Product Walkthrough → step 1
  G. Save auto-advance: dispatching the tour save event on step 2 → step 3;
     no event → no advance (failed action analogue)
  H. Manual navigation does not dispatch product writes (no Save API call)
  I. Responsive: controls visible at desktop / tablet / mobile widths
  J. Anonymous visitor never auto-starts the tour

Runs against the dev-mode backend (:8000, demo auth) + built frontend
(:3000), same harness as e2e/ui_journey.py. Requires a working local stack
(backend + local Postgres catalog); blocked while the %TEMP% catalog is
corrupted — see repo AGENTS.md.

Usage: python e2e/tour_walkthrough.py
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://localhost:3000"
RESULTS: list[tuple[str, bool, str]] = []

POPOVER = ".driver-popover"
NEXT = f"{POPOVER} .driver-popover-next-btn"
PREV = f"{POPOVER} .driver-popover-prev-btn"
CLOSE = f"{POPOVER} .driver-popover-close-btn"
DONE = f"{POPOVER} .driver-popover-next-btn"  # last step: next renders Done
SKIP = f"{POPOVER} .tour-skip-btn"
PROGRESS = f"{POPOVER} .driver-popover-progress-text, {POPOVER} .driver-popover-progress-btn"


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, ("| " + detail) if detail else "")


def open_tour(page) -> None:
    """Launch the tour manually via the LeftPanel Product Walkthrough button."""
    btn = page.locator("button", has_text="Product Walkthrough").first
    btn.scroll_into_view_if_needed()
    btn.click()
    page.wait_for_selector(POPOVER, timeout=8000)


def step_label(page) -> str:
    return page.locator(f"{POPOVER} .driver-popover-title").inner_text()


def tour_closed(page) -> bool:
    try:
        page.wait_for_selector(POPOVER, state="detached", timeout=5000)
        return True
    except PWTimeout:
        return page.locator(POPOVER).count() == 0


def authenticated_page(browser, width=1280, height=900):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    page.add_init_script(
        "try{localStorage.setItem('grantrx_auth_token','grantrx-dev-demo')}catch(e){}"
    )
    page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2500)
    return ctx, page


def test_a_forward_traversal(browser) -> None:
    ctx, page = authenticated_page(browser)
    try:
        open_tour(page)
        check("A: step 1 opens", "Matched Opportunities" in step_label(page))
        for expected in ["Save to Your Pipeline", "Application Pipeline",
                         "Apply or Draft", "All Set"]:
            page.locator(NEXT).click()
            page.wait_for_timeout(700)
            check(f"A: next → {expected}", expected in step_label(page),
                  step_label(page))
        page.locator(DONE).click()
        check("A: Finish closes tour", tour_closed(page))
    except Exception as e:  # noqa: BLE001 — report and continue
        check("A: traversal", False, repr(e)[:200])
    ctx.close()


def test_b_back(browser) -> None:
    ctx, page = authenticated_page(browser)
    try:
        open_tour(page)
        page.locator(NEXT).click(); page.wait_for_timeout(600)
        page.locator(NEXT).click(); page.wait_for_timeout(900)
        check("B: reached step 3", "Application Pipeline" in step_label(page))
        page.locator(PREV).click(); page.wait_for_timeout(900)
        check("B: Back → step 2", "Save to Your Pipeline" in step_label(page),
              step_label(page))
        page.locator(CLOSE).click()
    except Exception as e:  # noqa: BLE001
        check("B: back", False, repr(e)[:200])
    ctx.close()


def test_c_skip(browser) -> None:
    ctx, page = authenticated_page(browser)
    try:
        open_tour(page)
        page.locator(NEXT).click(); page.wait_for_timeout(600)
        page.locator(SKIP).click()
        check("C: Skip Tour closes", tour_closed(page))
    except Exception as e:  # noqa: BLE001
        check("C: skip", False, repr(e)[:200])
    ctx.close()


def test_d_close_x(browser) -> None:
    ctx, page = authenticated_page(browser)
    try:
        open_tour(page)
        page.locator(NEXT).click(); page.wait_for_timeout(600)
        page.locator(CLOSE).click()
        check("D: X closes", tour_closed(page))
    except Exception as e:  # noqa: BLE001
        check("D: close X", False, repr(e)[:200])
    ctx.close()


def test_e_escape(browser) -> None:
    ctx, page = authenticated_page(browser)
    try:
        open_tour(page)
        page.keyboard.press("Escape")
        check("E: Escape closes", tour_closed(page))
    except Exception as e:  # noqa: BLE001
        check("E: escape", False, repr(e)[:200])
    ctx.close()


def test_f_restart(browser) -> None:
    ctx, page = authenticated_page(browser)
    try:
        open_tour(page)
        page.locator(SKIP).click()
        assert tour_closed(page)
        open_tour(page)
        check("F: restart lands on step 1",
              "Matched Opportunities" in step_label(page))
        page.locator(CLOSE).click()
    except Exception as e:  # noqa: BLE001
        check("F: restart", False, repr(e)[:200])
    ctx.close()


def test_g_auto_advance(browser) -> None:
    ctx, page = authenticated_page(browser)
    try:
        open_tour(page)
        page.locator(NEXT).click(); page.wait_for_timeout(600)
        check("G: on step 2", "Save to Your Pipeline" in step_label(page))
        # No action fired → still on step 2
        page.wait_for_timeout(500)
        check("G: no action → no advance",
              "Save to Your Pipeline" in step_label(page))
        page.evaluate(
            "window.dispatchEvent(new CustomEvent('grantrx:tour:save-fired'))")
        page.wait_for_timeout(700)
        check("G: save event advances exactly one step",
              "Application Pipeline" in step_label(page), step_label(page))
        page.locator(CLOSE).click()
    except Exception as e:  # noqa: BLE001
        check("G: auto-advance", False, repr(e)[:200])
    ctx.close()


def test_h_no_mutation_on_nav(browser) -> None:
    ctx, page = authenticated_page(browser)
    try:
        writes: list[str] = []
        page.on("request", lambda r: writes.append(r.url)
                if r.method in ("POST", "PUT", "PATCH", "DELETE")
                and "user-scholarships" in r.url else None)
        open_tour(page)
        page.locator(NEXT).click(); page.wait_for_timeout(600)
        page.locator(PREV).click(); page.wait_for_timeout(600)
        page.locator(SKIP).click(); page.wait_for_timeout(400)
        check("H: navigation made no tracking writes", not writes,
              "; ".join(writes)[:120])
    except Exception as e:  # noqa: BLE001
        check("H: no mutation", False, repr(e)[:200])
    ctx.close()


def test_i_responsive(browser) -> None:
    for label, w, h in [("desktop", 1280, 900), ("tablet", 820, 1100),
                        ("mobile", 390, 844)]:
        ctx, page = authenticated_page(browser, w, h)
        try:
            open_tour(page)
            box = page.locator(POPOVER).bounding_box()
            visible = (
                box is not None and box["x"] >= 0 and box["y"] >= 0
                and box["x"] + box["width"] <= w
                and box["y"] + box["height"] <= h
            )
            nav_ok = page.locator(CLOSE).is_visible() and (
                page.locator(NEXT).is_visible()
                or page.locator(DONE).is_visible()
            )
            check(f"I: {label} ({w}px) popover in viewport + nav",
                  visible and nav_ok,
                  f"box={box}")
            page.locator(SKIP).click()
        except Exception as e:  # noqa: BLE001
            check(f"I: {label}", False, repr(e)[:160])
        ctx.close()


def test_j_anonymous_no_autostart(browser) -> None:
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    try:
        page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        check("J: anonymous does not auto-start tour",
              page.locator(POPOVER).count() == 0)
    except Exception as e:  # noqa: BLE001
        check("J: anonymous", False, repr(e)[:160])
    ctx.close()


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        test_a_forward_traversal(browser)
        test_b_back(browser)
        test_c_skip(browser)
        test_d_close_x(browser)
        test_e_escape(browser)
        test_f_restart(browser)
        test_g_auto_advance(browser)
        test_h_no_mutation_on_nav(browser)
        test_i_responsive(browser)
        test_j_anonymous_no_autostart(browser)
        browser.close()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

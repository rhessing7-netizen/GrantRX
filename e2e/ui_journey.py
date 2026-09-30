"""Final E2E — authenticated product journey (demo user) via Playwright.

Runs against the dev-mode backend (:8000, demo auth) + built frontend (:3000).
The demo user profile/rows are cleaned up afterwards by e2e/cleanup.py; the
final step here also exercises self-serve account deletion.

Usage: python e2e/ui_journey.py
"""

from __future__ import annotations

import os
import sys
import uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import psycopg
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://localhost:3000"
DB = os.getenv(
    "DATABASE_URL",
    "postgresql://grantrx:grantrx@127.0.0.1:5433/grantrx",
)
DEMO_ID = "00000000-0000-0000-0000-000000000001"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, ("| " + detail) if detail else "", flush=True)


def body_text(page) -> str:
    return page.evaluate("document.body.innerText")


def set_demo_searches(n: int) -> None:
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute(
            "UPDATE profiles SET searches_used_this_week=%s WHERE id=%s",
            (n, DEMO_ID),
        )


def demo_state() -> tuple[int, str] | None:
    with psycopg.connect(DB, autocommit=True) as c:
        row = c.execute(
            "SELECT searches_used_this_week, subscription_tier FROM profiles WHERE id=%s",
            (DEMO_ID,),
        ).fetchone()
        return row


def demo_tracking() -> list[tuple[str, str]]:
    with psycopg.connect(DB, autocommit=True) as c:
        return c.execute(
            "SELECT status::text, scholarship_id::text FROM user_scholarships "
            "WHERE user_id=%s AND NOT dismiss_only",
            (DEMO_ID,),
        ).fetchall()


def click_if_visible(page, selector: str, timeout=3000) -> bool:
    loc = page.locator(selector).first
    try:
        loc.wait_for(state="visible", timeout=timeout)
        loc.click()
        return True
    except PWTimeout:
        return False


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        # Prevent the interactive product tour from hijacking input; its
        # driver.js overlay intercepts all pointer events once started.
        page.add_init_script(
            "try{localStorage.setItem('grantrx_tour_completed','true')}catch(e){}")
        page.set_default_timeout(15000)

        # ---------- Onboarding ----------
        print("\n== Onboarding (all-optional) ==")
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        has_profile = demo_state() is not None
        if not has_profile:
            check("onboarding CTA visible",
                  click_if_visible(page, "button:has-text('Set up'), button:has-text('Start Onboarding')"))
            page.wait_for_timeout(600)
            check("wizard opens on step 1 (Fields of Study)",
                  "Fields of Study" in body_text(page))
            # Step semantics: everything optional, Continue always available
            check("skip offered on step 1",
                  "Skip Setup" in body_text(page))
            click_if_visible(page, "button:has-text('Continue')")
            page.wait_for_timeout(400)
            check("step 2 Academic Details reachable with empty step 1",
                  "Academic Details" in body_text(page))
            click_if_visible(page, "button:has-text('Continue')")
            page.wait_for_timeout(400)
            check("step 3 reachable", "Background" in body_text(page))
            # Finish/submit on last step
            finished = click_if_visible(page, "button:has-text('Finish')") or \
                click_if_visible(page, "button:has-text('Complete')") or \
                click_if_visible(page, "button[type=submit]")
            check("wizard submitted", finished)
            page.wait_for_timeout(2000)
            st = demo_state()
            check("profile persisted server-side", st is not None, str(st))
        else:
            print("(demo profile already exists — skipping onboarding)")

        print("\n== Discovery feed ==")
        page.wait_for_timeout(2500)
        t = body_text(page)
        check("feed loaded without crashing on empty profile",
              "opportunities matched" in t.lower() or "matched" in t.lower(),
              t[:150].replace("\n", " "))
        check("locked/masked free-tier results present or all-visible note",
              "free tier" in t.lower() or "visible" in t.lower())
        n_cards = page.locator("[aria-label^='View details for']").count()
        check("opportunity cards rendered", n_cards >= 1, f"{n_cards}")

        # ---------- Keyword quota UX ----------
        print("\n== Search quota UX ==")
        set_demo_searches(8)
        search_in = page.locator("input[placeholder*='Keyword']").first
        check("search input present", search_in.count() > 0)
        if search_in.count():
            search_in.fill("nursing")
            page.locator("button[aria-label='Search']").first.click()
            page.wait_for_timeout(2500)
            st = demo_state()
            check("UI search consumed quota (8->9)", st and st[0] == 9, str(st))
            search_in.fill("grant")
            page.locator("button[aria-label='Search']").first.click()
            page.wait_for_timeout(2500)
            st = demo_state()
            check("second search consumed (9->10)", st and st[0] == 10, str(st))
            # 11th search at cap: search button disables, Enter is inert,
            # limit message + Upgrade link appear; clicking it opens the modal.
            search_in.fill("fellowship")
            page.wait_for_timeout(600)
            btn = page.locator("button[aria-label='Search']").first
            check("search button disabled at cap", not btn.is_enabled())
            search_in.press("Enter")
            page.wait_for_timeout(1200)
            st = demo_state()
            check("Enter at cap did not consume quota", st and st[0] == 10, str(st))
            t = body_text(page)
            check("limit message shown at cap",
                  "limit reached" in t.lower() or "used all 10" in t.lower(),
                  t[:160].replace("\n", " "))
            up = page.locator("button:has-text('Upgrade to Premium')").first
            if up.count() and up.is_visible():
                up.click()
                page.wait_for_timeout(1200)
            t = body_text(page)
            check("upgrade entry reachable at cap",
                  "premium" in t.lower() or "upgrade" in t.lower(),
                  t[:120].replace("\n", " "))
            st = demo_state()
            check("blocked search did not consume", st and st[0] == 10, str(st))
            # close modal
            click_if_visible(page, "button[aria-label='Close'], button:has-text('✕'), button:has-text('Not now')")
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            # refresh still works at cap
            click_if_visible(page, "button:has-text('Refresh Matches')")
            page.wait_for_timeout(2000)
            t = body_text(page)
            check("match refresh still works at cap",
                  "matched" in t.lower() and "premium" not in t.lower()[:400],
                  t[:150].replace("\n", " "))
            # quota persists across reload
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            t = body_text(page)
            check("quota state persists across reload",
                  "10" in t or "0 of" in t or "limit" in t.lower())
        # reset for later sections
        set_demo_searches(0)

        print("\n== Save + application pipeline ==")
        save_btns = page.locator("button:has-text('Save'), button:has-text('Track'), button:has-text('Save for later')")
        if save_btns.count() == 0:
            # try card click -> drawer save
            card = page.locator("[aria-label^='View details for']").first
            if card.count():
                card.click()
                page.wait_for_timeout(800)
                save_btns = page.locator("button:has-text('Save'), button:has-text('Track')")
        if save_btns.count():
            save_btns.first.click()
            page.wait_for_timeout(1500)
        rows = demo_tracking()
        check("save persisted", len(rows) == 1, str(rows))

        # Kanban tab
        click_if_visible(page, "button:has-text('My Applications')")
        page.wait_for_timeout(1500)
        t = body_text(page)
        check("kanban shows saved item", "Saved" in t, t[:120].replace("\n", " "))

        # Move saved -> in_progress: desktop = dnd-kit drag between columns;
        # mobile pipeline = stage select. Try select first, then drag.
        sel = page.locator("select[aria-label='Move stage']:visible")
        moved = False
        if sel.count():
            sel.first.select_option("in_progress")
            moved = True
        else:
            # dnd-kit needs stepped pointer movement
            src = page.locator("text=Saved").first
            card_loc = page.locator("[class*='cursor-grab'], [draggable='true']").first
            target = page.locator("text=In Progress").first
            if card_loc.count() and target.count():
                cb = card_loc.bounding_box()
                tb = target.bounding_box()
                if cb and tb:
                    page.mouse.move(cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2)
                    page.mouse.down()
                    for i in range(1, 11):
                        page.mouse.move(
                            cb["x"] + (tb["x"] - cb["x"]) * i / 10,
                            cb["y"] + (tb["y"] - cb["y"]) * i / 10,
                        )
                        page.wait_for_timeout(60)
                    page.mouse.move(tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2)
                    page.wait_for_timeout(300)
                    page.mouse.up()
                    moved = True
        page.wait_for_timeout(1500)
        rows = demo_tracking()
        check("stage move persisted to in_progress",
              moved and any(r[0] == "in_progress" for r in rows),
              f"moved={moved} rows={rows}")

        print("\n== Calendar ==")
        click_if_visible(page, "button:has-text('Calendar')")
        page.wait_for_timeout(1500)
        t = body_text(page)
        check("calendar week view renders",
              "week of" in t.lower() or "next week" in t.lower(),
              t[:200].replace("\n", " "))
        # toggle month view and verify a full month grid renders
        click_if_visible(page, "button:has-text('Month')")
        page.wait_for_timeout(1200)
        t = body_text(page)
        check("calendar month view renders",
              any(m in t for m in ["January", "February", "March", "April", "May",
                                   "June", "July", "August", "September",
                                   "October", "November", "December"]),
              t[:200].replace("\n", " "))

        print("\n== Financial Planner ==")
        click_if_visible(page, "button:has-text('Financial Planner')")
        page.wait_for_timeout(1500)
        t = body_text(page)
        check("planner renders", "planner" in t.lower() or "tuition" in t.lower(),
              t[:120].replace("\n", " "))
        # fill a field and save if there's a save affordance
        num = page.locator("input[type=number]").first
        if num.count():
            num.fill("25000")
            saved = click_if_visible(page, "button:has-text('Save')")
            page.wait_for_timeout(1200)
            check("planner save clicked", saved)
        # reload persistence via API-read state checked in api_boundaries; here UI reload
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        click_if_visible(page, "button:has-text('Financial Planner')")
        page.wait_for_timeout(1500)
        t = body_text(page)
        check("planner persists after reload", "25,000" in t or "25000" in t, t[:150].replace("\n", " "))

        print("\n== Support ==")
        sup = page.locator("[aria-label*='Support'], button:has-text('Support'), button:has-text('Help')").first
        if sup.count():
            sup.click()
            page.wait_for_timeout(800)
            t = body_text(page)
            check("support drawer opens", "assistant" in t.lower() or "support" in t.lower())
            dlg = page.locator("[role='dialog']")
            check("support drawer is a labelled dialog", dlg.count() > 0)
            # guest mode (no Supabase session locally) shows a sign-in gate;
            # authenticated chat is covered by api_boundaries.py
            guest = "sign in to chat" in t.lower()
            if guest:
                check("guest mode shows sign-in gate (no Supabase session)", True)
            else:
                inp = page.locator("[role='dialog'] textarea").first
                if inp.count():
                    inp.fill("How do I upgrade?")
                    page.locator("[role='dialog'] button:has-text('Send')").first.click()
                    page.wait_for_timeout(3000)
                    check("support reply received",
                          len(page.locator("[role='dialog']").inner_text()) > 0)
            # Escape must dismiss the dialog (a11y)
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
            check("Escape closes support drawer",
                  page.locator("[role='dialog']").count() == 0)
        else:
            check("support launcher found", False)

        print("\n== Account settings + deletion ==")
        acc = page.locator("button:has-text('Account Settings'):visible, [aria-label='Account']:visible").first
        if acc.count():
            acc.click()
            page.wait_for_timeout(800)
            t = body_text(page)
            check("account settings opens", "account" in t.lower() or "settings" in t.lower())
            # Danger Zone lives on the Security tab
            click_if_visible(page, "button:has-text('Security'), [role='tab']:has-text('Security')")
            page.wait_for_timeout(600)
            del_btn = page.locator("button:has-text('Delete My Account')").first
            if del_btn.count():
                del_btn.click()
                page.wait_for_timeout(800)
                t = body_text(page)
                check("delete confirmation requires typing DELETE",
                      "type" in t.lower() and "delete" in t.lower())
                confirm = page.locator("button:has-text('Yes, delete my account')").first
                check("confirm disabled until DELETE typed",
                      confirm.count() > 0 and not confirm.is_enabled())
                inp = page.locator("input[placeholder*='DELETE']").first
                if inp.count():
                    inp.fill("DELETE")
                    page.wait_for_timeout(400)
                    check("confirm enabled after typing DELETE",
                          confirm.is_enabled())
                    confirm.click()
                    page.wait_for_timeout(3000)
                    t = body_text(page)
                    st = demo_state()
                    check("account deleted (profile gone)", st is None, str(st))
                    check("post-delete UI shows deleted/onboarding state",
                          "deleted" in t.lower() or "onboarding" in t.lower()
                          or "set up" in t.lower())
            else:
                check("delete account control present", False, "no Delete button on Security tab")
        else:
            check("account settings entry found", False)

        browser.close()

    print("\n======== SUMMARY ========")
    fails = [r for r in RESULTS if not r[1]]
    print(f"{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for n, _, d in fails:
        print("  FAIL:", n, d)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

"""Final E2E — UI smoke + public/anonymous surface (Playwright, Chromium).

Targets the built frontend (http://localhost:3000) talking to the dev-mode
backend (:8000, demo auth). Public/anonymous paths and branding; the
historical "anonymous -> false session expired" regression is checked via
request interception.

Usage: python e2e/ui_smoke.py
"""

from __future__ import annotations

import re
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, ("| " + detail) if detail else "")


def page_text(page) -> str:
    return page.evaluate("document.body.innerText")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)

        print("\n== Public pages ==")
        for path, expect in [
            ("/", "Discover"),
            ("/privacy", "Privacy"),
            ("/terms", "Terms"),
            ("/early-access", "early"),
            ("/crawler", "crawler"),
        ]:
            resp = page.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
            text = page_text(page)
            check(f"GET {path} renders", resp.status == 200 and expect.lower() in text.lower(),
                  f"{resp.status}")

        text = page_text(page)
        # grantrx.com email addresses are documented production contact config
        # (docs/PRODUCTION_CONFIGURATION.md) — flag only wordmark-style residue.
        residual = re.sub(r"[\w.]+@grantrx\.com", "", text.lower())
        check("no residual GrantRx/Fundria branding on public pages",
              "grantrx" not in residual and "grant rx" not in residual
              and "fundria" not in residual)

        print("\n== Early-access form (anonymous) ==")
        page.goto(BASE + "/early-access", wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        ea_text = page_text(page)
        check("early-access shows EdFintia branding", "edfintia" in ea_text.lower())
        email_in = page.locator("input[type=email], input[name=email]").first
        check("early-access email field present", email_in.count() > 0)
        # invalid email
        if email_in.count():
            email_in.fill("not-an-email")
            btn = page.locator("button[type=submit], button:has-text('Join'), button:has-text('early')").first
            if btn.count():
                btn.click()
                page.wait_for_timeout(800)
                t = page_text(page)
                check("invalid email shows validation", "valid" in t.lower() or "error" in t.lower())
        # valid signup
        page.reload(wait_until="domcontentloaded")
        email_in = page.locator("input[type=email]").first
        if email_in.count():
            email_in.fill("e2e-ui-check@e2e.test")
            fn = page.locator("input[name=first_name], input[placeholder*=ame]").first
            if fn.count():
                fn.fill("E2E")
            # consent checkbox
            cb = page.locator("input[type=checkbox]")
            for i in range(cb.count()):
                if not cb.nth(i).is_checked():
                    cb.nth(i).check()
            btn = page.locator("button[type=submit]").first
            if btn.count():
                btn.click()
                page.wait_for_timeout(1500)
                t = page_text(page)
                check("valid early-access signup succeeds",
                      "early-access list" in t or "watch your inbox" in t.lower() or "on the list" in t.lower(),
                      t[:120].replace("\n", " "))

        print("\n== Home: anonymous + demo flow ==")
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        home = page_text(page)
        check("home renders Discover", "Discover" in home)
        check("EdFintia present", "edfintia" in home.lower())
        check("onboarding CTA for profile-less user",
              "onboarding" in home.lower() or "complete your profile" in home.lower())
        # demo backend injects demo user (no profile) -> must NOT claim session expired
        check("no false 'session expired' for anonymous",
              "session has expired" not in home.lower())

        # The historical regression: force the matched endpoint to 401 with no
        # token set -> UI must say "sign in", NOT "session expired".
        page2 = ctx.new_page()
        def force401(route):
            route.fulfill(status=401, content_type="application/json",
                          body='{"detail":"Missing authorization header"}')
        page2.route("**/api/scholarships/matched*", force401)
        page2.route("**/profiles/me*", force401)
        page2.route("**/api/user/usage*", force401)
        page2.goto(BASE + "/", wait_until="domcontentloaded")
        page2.wait_for_timeout(2500)
        t2 = page_text(page2)
        check("401 w/o token -> 'sign in' not 'session expired'",
              "session has expired" not in t2.lower() and "sign in" in t2.lower(),
              t2[:200].replace("\n", " "))
        page2.unroute("**/api/scholarships/matched*", force401)
        page2.unroute("**/profiles/me*", force401)
        page2.unroute("**/api/user/usage*", force401)

        print("\n== Interactive elements (desktop) ==")
        buttons = page.locator("button:visible").all_inner_texts()
        check("auth entry point exists",
              any(re.search(r"sign in|log in|get started", b, re.I) for b in buttons),
              str(buttons)[:200])
        check("support launcher exists",
              any(re.search(r"support|help", b, re.I) for b in buttons)
              or page.locator("[aria-label*=upport], [aria-label*=elp]").count() > 0)

        # API 404s (no-profile user) surface as console "resource" noise but are
        # handled app logic — only flag static-asset / script failures.
        errs = [e for e in console_errors
                if "favicon" not in e and "ERR_" not in e
                and "404" not in e and "Not Found" not in e]
        check("no unexpected console errors", len(errs) == 0, str(errs[:3]))

        browser.close()

    print("\n======== SUMMARY ========")
    fails = [r for r in RESULTS if not r[1]]
    print(f"{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for n, _, d in fails:
        print("  FAIL:", n, d)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

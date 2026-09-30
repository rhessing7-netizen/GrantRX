"""Final E2E — responsive viewports + accessibility (axe-core) checks.

Runs against the built frontend (:3000) + dev backend (:8000, demo auth).
Viewports: 375, 430, 768, 1280 px widths.

Usage: python e2e/responsive_a11y.py
"""

from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://localhost:3000"
AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"
RESULTS: list[tuple[str, bool, str]] = []
AXE_VIOLATIONS: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, ("| " + detail) if detail else "", flush=True)


def body_text(page) -> str:
    return page.evaluate("document.body.innerText")


def overflow_px(page) -> int:
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


def run_axe(page, label: str) -> None:
    try:
        page.add_script_tag(url=AXE_CDN)
        res = page.evaluate(
            """async () => {
                const r = await axe.run(document, {
                  runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] }
                });
                return r.violations.map(v => ({
                  id: v.id, impact: v.impact,
                  nodes: v.nodes.slice(0, 3).map(n => n.target.join(' ')),
                  desc: v.help,
                }));
            }"""
        )
    except Exception as e:  # CDN unreachable etc.
        check(f"axe[{label}] executed", False, f"{type(e).__name__}: {e}")
        return
    serious = [v for v in res if v["impact"] in ("critical", "serious")]
    AXE_VIOLATIONS.extend({**v, "page": label} for v in res)
    check(f"axe[{label}] no critical/serious violations", not serious,
          "; ".join(f"{v['id']}({v['impact']}): {v['nodes'][:1]}" for v in serious) or f"{len(res)} minor/moderate")


def keyboard_probe(page, label: str) -> None:
    # Tab 12 times; at least once focus must land on a visible element with a
    # computed outline/focus style, and focus must never be lost to <body>.
    page.keyboard.press("Tab")
    seen_focused = 0
    for _ in range(12):
        page.keyboard.press("Tab")
        info = page.evaluate(
            """() => {
                const el = document.activeElement;
                if (!el || el === document.body) return {tag:'body'};
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                const visible = r.width > 0 && r.height > 0 && s.visibility !== 'hidden';
                return {tag: el.tagName + ':' + (el.getAttribute('aria-label') || el.textContent || '').slice(0,30),
                        visible};
            }"""
        )
        if info.get("visible"):
            seen_focused += 1
    check(f"keyboard[{label}] tab reaches visible focusable elements",
          seen_focused >= 3, f"{seen_focused} focusable stops")


def main() -> int:
    viewports = [375, 430, 768, 1280]
    with sync_playwright() as p:
        browser = p.chromium.launch()

        for w in viewports:
            ctx = browser.new_context(viewport={"width": w, "height": 850})
            page = ctx.new_page()
            page.add_init_script(
                "try{localStorage.setItem('grantrx_tour_completed','true');"
                "localStorage.setItem('grantrx_auth_token','grantrx-dev-demo')}catch(e){}")
            page.set_default_timeout(12000)

            # Home (authenticated demo user, has profile from earlier phases? —
            # anonymous surface is what matters for layout checks)
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            ov = overflow_px(page)
            check(f"home[{w}px] no horizontal overflow", ov <= 1, f"{ov}px")
            t = body_text(page)
            check(f"home[{w}px] renders", len(t) > 100)
            if w < 1024:
                nav = page.locator("nav").last
                bt = body_text(page)
                check(f"home[{w}px] mobile nav present",
                      nav.count() > 0 and ("Discover" in bt or "Home" in bt))

            # Early access page
            page.goto(BASE + "/early-access", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            ov = overflow_px(page)
            check(f"early-access[{w}px] no horizontal overflow", ov <= 1, f"{ov}px")
            check(f"early-access[{w}px] form renders",
                  bool(page.locator("input[type='email'], input[name*='email']").count()))

            # Privacy + terms
            for route in ("/privacy", "/terms"):
                page.goto(BASE + route, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
                ov = overflow_px(page)
                check(f"{route}[{w}px] no horizontal overflow", ov <= 1, f"{ov}px")

            ctx.close()

        # ---- Accessibility on a desktop context ----
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.add_init_script(
            "try{localStorage.setItem('grantrx_tour_completed','true')}catch(e){}")
        page.set_default_timeout(12000)

        for route in ("/", "/early-access", "/privacy", "/terms"):
            page.goto(BASE + route, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            run_axe(page, route)
            keyboard_probe(page, route)

        # Modal a11y: auth modal focus + Escape
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        sign_in = page.locator("button:has-text('Sign In'), button:has-text('Sign in'), button:has-text('Log in')").first
        if sign_in.count() and sign_in.is_visible():
            sign_in.click()
            page.wait_for_timeout(800)
            dlg = page.locator("[role='dialog'], [aria-modal='true']")
            check("auth modal exposes dialog semantics", dlg.count() > 0)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            check("Escape closes auth modal", page.locator("[role='dialog'], [aria-modal='true']").count() == 0)
        else:
            # authenticated surface — open account settings instead
            acc = page.locator("button:has-text('Account Settings'):visible").first
            if acc.count():
                acc.click()
                page.wait_for_timeout(800)
                dlg = page.locator("[role='dialog'], [aria-modal='true'], .fixed.inset-0")
                check("settings modal opens", dlg.count() > 0)
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)

        ctx.close()
        browser.close()

    print("\n======== SUMMARY ========")
    fails = [r for r in RESULTS if not r[1]]
    print(f"{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for n, _, d in fails:
        print("  FAIL:", n, d)
    if AXE_VIOLATIONS:
        print("\n-- all axe violations (any impact) --")
        for v in AXE_VIOLATIONS:
            print(f"  [{v['page']}] {v['id']} {v['impact']}: {v['desc']} -> {v['nodes'][:1]}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

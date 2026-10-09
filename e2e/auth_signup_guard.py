"""E2E — signup/auth fail-closed guards (Playwright).

Stubs Supabase's gotrue endpoints at the network layer so no real Supabase
project is touched, then verifies the signup → session → save chain never
advances to authenticated UI without a usable access token:

  A. signUp returns error            → error shown, no onboarding, no auth state
  B. signUp returns user + no session → fail-closed, not authenticated
  B2. OTP verify returns no session   → fail-closed, not authenticated
  C. signUp returns session + token   → authenticated flow proceeds
  D. signIn returns ok + no session   → handleAuthSuccess cannot mark signed-in
  E. anonymous load                   → zero protected API requests

Usage: python e2e/auth_signup_guard.py
Requires: dev backend on :8000 + built frontend on BASE (:3000).
"""

from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
API = "http://localhost:8000"
RESULTS: list[tuple[str, bool, str]] = []

FAKE_USER = {
    "id": "11111111-2222-3333-4444-555555555555",
    "aud": "authenticated",
    "role": "authenticated",
    "email": "jane@example.com",
}
# GoTrue returns sessions FLAT (access_token at top level) — gotrue-js's
# _sessionResponse/hasSession builds the session object from these fields.
FAKE_SESSION = {
    "access_token": "e2e-fake-access-token",
    "token_type": "bearer",
    "expires_in": 3600,
    "refresh_token": "e2e-fake-refresh",
    "user": FAKE_USER,
}
PUBLIC_BACKEND = ("match-preview", "early-access", "unsubscribe")


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, ("| " + detail) if detail else "", flush=True)


def body_text(page) -> str:
    return page.evaluate("document.body.innerText")


def fulfill_json(route, status: int, payload: dict) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def protected_calls(page) -> list[str]:
    calls: list[str] = []

    def on_request(req) -> None:
        if API in req.url and not any(p in req.url for p in PUBLIC_BACKEND):
            calls.append(f"{req.method} {req.url.split(API)[-1]}")

    page.on("request", on_request)
    return calls


def wait_ready(page) -> bool:
    """Wait for auth resolution + hydration to expose the auth launcher."""
    try:
        page.locator(
            "button:has-text('Sign In / Sign Up')"
        ).first.wait_for(state="visible", timeout=20000)
        return True
    except Exception:
        return False


def fill_signup_form(page) -> None:
    ready = wait_ready(page)
    page.locator("button:has-text('Sign In / Sign Up')").first.click()
    page.locator("input[placeholder='Jane Doe']").fill("Jane Doe")
    page.locator("input[type='email']").fill("jane@example.com")
    page.locator("input[placeholder='At least 6 characters']").fill("password123")
    page.locator("input[placeholder='Re-enter your password']").fill("password123")
    page.locator("input[type='checkbox']").first.check()
    page.locator("button:has-text('Create Account')").click()


def scenario(page, signup_status, signup_body, verify_body=None) -> list[str]:
    calls = protected_calls(page)
    page.route(
        "**/auth/v1/signup*",
        lambda r: fulfill_json(r, signup_status, signup_body),
    )
    if verify_body is not None:
        page.route(
            "**/auth/v1/verify*",
            lambda r: fulfill_json(r, 200, verify_body),
        )
    return calls


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---------- E. Anonymous protection ----------
        print("\n== E. Anonymous protection ==")
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        calls = protected_calls(page)
        page.goto(BASE + "/", wait_until="domcontentloaded")
        ready = wait_ready(page)
        check("anonymous load shows sign-in prompt",
              "sign in" in body_text(page).lower())
        check("no protected API requests while anonymous",
              calls == [], str(calls[:5]))
        ctx.close()

        # ---------- A. signUp returns error ----------
        print("\n== A. signUp error ==")
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        calls = scenario(page, 400, {
            "code": 400,
            "error_code": "over_email_send_rate_limit",
            "msg": "email rate limit exceeded",
        })
        page.goto(BASE + "/", wait_until="domcontentloaded")
        ready = wait_ready(page)
        fill_signup_form(page)
        page.wait_for_timeout(2000)
        t = body_text(page).lower()
        check("signup error surfaced to user",
              "rate limit" in t or "failed" in t or "error" in t)
        check("onboarding did not open on signup error",
              "fields of study" not in t)
        check("modal still open for retry",
              "create account" in t)
        check("no protected requests after failed signup",
              calls == [], str(calls[:5]))
        ctx.close()

        # ---------- B. signUp user + no session (confirmed/existing) ----------
        print("\n== B. signUp user, no session ==")
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        calls = scenario(page, 200, {
            "user": {**FAKE_USER, "email_confirmed_at": "2026-01-01T00:00:00Z"},
            "session": None,
        })
        page.goto(BASE + "/", wait_until="domcontentloaded")
        ready = wait_ready(page)
        fill_signup_form(page)
        page.wait_for_timeout(2000)
        t = body_text(page).lower()
        check("ambiguous no-session signup stays on modal with message",
              "sign in" in t and "fields of study" not in t)
        check("no protected requests after no-session signup",
              calls == [], str(calls[:5]))
        ctx.close()

        # ---------- B2. OTP screen then verify without session ----------
        print("\n== B2. confirmation-required -> verify without session ==")
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        calls = scenario(
            page, 200,
            {"user": {**FAKE_USER, "email_confirmed_at": None}, "session": None},
            verify_body={"user": FAKE_USER, "session": None},
        )
        page.goto(BASE + "/", wait_until="domcontentloaded")
        ready = wait_ready(page)
        fill_signup_form(page)
        page.wait_for_timeout(2000)
        t = body_text(page).lower()
        check("unconfirmed signup shows OTP verification screen",
              "verify your email" in t or "verification code" in t, t[:100])
        page.locator("input[inputmode='numeric']").fill("123456")
        page.locator("button:has-text('Verify Code')").click()
        page.wait_for_timeout(2000)
        t = body_text(page).lower()
        check("verify without session fails closed (no onboarding)",
              "fields of study" not in t and "sign in" in t, t[:120])
        check("no protected requests across OTP flow",
              calls == [], str(calls[:5]))
        ctx.close()

        # ---------- C. signUp session + token -> authenticated ----------
        print("\n== C. signUp session + token ==")
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        calls = scenario(page, 200, dict(FAKE_SESSION))
        page.goto(BASE + "/", wait_until="domcontentloaded")
        ready = wait_ready(page)
        fill_signup_form(page)
        page.wait_for_timeout(4000)
        t = body_text(page).lower()
        authed = (
            "sign out" in t
            or "fields of study" in t
            or "matched" in t
        ) and "create account" not in t
        check("valid session advances to authenticated experience",
              authed, t[:140])
        check("profile save request reached backend",
              any("/profiles" in c for c in calls), str(calls[:6]))
        ctx.close()

        # ---------- D. signIn ok + no session -> page-level guard ----------
        print("\n== D. signIn no-session -> handleAuthSuccess guard ==")
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        calls = protected_calls(page)
        page.route(
            "**/auth/v1/token*",
            lambda r: fulfill_json(r, 200, {
                "access_token": None,
                "token_type": "bearer",
                "expires_in": 0,
                "refresh_token": None,
                "user": FAKE_USER,
            }),
        )
        page.goto(BASE + "/", wait_until="domcontentloaded")
        wait_ready(page)
        page.locator("button:has-text('Sign In / Sign Up')").first.click()
        # Mode toggle inside the dialog (toggle precedes the submit button in DOM order)
        page.locator("div[role='dialog'] button:has-text('Sign In')").first.click()
        page.locator("input[type='email']").fill("jane@example.com")
        page.locator("input[placeholder='At least 6 characters']").fill("password123")
        page.locator("div[role='dialog'] button[type='submit']").click()
        page.wait_for_timeout(2000)
        t = body_text(page).lower()
        check("no-session sign-in does not open onboarding",
              "fields of study" not in t)
        check("no-session sign-in leaves app unauthenticated",
              "sign in" in t)
        check("no protected requests after no-session sign-in",
              calls == [], str(calls[:5]))
        ctx.close()

        browser.close()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n======== SUMMARY ========")
    print(f"{passed} passed, {len(failed)} failed")
    for n in failed:
        print("  FAIL:", n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

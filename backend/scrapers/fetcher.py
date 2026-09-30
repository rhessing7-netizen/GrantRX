"""Async HTML fetcher with three-tier strategy.

Tier 1 — Deterministic / Static: httpx GET through the C6 polite fetch
         policy (honest EdFintiaBot identity, robots.txt, per-host pacing,
         bounded retries).
Tier 2 — Headless Dynamic: Playwright for JS-rendered SPAs. It exists to
         *render JavaScript*, not to evade access controls: it runs under
         the same honest identity, the same robots/pacing gate, and only
         when the httpx response is a JS-only shell or the source requests
         it explicitly. A server that refuses us (403/429, robots denial)
         is not escalated to a browser.
Tier 3 — LLM Fallback: handled by llm_parser.py (not this module).

The fetcher auto-selects the tier based on:
  - The source's scraper_type ("deterministic", "playwright", "llm_fallback")
  - httpx response heuristics (JS-only shell detection)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .fetch_policy import (
    OUTCOME_OK,
    OUTCOME_PERMANENT_HTTP,
    FetchResult,
    FetchSession,
    crawler_user_agent,
    default_session,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0

# Heuristics for when to skip Playwright and accept the httpx response
_JS_SIGNALS = ("__NEXT_DATA__", "window.__INITIAL_STATE__", 'id="root"')

# Common DOM selectors that indicate scholarship content has loaded
_CONTENT_SELECTORS = [
    "h1",
    "h2",
    ".scholarship",
    ".scholarship-list",
    "[class*='scholarship']",
    "[class*='award']",
    "table",
    "main",
    "article",
    "#content",
    "#main-content",
]


async def fetch_result(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    scraper_type: str = "deterministic",
    use_playwright_fallback: bool = True,
    session: Optional[FetchSession] = None,
) -> FetchResult:
    """Fetch a URL through the C6 policy; Playwright only for JS rendering.

    Returns the FetchResult describing what happened. ``text`` holds the
    HTML on a successful GET (Playwright-rendered HTML is also placed in
    ``text`` so callers don't care which tier produced it).
    """
    session = session or default_session()

    # If the source explicitly requests Playwright, go straight to Tier 2 —
    # still under the same robots/pacing gate.
    if scraper_type == "playwright":
        logger.info("Tier 2 (Playwright) selected for %s (scraper_type=playwright)", url)
        rendered = await _fetch_with_playwright(url, timeout=timeout, session=session)
        if rendered:
            return FetchResult(url=url, outcome=OUTCOME_OK, http_status=200, text=rendered)
        logger.warning("Playwright unavailable/failed for %s; trying httpx", url)

    result = await session.get(url, timeout=timeout)
    if result.ok:
        if result.text and _looks_js_only(result.text) and use_playwright_fallback:
            # A JS shell is a rendering problem, not a refusal — the one
            # legitimate reason to involve a browser.
            logger.info("httpx response looks JS-only, rendering with Playwright: %s", url)
            rendered = await _fetch_with_playwright(url, timeout=timeout, session=session)
            if rendered:
                result.text = rendered
        return result

    # No browser escalation on refusals/errors: a 403/429 or robots denial
    # is the site's decision and must stand (C6: report, don't circumvent).
    if result.outcome != OUTCOME_PERMANENT_HTTP:
        logger.warning("Fetch %s for %s: %s", result.outcome, url, result.error)
    else:
        logger.debug("Fetch permanent error for %s: %s", url, result.error)
    return result


async def fetch_html(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    scraper_type: str = "deterministic",
    use_playwright_fallback: bool = True,
    session: Optional[FetchSession] = None,
) -> str:
    """Fetch HTML for a URL using the appropriate tier (compat wrapper).

    Returns the HTML string, or "" when the fetch did not succeed —
    including robots denials, which are policy outcomes, not errors.
    """
    result = await fetch_result(
        url,
        timeout=timeout,
        scraper_type=scraper_type,
        use_playwright_fallback=use_playwright_fallback,
        session=session,
    )
    return result.text if result.ok else ""


def _looks_js_only(html: str) -> bool:
    if not html:
        return True
    text = html.strip()
    if len(text) < 600:
        return True
    return any(signal in html for signal in _JS_SIGNALS) and "<h1" not in html.lower()


# ---------------------------------------------------------------------------
# Tier 2: Playwright headless dynamic renderer
# ---------------------------------------------------------------------------


async def _fetch_with_playwright(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    wait_selector: Optional[str] = None,
    session: Optional[FetchSession] = None,
) -> Optional[str]:
    """Render a page with Playwright (Tier 2).

    Policy (C6): the browser identifies itself as EdFintiaBot, passes the
    same robots.txt + per-host pacing + concurrency gate as every other
    fetch BEFORE the browser is even launched, and uses no stealth or
    bot-detection evasion. If a site requires circumvention, we report the
    source as unsupported instead.

    Returns None if the fetch is denied, Playwright is unavailable, or the
    page fails to load.
    """
    session = session or default_session()
    async with session.acquire(url) as denial:
        if denial is not None:
            logger.warning("Playwright fetch refused by policy for %s: %s", url, denial.outcome)
            return None
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed; cannot render JS pages.")
            return None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                try:
                    context = await browser.new_context(
                        user_agent=crawler_user_agent(),
                        viewport={"width": 1920, "height": 1080},
                        locale="en-US",
                        extra_http_headers={
                            "Accept-Language": "en-US,en;q=0.9",
                        },
                    )
                    page = await context.new_page()

                    await page.goto(
                        url,
                        timeout=timeout * 1000,
                        wait_until="domcontentloaded",
                    )

                    # Wait for network to settle (shorter timeout than overall)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=min(timeout * 500, 15000))
                    except Exception:
                        # networkidle can hang on long-polling sites; continue anyway
                        logger.debug("networkidle wait timed out for %s, continuing", url)

                    # Wait for a content selector to appear (content-ready detection)
                    selector = wait_selector or _pick_content_selector()
                    try:
                        await page.wait_for_selector(selector, timeout=10000)
                        logger.debug("Content selector '%s' found for %s", selector, url)
                    except Exception:
                        logger.debug("Content selector '%s' not found for %s; proceeding", selector, url)

                    # Extra delay for late-rendering JS frameworks
                    await page.wait_for_timeout(1500)

                    # Try scrolling to trigger lazy-loaded content
                    try:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(500)
                        await page.evaluate("window.scrollTo(0, 0)")
                    except Exception:
                        pass

                    html = await page.content()
                    return html
                finally:
                    await browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.error("Playwright fetch failed for %s: %s", url, exc)
            return None


def _pick_content_selector() -> str:
    """Pick a CSS selector likely to be present when content is loaded."""
    return ", ".join(_CONTENT_SELECTORS)


# ---------------------------------------------------------------------------
# Batch fetcher
# ---------------------------------------------------------------------------


async def fetch_many(
    urls: list[str],
    *,
    concurrency: int = 5,
    scraper_types: Optional[dict[str, str]] = None,
    session: Optional[FetchSession] = None,
) -> list[tuple[str, Optional[str]]]:
    """Fetch multiple URLs concurrently, returning (url, html_or_None) tuples.

    The C6 policy bounds the real concurrency: this semaphore, the session's
    global limit, and the per-host limit all apply (the tightest wins).

    Args:
        urls: List of URLs to fetch.
        concurrency: Max concurrent requests for this batch.
        scraper_types: Optional mapping of url -> scraper_type for tier selection.
        session: FetchSession to share policy state with (default: run session).
    """
    session = session or default_session()
    sem = asyncio.Semaphore(concurrency)
    types_map = scraper_types or {}

    async def _one(u: str) -> tuple[str, Optional[str]]:
        async with sem:
            try:
                result = await fetch_result(u, scraper_type=types_map.get(u, "deterministic"),
                                            session=session)
                return u, (result.text if result.ok and result.text else None)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to fetch %s: %s", u, exc)
                return u, None

    fetched = await asyncio.gather(*(_one(u) for u in urls))
    if session.outcome_counts:
        logger.info("Fetch outcomes: %s", session.outcomes_summary())
    return fetched

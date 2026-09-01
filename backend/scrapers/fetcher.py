"""Async HTML fetcher with three-tier strategy.

Tier 1 — Deterministic / Static: fast httpx async GET for well-structured endpoints.
Tier 2 — Headless Dynamic: Playwright for JS-rendered SPAs, waits for DOM
         selector availability, bypasses basic bot checks, extracts rendered HTML.
Tier 3 — LLM Fallback: handled by llm_parser.py (not this module).

The fetcher auto-selects the tier based on:
  - The source's scraper_type ("deterministic", "playwright", "llm_fallback")
  - httpx response heuristics (JS-only shell detection, 403/405 status codes)
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

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


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


async def fetch_html(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    scraper_type: str = "deterministic",
    use_playwright_fallback: bool = True,
) -> str:
    """Fetch HTML for a URL using the appropriate tier.

    Args:
        url: Target URL.
        timeout: Per-request timeout in seconds.
        scraper_type: "deterministic" (Tier 1), "playwright" (Tier 2),
                      or "llm_fallback" (Tier 3 — still fetches via httpx first).
        use_playwright_fallback: If True, fall back to Playwright when httpx
                                 gets a JS-only shell or error status.
    """
    # If the source explicitly requests Playwright, go straight to Tier 2
    if scraper_type == "playwright":
        logger.info("Tier 2 (Playwright) selected for %s (scraper_type=playwright)", url)
        rendered = await _fetch_with_playwright(url, timeout=timeout)
        if rendered:
            return rendered
        # Fall back to httpx if Playwright fails
        logger.warning("Playwright failed for %s; falling back to httpx", url)

    # Tier 1: httpx
    headers = {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        try:
            resp = await client.get(url)
            # 403/405 typically means bot protection — try Playwright
            if resp.status_code in (403, 405) and use_playwright_fallback:
                logger.warning(
                    "httpx got HTTP %d for %s; trying Playwright (Tier 2)",
                    resp.status_code,
                    url,
                )
                rendered = await _fetch_with_playwright(url, timeout=timeout)
                return rendered or ""
            resp.raise_for_status()
            html = resp.text
            if not _looks_js_only(html) or not use_playwright_fallback:
                return html
            logger.info("httpx response looks JS-only, falling back to Playwright: %s", url)
        except httpx.HTTPError as exc:
            if not use_playwright_fallback:
                raise
            logger.warning("httpx fetch failed (%s); trying Playwright: %s", exc, url)
            html = ""

    rendered = await _fetch_with_playwright(url, timeout=timeout)
    return rendered or html


def _looks_js_only(html: str) -> bool:
    if not html:
        return True
    text = html.strip()
    if len(text) < 600:
        return True
    return any(signal in html for signal in _JS_SIGNALS) and "<h1" not in html.lower()


# ---------------------------------------------------------------------------
# Tier 2: Playwright headless dynamic crawler
# ---------------------------------------------------------------------------


async def _fetch_with_playwright(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    wait_selector: Optional[str] = None,
) -> Optional[str]:
    """Render a page with Playwright (Tier 2).

    Enhancements over the basic version:
    - Stealth-like browser config (realistic viewport, UA, locale)
    - Waits for DOM selector availability (content-ready detection)
    - Bypasses basic bot checks by waiting for network idle + extra delay
    - Extracts rendered outer HTML (not just page.content())

    Returns None if Playwright is unavailable or the page fails to load.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed; cannot render JS pages.")
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context = await browser.new_context(
                    user_agent=_random_ua(),
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                # Remove webdriver property to bypass basic bot detection
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )

                page = await context.new_page()

                # Navigate with domcontentloaded first, then wait for network idle
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

                # Extract rendered outer HTML
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
) -> list[tuple[str, Optional[str]]]:
    """Fetch multiple URLs concurrently, returning (url, html_or_None) tuples.

    Args:
        urls: List of URLs to fetch.
        concurrency: Max concurrent requests.
        scraper_types: Optional mapping of url -> scraper_type for tier selection.
    """
    sem = asyncio.Semaphore(concurrency)
    types_map = scraper_types or {}

    async def _one(u: str) -> tuple[str, Optional[str]]:
        async with sem:
            try:
                return u, await fetch_html(u, scraper_type=types_map.get(u, "deterministic"))
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to fetch %s: %s", u, exc)
                return u, None

    return await asyncio.gather(*(_one(u) for u in urls))

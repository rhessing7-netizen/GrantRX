"""Page link inventory and URL acceptance (Catalog Batch C5).

The extractor may only return URLs that genuinely appear on the fetched page.
This module builds that inventory and enforces the rule deterministically, so
a hallucinated or injected URL can never become an opportunity's portal URL.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from .normalize import clean_text

# Page chrome that is navigation, not opportunity content.
CHROME_TAGS = ("nav", "header", "footer", "aside")


def normalize_link(url: str) -> str:
    """Comparison form of a URL: https, lowercase host without www, no
    fragment, no trailing slash. Query is kept verbatim — this is link
    *equality*, not opportunity identity (that is C4's canonicalization)."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not p.hostname:
        return ""
    host = p.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse(("https", host, path, "", p.query, ""))


def resolve_url(raw: str, base: str) -> str:
    """Resolve a possibly-relative href against the page URL (http/https only)."""
    raw = (raw or "").strip()
    if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:")):
        return ""
    try:
        resolved = urljoin(base, raw)
    except ValueError:
        return ""
    return resolved if normalize_link(resolved) else ""


def extract_links(html: str, base_url: str, *, include_chrome: bool = False,
                  limit: Optional[int] = None) -> List[Tuple[str, str]]:
    """Return [(anchor_text, absolute_url)] in document order, deduplicated.

    Navigation chrome (nav/header/footer/aside) is excluded unless requested.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    if not include_chrome:
        for tag in soup.find_all(CHROME_TAGS):
            tag.decompose()
    out: List[Tuple[str, str]] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        url = resolve_url(a["href"], base_url)
        key = normalize_link(url)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((clean_text(a.get_text(" "))[:120], url))
        if limit and len(out) >= limit:
            break
    return out


def link_index(html: str, base_url: str) -> Dict[str, str]:
    """normalized URL -> actual absolute href, for every link on the page
    (chrome included: an application button can legitimately live anywhere)."""
    return {normalize_link(u): u for _, u in extract_links(html, base_url, include_chrome=True)}


# Transaction/donation endpoints are never application portals or
# opportunity detail pages — community-foundation fund listings commonly
# carry per-fund "give" links that are donor checkout pages (E2 finding).
_NON_PORTAL_PATH = re.compile(
    r"(?:/(?:donate|donation|donations|give|giving|checkout|cart|payment|pay|"
    r"contribute|contribution)(?:/|$))|(?:-(?:donate|donation|donations|"
    r"contribute|contribution|checkout)(?:\.|/|$))", re.I)


def accept_url(raw: Optional[str], *, base_url: str, links: Dict[str, str]) -> Optional[str]:
    """Return the page's real href for ``raw`` if it is an actual link on the
    page (or the page URL itself); else None. URLs that only appear as prose
    are not accepted — that would widen the prompt-injection surface.
    Donation/transaction endpoints are rejected as portals.
    """
    resolved = resolve_url(raw or "", base_url)
    if resolved and _NON_PORTAL_PATH.search(urlparse(resolved).path):
        return None
    key = normalize_link(resolved)
    if not key:
        return None
    if key == normalize_link(base_url):
        return base_url
    return links.get(key)

"""Persisted opportunity identity (Catalog Batch C4).

Identity answers "is this the same funding opportunity?", not "do these URLs
look similar?". Every scholarship row stores:

  ``identity_key``           unique, indexed primary identity
  ``identity_fallback_key``  unique, nullable title+provider identity used to
                             survive provider URL migrations

Precedence (deterministic, conservative):
  1. Strong opportunity-specific canonical URL -> "u:<canon>"
  2. Normalized title + provider               -> "tp:<title>|<provider>"
  3. Any canonical URL (last resort; still stable)

A canonical URL is *weak* — never sufficient identity on its own — when it is
a bare homepage, a listing-grade path ("/scholarships"), or merely the page
the opportunity was listed on (portal == source). That last rule is what lets
C5 put multiple children from one listing page into distinct identities:
without an opportunity-specific URL, title+provider must distinguish them.

Identity deliberately excludes deadline year, award year, and extraction
timestamps: a recurring annual program keeps one row across cycles and C3
lifecycle owns the deadline transition.

False duplicates are inconvenient; false merges are data corruption. There is
no fuzzy matching anywhere in this module.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple
from urllib.parse import parse_qsl, quote, urlparse, urlunparse

from ..schema import _GENERIC_LISTING_TITLES

# Query parameter names that identify the underlying program/opportunity
# record. Allowlist only — evidenced in this repository by the real source
# URL health.ri.gov/programs/detail.php?pgm_id=141. Everything else (utm_*,
# fbclid/gclid, session ids, nav state like kheaa.com ?main=1) is stripped
# from identity rather than trusted to distinguish programs.
IDENTITY_QUERY_PARAMS = frozenset({
    "id",
    "pgm_id", "program_id", "programid",
    "scholarship_id", "scholarshipid",
    "fund_id", "fundid", "funding_id",
    "opportunity_id", "opportunityid", "opportunity", "opp_id",
    "award_id", "awardid",
    "grant_id", "grantid",
    "detail_id",
})

# A final path segment that by itself denotes a listing/index page rather
# than one specific opportunity. "/scholarships" is a directory;
# "/scholarships/nursing-award" is not.
LISTING_PATH_SEGMENTS = frozenset({
    "scholarships", "scholarship",
    "grants", "grant",
    "awards", "award",
    "financial-aid", "financialaid", "financial_aid",
    "opportunities", "funding", "programs", "apply", "aid",
})


def normalize_identity_text(value: str) -> str:
    """Normalize title/provider text for identity without fuzzy matching."""
    value = (value or "").casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def canonical_identity_url(value: str) -> str:
    """Return a stable canonical URL for identity comparisons.

    Normalizes scheme (always https — http/https is not identity), host case,
    a leading ``www.``, default ports, duplicate slashes, the trailing slash,
    and fragments. Query parameters are dropped EXCEPT the allowlisted
    identity parameters above, which are kept sorted so parameter order never
    changes identity. A URL that carries only non-allowlisted parameters
    canonicalizes identically to the bare path — unknown parameters are
    treated as non-identifying, and the resulting weaker identity is handled
    by ``compute_identity_keys``.
    """
    if not value:
        return ""
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port and port not in (80, 443):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    kept = sorted(
        (name.lower(), val.strip())
        for name, val in parse_qsl(parsed.query, keep_blank_values=True)
        if name.lower() in IDENTITY_QUERY_PARAMS and val.strip()
    )
    query = "&".join(f"{k}={quote(v, safe='')}" for k, v in kept)
    return urlunparse(("https", host, path, "", query, ""))


def _is_listing_path(path: str) -> bool:
    """True when a path is a bare root or ends in a generic listing segment."""
    segments = (path or "").strip("/")
    if not segments:
        return True  # bare homepage
    last = segments.split("/")[-1]
    last = re.sub(r"\.(html?|php|aspx?|cfm|jsp)$", "", last.lower())
    return last in LISTING_PATH_SEGMENTS


def is_weak_identity_url(canon_url: str, canon_source_url: str = "") -> bool:
    """True when a canonical URL cannot distinguish opportunities by itself.

    Weak = bare homepage, listing-grade path, or just the page the
    opportunity was discovered on (portal == source). A URL carrying
    allowlisted identity parameters is never weak — the parameter is the
    program's own identifier, even on a shared detail.php endpoint.
    """
    if not canon_url:
        return True
    parsed = urlparse(canon_url)
    if parsed.query:
        return False
    if canon_source_url and canon_url == canon_source_url:
        return True
    return _is_listing_path(parsed.path)


def title_provider_key(title: str, provider: str) -> Optional[str]:
    """Conservative normalized title+provider identity (no fuzzy matching).

    Generic listing headings are already rejected as titles by C1; they are
    excluded here too so they can never become a powerful fallback identity.
    """
    t = normalize_identity_text(title)
    p = normalize_identity_text(provider)
    if not t or not p or t in _GENERIC_LISTING_TITLES:
        return None
    return f"tp:{t}|{p}"


def compute_identity_keys(
    title: str,
    provider: str,
    portal_url: str,
    source_url: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (identity_key, identity_fallback_key) per the module docstring.

    The fallback key is populated alongside URL identities so a provider URL
    migration can still match on title+provider. When the primary key IS the
    title+provider key, the fallback is None.
    """
    canon = canonical_identity_url(portal_url)
    src_canon = canonical_identity_url(source_url or "")
    tp = title_provider_key(title, provider)
    if canon:
        # A URL that carried parameters but kept none is weak: the parameters
        # may have been program-identifying (we can't know), so the URL alone
        # must not collapse distinct programs onto one identity.
        raw_query = ""
        try:
            raw_query = urlparse(portal_url.strip()).query if portal_url else ""
        except ValueError:
            pass
        weak = is_weak_identity_url(canon, src_canon) or (
            bool(raw_query) and not urlparse(canon).query
        )
        if not weak:
            return f"u:{canon}", tp
    if tp:
        return tp, None
    if canon:
        return f"u:{canon}", None
    return None, None


def same_identity(
    existing,
    *,
    title: str,
    provider: str,
    portal_url: str,
    source_url: Optional[str] = None,
) -> bool:
    """True when ``existing`` shares any identity key with the given fields.

    Used only for the bounded compatibility scan of rows that predate the
    identity backfill (identity_key IS NULL); the normal path is indexed
    lookup on the persisted columns.
    """
    a_key, a_fb = compute_identity_keys(
        getattr(existing, "title", None), getattr(existing, "provider", None),
        getattr(existing, "portal_url", None), getattr(existing, "source_url", None),
    )
    b_key, b_fb = compute_identity_keys(title, provider, portal_url, source_url)
    return bool({k for k in (a_key, a_fb) if k} & {k for k in (b_key, b_fb) if k})

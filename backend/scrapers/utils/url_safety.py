"""Single definition of a safe opportunity URL and a safe URL replacement.

Used by both the ingestion runner's portal fallback and the dead-link repair
job so the two can never disagree about what counts as "opportunity-specific".

Rule (established, conservative, deterministic):
  * A reachable URL is not evidence of an opportunity. An organization's root
    homepage must never stand in for a dead application URL.
  * A replacement must have a path containing an opportunity term, and must be
    hosted on the same site (host without ``www.``) as one of the URLs it is
    replacing — otherwise it may belong to an unrelated organization.
"""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlparse

OPPORTUNITY_PATH_TERMS = (
    "scholarship",
    "grant",
    "fellowship",
    "financial-aid",
    "financial_aid",
    "financialaid",
    "award",
    "tuition",
    "education-fund",
    "loan-repayment",
)


def _host(url: str) -> str:
    netloc = urlparse((url or "").strip()).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def is_specific_opportunity_url(url: str) -> bool:
    """True only for URLs whose path looks like an opportunity/funding page."""
    if not url or not url.strip():
        return False
    parsed = urlparse(url.strip())
    path = (parsed.path or "").strip("/").lower()
    if not parsed.scheme or not parsed.netloc or not path:
        return False
    return any(term in path for term in OPPORTUNITY_PATH_TERMS)


def is_safe_replacement_url(candidate: str, originals: Iterable[str]) -> bool:
    """True when ``candidate`` may replace a dead opportunity URL.

    Requires an opportunity-specific path AND the same site as at least one of
    the original URLs (the dead portal URL and/or the record's source URL).
    """
    if not is_specific_opportunity_url(candidate):
        return False
    cand_host = _host(candidate)
    return bool(cand_host) and any(cand_host == _host(o) for o in originals if o)

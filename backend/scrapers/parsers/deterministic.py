"""Deterministic BeautifulSoup parsers for known structured scholarship portals.

Each parser is keyed by a host matcher (substring or regex). The registry
is consulted by :mod:`scrapers.runner` before falling back to the LLM parser.

Adding a new portal:
1. Implement a function with signature ``parse(html: str, url: str) -> ScholarshipExtract``.
2. Register it via ``@register_parser("hostname-substring")``.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

from ..schema import ScholarshipExtract
from ..utils.normalize import (
    clean_text,
    map_credentials,
    map_disciplines,
    parse_amount,
    parse_date,
    split_list,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ParserFn = Callable[[str, str], ScholarshipExtract]
_REGISTRY: List[Tuple[str, ParserFn]] = []


def register_parser(host_matcher: str) -> Callable[[ParserFn], ParserFn]:
    """Decorator to register a deterministic parser keyed by a host substring."""

    def decorator(fn: ParserFn) -> ParserFn:
        _REGISTRY.append((host_matcher.lower(), fn))
        return fn

    return decorator


def get_parser_for_url(url: str) -> Optional[ParserFn]:
    """Return the first registered parser whose host matcher is in the URL."""
    lower = url.lower()
    for matcher, fn in _REGISTRY:
        if matcher in lower:
            return fn
    return None


def all_parsers() -> Dict[str, ParserFn]:
    """Return a mapping of host matcher -> parser (for diagnostics/CLI)."""
    return {matcher: fn for matcher, fn in _REGISTRY}


# ---------------------------------------------------------------------------
# Shared extraction helpers
# ---------------------------------------------------------------------------


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _find_labelled(soup: BeautifulSoup, *labels: str) -> Optional[Tag]:
    """Find an element whose text starts with one of the given labels."""
    for label in labels:
        for el in soup.find_all(["dt", "th", "strong", "b", "span", "p", "li", "h2", "h3", "h4"]):
            text = clean_text(el.get_text())
            if text.lower().startswith(label.lower()):
                # Prefer a sibling dd/td or the same element's trailing text
                sibling = el.find_next_sibling(["dd", "td", "span", "p"])
                if sibling:
                    return sibling
                # Otherwise look for a colon-separated value in the same element
                if ":" in text:
                    return el
    return None


def _extract_labelled_text(soup: BeautifulSoup, *labels: str) -> str:
    el = _find_labelled(soup, *labels)
    if not el:
        return ""
    text = clean_text(el.get_text())
    if ":" in text:
        return clean_text(text.split(":", 1)[1])
    return text


def _extract_amount_from_text(soup: BeautifulSoup, *labels: str) -> Optional[int]:
    return parse_amount(_extract_labelled_text(soup, *labels))


def _extract_deadline_from_text(soup: BeautifulSoup, *labels: str) -> Optional[str]:
    raw = _extract_labelled_text(soup, *labels)
    d = parse_date(raw)
    return d.isoformat() if d else None


def _scrape_criteria_blob(soup: BeautifulSoup) -> str:
    """Concatenate likely eligibility/criteria sections into one blob."""
    blob_parts: List[str] = []
    for header in soup.find_all(["h2", "h3", "h4"]):
        h_text = clean_text(header.get_text()).lower()
        if any(k in h_text for k in ("eligib", "criteria", "requirement", "qualification")):
            # Collect following siblings until the next heading
            for sib in header.find_next_siblings():
                if sib.name in ("h2", "h3", "h4"):
                    break
                blob_parts.append(clean_text(sib.get_text()))
    return " ".join(blob_parts)


# ---------------------------------------------------------------------------
# Parser: APhA (American Pharmacists Association)
# ---------------------------------------------------------------------------


@register_parser("pharmacist.com")
def parse_apha(html: str, url: str) -> ScholarshipExtract:
    soup = _soup(html)

    title = clean_text(soup.select_one("h1, .field--name-title, .page-title").get_text() if soup.select_one("h1, .field--name-title, .page-title") else "")
    if not title:
        title_tag = soup.find(["h1", "h2"])
        title = clean_text(title_tag.get_text()) if title_tag else ""

    provider = "American Pharmacists Association"

    amount = _extract_amount_from_text(soup, "Award", "Amount", "Stipend", "Scholarship Amount")
    deadline = _extract_deadline_from_text(soup, "Deadline", "Application Deadline", "Due Date")

    criteria_blob = _scrape_criteria_blob(soup) + " " + clean_text(soup.get_text())
    disciplines = map_disciplines(criteria_blob) or ["pharmacy"]
    credentials = map_credentials(criteria_blob)

    return ScholarshipExtract(
        title=title or "APhA Scholarship",
        provider=provider,
        portal_url=url,
        award_amount=amount,
        deadline=deadline,
        eligible_disciplines=disciplines,
        eligible_credentials=credentials,
        matching_tags=["apha", "pharmacy"],
        source="deterministic",
    )


# ---------------------------------------------------------------------------
# Parser: AACN (American Association of Colleges of Nursing)
# ---------------------------------------------------------------------------


@register_parser("aacnnursing.org")
def parse_aacn(html: str, url: str) -> ScholarshipExtract:
    soup = _soup(html)

    title_tag = soup.find(["h1", "h2"])
    title = clean_text(title_tag.get_text()) if title_tag else ""

    provider = "American Association of Colleges of Nursing"

    amount = _extract_amount_from_text(soup, "Award", "Amount", "Funding")
    deadline = _extract_deadline_from_text(soup, "Deadline", "Application Deadline")

    criteria_blob = _scrape_criteria_blob(soup) + " " + clean_text(soup.get_text())
    disciplines = map_disciplines(criteria_blob) or ["nursing"]
    credentials = map_credentials(criteria_blob)

    return ScholarshipExtract(
        title=title or "AACN Scholarship",
        provider=provider,
        portal_url=url,
        award_amount=amount,
        deadline=deadline,
        eligible_disciplines=disciplines,
        eligible_credentials=credentials,
        matching_tags=["aacn", "nursing"],
        source="deterministic",
    )


# ---------------------------------------------------------------------------
# Parser: Generic state higher-ed board pages
# ---------------------------------------------------------------------------


_STATE_BOARD_RE = re.compile(r"(higher|board|regents|education|scholarship)", re.IGNORECASE)


@register_parser(".gov")
def parse_state_board(html: str, url: str) -> ScholarshipExtract:
    soup = _soup(html)

    title_tag = soup.find(["h1", "h2"])
    title = clean_text(title_tag.get_text()) if title_tag else ""

    # Provider: best-effort from <title> or org name meta
    provider = ""
    org_meta = soup.find("meta", attrs={"name": re.compile("org|publisher", re.I)})
    if org_meta and org_meta.get("content"):
        provider = clean_text(org_meta["content"])
    if not provider:
        page_title = soup.title.get_text() if soup.title else ""
        provider = clean_text(page_title.split("|")[0].split("-")[0]) if page_title else "State Higher Education Board"

    amount = _extract_amount_from_text(soup, "Award", "Amount", "Maximum Award", "Scholarship Value")
    deadline = _extract_deadline_from_text(soup, "Deadline", "Application Deadline", "Apply By")

    criteria_blob = _scrape_criteria_blob(soup)
    disciplines = map_disciplines(criteria_blob)
    credentials = map_credentials(criteria_blob)

    # State restriction: try to infer from URL or provider
    state_restrictions: List[str] = []
    state_match = re.search(r"/([a-z]{2})\.", url.lower())
    if state_match:
        state_restrictions = [state_match.group(1).upper()]

    return ScholarshipExtract(
        title=title or "State Scholarship",
        provider=provider,
        portal_url=url,
        award_amount=amount,
        deadline=deadline,
        eligible_disciplines=disciplines,
        eligible_credentials=credentials,
        state_restrictions=state_restrictions,
        matching_tags=["state", "higher-ed"],
        source="deterministic",
    )


# ---------------------------------------------------------------------------
# Parser: Generic structured article fallback (best-effort)
# ---------------------------------------------------------------------------


@register_parser("scholarship")
def parse_generic_scholarship(html: str, url: str) -> ScholarshipExtract:
    """Best-effort parser for pages whose URL contains 'scholarship'.

    Looks for common microdata/label patterns. Intentionally conservative;
    incomplete extractions will trigger the LLM fallback in the runner.
    """
    soup = _soup(html)

    title_tag = soup.find(["h1", "h2"])
    title = clean_text(title_tag.get_text()) if title_tag else ""

    provider = ""
    provider_tag = soup.find(attrs={"class": re.compile("provider|sponsor|organization", re.I)})
    if provider_tag:
        provider = clean_text(provider_tag.get_text())

    amount = _extract_amount_from_text(soup, "Award", "Amount", "Value", "Prize")
    deadline = _extract_deadline_from_text(soup, "Deadline", "Due", "Closes")

    criteria_blob = _scrape_criteria_blob(soup) + " " + clean_text(soup.get_text())
    disciplines = map_disciplines(criteria_blob)
    credentials = map_credentials(criteria_blob)

    return ScholarshipExtract(
        title=title,
        provider=provider,
        portal_url=url,
        award_amount=amount,
        deadline=deadline,
        eligible_disciplines=disciplines,
        eligible_credentials=credentials,
        matching_tags=split_list(_extract_labelled_text(soup, "Tags", "Categories")),
        source="deterministic",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_with_deterministic(html: str, url: str) -> Optional[ScholarshipExtract]:
    """Run the matching deterministic parser, or None if no match."""
    fn = get_parser_for_url(url)
    if not fn:
        return None
    try:
        return fn(html, url)
    except Exception as exc:  # noqa: BLE001
        logger.error("Deterministic parser %s failed for %s: %s", fn.__name__, url, exc)
        return None

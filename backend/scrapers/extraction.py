"""Page-level extraction: one page -> zero, one, or many opportunities (C5).

Pipeline for one fetched page:

  classify_page            deterministic: single_opportunity | listing |
                           unknown | irrelevant
  irrelevant               -> zero opportunities, no LLM call
  single_opportunity       -> deterministic parser when it yields a complete
                              record, otherwise LLM (list contract)
  listing / unknown        -> LLM list extraction (deterministic single-record
                              parsers are never allowed to swallow a listing)
  per child (isolated)     -> title guards, URL acceptance against the page's
                              real links, shared-URL demotion, bounded detail
                              fetch, deadline-year guard, scoped evidence,
                              independent verification

Trust boundary (unchanged from C2): extract -> independent evidence
verification -> persistence. The LLM is an extractor only; its output is
post-validated deterministically here.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import llm_parser
from .parsers import deterministic
from .schema import ScholarshipExtract, TrackExtract, _GENERIC_LISTING_TITLES
from .utils.identity import normalize_identity_text
from .utils.normalize import clean_text, map_credentials, map_disciplines
from .utils.page_links import CHROME_TAGS, accept_url, link_index, normalize_link
from .utils.taxonomy import ANY_FIELD, funding_type_from_program_title
from .verification import html_to_text, verify_extract_against_text

logger = logging.getLogger(__name__)

PAGE_SINGLE = "single_opportunity"
PAGE_LISTING = "listing"
PAGE_UNKNOWN = "unknown"
PAGE_IRRELEVANT = "irrelevant"
PAGE_KINDS = (PAGE_SINGLE, PAGE_LISTING, PAGE_UNKNOWN, PAGE_IRRELEVANT)


# ---------------------------------------------------------------------------
# Limits (cost safety)
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


@dataclass(frozen=True)
class ExtractionLimits:
    """Per-page bounds. Defaults are conservative for GitHub-Actions-scale runs:
    25 children covers typical foundation/university directories in one call;
    10 detail fetches caps per-listing fan-out (listing -> detail only, never
    recursive)."""

    max_opportunities_per_page: int = 25
    max_detail_fetches_per_page: int = 10
    detail_fetch_enabled: bool = True
    max_segment_chars: int = 2000
    # Large-page (chunked) extraction bounds (E2.5): a listing page whose
    # text exceeds the single-call prompt window is split into structural
    # chunks — capped count, capped size, one LLM call per chunk.
    chunk_max_chars: int = 18000
    max_chunks_per_page: int = 5

    @classmethod
    def from_env(cls) -> "ExtractionLimits":
        return cls(
            max_opportunities_per_page=max(1, _env_int("C5_MAX_OPPORTUNITIES_PER_PAGE", 25)),
            max_detail_fetches_per_page=_env_int("C5_MAX_DETAIL_FETCHES_PER_PAGE", 10),
            detail_fetch_enabled=os.getenv("C5_DETAIL_FETCH_ENABLED", "true").strip().lower()
            in ("1", "true", "yes"),
            chunk_max_chars=max(1000, _env_int("C5_CHUNK_MAX_CHARS", 18000)),
            max_chunks_per_page=max(1, _env_int("C5_MAX_CHUNKS_PER_PAGE", 5)),
        )


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------

_FUNDING_TERM = re.compile(
    r"\b(scholarships?|grants?|fellowships?|awards?|bursar(?:y|ies)|tuition|"
    r"loan repayment|loan forgiveness|financial aid|stipends?)\b", re.I)
# A named opportunity item: a short label containing an opportunity noun.
_NAMED_ITEM = re.compile(
    r"\b(scholarships?|grants?|fellowships?|awards?|funds?|prizes?|stipends?|"
    r"loan repayment|bursar(?:y|ies))\b", re.I)
_NAV_PREFIX = re.compile(
    r"^(apply|learn more|read more|view|see all|click|more info|details|home|"
    r"contact|donate|back|browse|search)\b", re.I)
# Section headings inside ONE opportunity page ("Award Amount", "Eligibility
# Requirements") are not separate opportunities.
_SECTION_WORDS = re.compile(
    r"\b(eligib\w*|criteria|requirements?|amounts?|deadlines?|details|information|"
    r"how to|faq|overview|process|recipients?|winners?|history|about|contact|"
    r"applications?|instructions|guidelines|timeline|dates?|selection|renewal|"
    r"terms|policy|policies|questions)\b", re.I)
_AMOUNT = re.compile(r"\$\s?\d")
_DEADLINE_WORD = re.compile(r"\b(deadline|due|closes|apply by)\b", re.I)


@dataclass
class PageClassification:
    kind: str
    items: List[str] = field(default_factory=list)
    signals: Dict[str, int] = field(default_factory=dict)


_LABEL_TAGS = ["h2", "h3", "h4", "h5", "h6", "dt", "a", "strong", "b", "td", "th", "li"]
_HEADING_CLASS = re.compile(r"(heading|title)", re.I)


def _is_heading_like(el) -> bool:
    """Page builders (Kadence, Elementor, Divi, …) often render card titles as
    <p>/<div>/<span> with a heading/title class or role="heading" instead of
    an <hN> tag. Treat those as labels too (C6.5 calibration finding)."""
    if el.name not in ("p", "div", "span"):
        return False
    if (el.get("role") or "").lower() == "heading":
        return True
    return any(_HEADING_CLASS.search(c) for c in (el.get("class") or []))


def _content_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "template", *CHROME_TAGS]):
        tag.decompose()
    return soup


def classify_page(html: str, url: str = "") -> PageClassification:
    """Conservatively classify a page by structure, not by keyword presence.

    Counts distinct short *named* opportunity labels (headings, links,
    definition terms, table cells, list items) in the main content — page
    chrome, generic listing headings, navigation phrases and in-page section
    headings excluded. The word "scholarships" alone never makes a listing.
    """
    soup = _content_soup(html)
    text = clean_text(soup.get_text(" "))
    if not _FUNDING_TERM.search(text):
        return PageClassification(PAGE_IRRELEVANT)

    items: Dict[str, str] = {}
    for el in soup.find_all(lambda t: t.name in _LABEL_TAGS or _is_heading_like(t)):
        label = clean_text(el.get_text(" "))
        words = label.split()
        if not 2 <= len(words) <= 12:
            continue
        if _NAV_PREFIX.match(label) or _SECTION_WORDS.search(label) or not _NAMED_ITEM.search(label):
            continue
        key = normalize_identity_text(label)
        if key and key not in _GENERIC_LISTING_TITLES:
            items.setdefault(key, label)

    signals = {
        "named_items": len(items),
        "amounts": len(_AMOUNT.findall(text)),
        "deadline_mentions": len(_DEADLINE_WORD.findall(text)),
    }
    n = len(items)
    repeated_facts = signals["amounts"] >= 2 or signals["deadline_mentions"] >= 2
    if n >= 3 or (n == 2 and repeated_facts):
        kind = PAGE_LISTING
    elif n == 2:
        kind = PAGE_UNKNOWN
    else:
        kind = PAGE_SINGLE
    return PageClassification(kind, list(items.values()), signals)


# ---------------------------------------------------------------------------
# Evidence scoping
# ---------------------------------------------------------------------------


def _title_pattern(title: str) -> Optional[re.Pattern]:
    tokens = re.findall(r"[a-z0-9]+", (title or "").casefold())
    if not tokens:
        return None
    body = r"[^a-z0-9]+".join(re.escape(t) for t in tokens)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.I)


def title_on_page(title: str, text: str) -> bool:
    p = _title_pattern(title)
    return bool(p and p.search(text or ""))


def evidence_windows(text: str, titles: List[str], *, max_segment: int = 2000) -> List[str]:
    """Split page text into per-title evidence.

    Each occurrence of a title starts a segment that ends at the next
    occurrence of ANY title (capped at ``max_segment``). A title's evidence is
    the union of its segments, so a table-of-contents mention plus the body
    section both count, while a sibling's section never does. Overlapping
    matches prefer the longer title ("Alpha Scholarship II" is not "Alpha
    Scholarship").
    """
    matches: List[Tuple[int, int, int]] = []
    for i, t in enumerate(titles):
        p = _title_pattern(t)
        if p:
            matches += [(m.start(), m.end(), i) for m in p.finditer(text)]
    matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))
    kept: List[Tuple[int, int, int]] = []
    last_end = -1
    for m in matches:
        if m[0] >= last_end:
            kept.append(m)
            last_end = m[1]
    windows: List[List[str]] = [[] for _ in titles]
    for k, (start, _end, i) in enumerate(kept):
        stop = kept[k + 1][0] if k + 1 < len(kept) else len(text)
        windows[i].append(text[start:min(stop, start + max_segment)])
    return [" ".join(w) for w in windows]


def _deadline_year_supported(deadline: Optional[str], text: str) -> Optional[str]:
    """Drop a deadline whose year never appears in the evidence (an inferred
    year — C1 forbids it). Invalid dates also become None."""
    if not deadline:
        return None
    try:
        d = date.fromisoformat(deadline)
    except ValueError:
        return None
    year = str(d.year)
    if re.search(rf"(?<!\d){year}(?!\d)", text) or re.search(rf"[/-]{year[2:]}(?!\d)", text):
        return deadline
    return None


# A provider that is a bare funding/nav noun is a parse garble, not an
# organization ("Loan", "Scholarship", "Homepage").
_GENERIC_PROVIDER = re.compile(
    r"^(loans?|scholarships?|grants?|awards?|funds?|programs?|education|"
    r"homepages?|home|students?)\.?$", re.I)
# A record title that names an opportunity normally carries a funding noun.
# A bare org/section heading ("Iowa Department of Education") does not.
_OPPORTUNITY_NOUN = re.compile(
    r"\b(scholarships?|scholars?|grants?|fellowships?|awards?|funds?|prizes?|"
    r"stipends?|bursar(?:y|ies)|loans?|forgiveness|repayment|forgivable|"
    r"tuition|assistance|internships?|programs?|initiatives?)\b", re.I)
# Evidence language that establishes "any field" — required before ['any']
# disciplines can stay verified (unknown must never become unrestricted).
# "all fields of pharmacy" is a subtree restriction, NOT unrestricted: the
# lookahead rejects "of <field>" while preserving "all fields of study".
_ANY_FIELD_EVIDENCE = re.compile(
    r"\b(any|all|every|each|whatever)\s+(accredited\s+)?(field|fields|major|majors|"
    r"discipline|disciplines|degree|degrees)\b(?!\s+of\s+(?!study\b))|"
    r"\b(any|all|every|each|whatever)\s+(accredited\s+)?(program of study|"
    r"course of study|area of study|areas of study)\b|"
    r"\b(regardless of|irrespective of|open to)\s+.{0,25}?(major|field|discipline)s?\b"
    r"(?!\s+of\s+(?!study\b))|"
    # Label:value listing format — "Field: Any", "Major: All" declares the
    # same unrestricted fact. "any of the following" is excluded by the
    # lookahead (a following list is a restriction, not unrestricted).
    r"\b(fields?|majors?|disciplines?)\s*(?:of study)?\s*:\s*(?:any|all)\b"
    r"(?!\s+of)",
    re.I)

# "all fields of pharmacy" / "all pharmacy fields" / "any major in nursing"
# declare a subtree scope — normalize the claim to that field, never "any".
_FIELD_SCOPE_PATTERNS = [
    re.compile(
        r"\b(?:any|all|every|each)\s+(?:accredited\s+)?fields?\s+of\s+"
        r"([a-z][a-z/&\- ]{2,40})", re.I),
    re.compile(
        r"\b(?:any|all|every|each)\s+(?:accredited\s+)?"
        r"([a-z][a-z/&\- ]{2,40}?)\s+fields?\b", re.I),
    re.compile(
        r"\b(?:any|all|every|each)\s+(?:accredited\s+)?"
        r"(?:major|majors|discipline|disciplines)\s+in\s+"
        r"([a-z][a-z/&\- ]{2,40})", re.I),
]


def _field_scope_in_text(text: str) -> Optional[str]:
    """A phrase like "all fields of pharmacy" restricts scope to that field.

    Returns the single canonical field code the phrase names, or None when
    the qualifier isn't a recognized field ("all fields of study" is a
    genuinely-unrestricted claim, handled by ``_ANY_FIELD_EVIDENCE``)."""
    for pat in _FIELD_SCOPE_PATTERNS:
        match = pat.search(text or "")
        if not match:
            continue
        found = map_disciplines(match.group(1))
        if len(found) == 1:
            return found[0]
    return None


def narrow_disciplines_to_evidence(
    disciplines: List[str],
    text: str,
    source_discipline: Optional[str] = None,
) -> List[str]:
    """Narrow a broad area-code claim to a curated, more specific field.

    An extractor that emits a top-level area (``social_sciences``) for a
    program the curated source itself declares more precisely
    (``primary_discipline="social_work"``) has over-asserted eligibility
    breadth — the same over-claim class as an unsupported 'any'.

    The rewrite is conservative and two-gated (Q1 / E3 NASW finding,
    provider-agnostic):

      1. The source must declare a canonical field that is a strict
         descendant of the claimed area — curated metadata is what proposes
         the narrower code, never page-text pattern matching (a partial
         matcher cannot see every field and would under-cover genuinely
         broad programs).
      2. The record's own evidence may VETO but never cause the narrowing:
         when the evidence names other descendants of the same area, the
         broad claim is genuinely supported (e.g. a STEM award on an
         engineering association's page) and is kept.

    The claim is never dropped wholesale and never rewritten outside the
    claimed subtree.
    """
    from .utils.taxonomy import FIELD_OF_STUDY, _AREA_CHILDREN

    claims = [str(d) for d in (disciplines or [])]
    if not claims or claims == [ANY_FIELD]:
        return list(claims)
    areas = set(_AREA_CHILDREN)
    if not any(c in areas for c in claims) or not source_discipline:
        return list(claims)
    candidate = str(source_discipline)
    if candidate not in FIELD_OF_STUDY or candidate in areas or candidate in claims:
        return list(claims)
    found = set(map_disciplines(text or ""))
    out: List[str] = []
    for c in claims:
        if c not in areas:
            out.append(c)
            continue
        is_descendant = FIELD_OF_STUDY.get(candidate, (None, ""))[0] == c
        other_descendants = [
            f for f in found
            if f != candidate and FIELD_OF_STUDY.get(f, (None, ""))[0] == c]
        if is_descendant and not other_descendants:
            out.append(candidate)
        else:
            out.append(c)
    return list(dict.fromkeys(out))


# A fund-shaped title ("X Fund", "Y Endowment", "Z Memorial Fund") names a
# philanthropic account, not necessarily an applicant-facing education
# benefit. The record's own evidence text must establish education funding
# (E2.5 community-foundation rule). Bare "grant"/"award" alone is not
# enough — charitable-grant funds exist; an education term must appear.
_FUND_ACCOUNT_TITLE = re.compile(
    r"\b(funds?|endowments?|trusts?|memorials?|donor advised)\b", re.I)
_EDU_FUNDING_TERM = re.compile(
    r"\b(scholarships?|scholars?|fellowships?|tuition|stipends?|students?|"
    r"education|educational|college|university|universities|school|"
    r"degree|academic|classroom|teachers?|scholastic)\b", re.I)


def _structural_review_flags(ex: ScholarshipExtract, text: str) -> bool:
    """Deterministic sanity checks on records that otherwise pass evidence
    verification (E2 findings). A flag means needs_review, never rejection."""
    if not _OPPORTUNITY_NOUN.search(ex.title or ""):
        return True
    if _GENERIC_PROVIDER.match((ex.provider or "").strip()):
        return True
    if (ex.eligible_disciplines or []) == ["any"] and not _ANY_FIELD_EVIDENCE.search(text or ""):
        return True
    if _FUND_ACCOUNT_TITLE.search(ex.title or "") and not _EDU_FUNDING_TERM.search(text or ""):
        return True
    return False


def attach_verification(extract: ScholarshipExtract, *, text: str, source_url: str) -> ScholarshipExtract:
    """Attach independent evidence verification (never from the extractor)."""
    # "all fields of pharmacy" asserts a subtree, not global 'any' — rewrite
    # the claim to the scoped field before verification (E2.5).
    if (extract.eligible_disciplines or []) == [ANY_FIELD]:
        scoped = _field_scope_in_text(text)
        if scoped:
            object.__setattr__(extract, "eligible_disciplines", [scoped])
    result = verify_extract_against_text(extract, text)
    extract.source_url = source_url
    status = result["status"]
    if status == "verified" and _structural_review_flags(extract, text):
        status = "needs_review"
    object.__setattr__(extract, "verification_status", status)
    object.__setattr__(extract, "verified_fields", result["fields"])
    object.__setattr__(extract, "verified_at", datetime.utcnow() if status == "verified" else None)
    return extract


def _apply_title_funding_terms(ex: ScholarshipExtract) -> None:
    """Explicit loan-forgiveness-family terms (E1.5) or the official title's
    own instrument head noun (E4.6: "... Scholarship/Grant/Fellowship")
    establish ``funding_type``; anything else leaves NULL alone. An explicit
    extracted funding type always wins."""
    if ex.funding_type is None:
        ex.funding_type = funding_type_from_program_title(ex.title)


# ---------------------------------------------------------------------------
# Program-directory track mode (E1.5)
# ---------------------------------------------------------------------------

# A heading that explicitly announces program variants: "Eligible Professions
# and Guidelines", "Program Tracks", etc. Deliberately narrow — "Programs"
# alone is a listing of separate opportunities, not tracks.
_TRACK_HEADING = re.compile(r"\b(professions?|guidelines?|tracks?|variants?)\b", re.I)
_TRACK_LINK_MAX = 30


def _h1_text(html: str) -> str:
    soup = _content_soup(html)
    h = soup.find("h1")
    return clean_text(h.get_text(" ")) if h else ""


def _program_track_links(html: str, url: str) -> List[Tuple[str, str]]:
    """Detect an authoritative track directory on the page.

    Returns ``(verbatim link text, absolute URL)`` pairs found under a
    track-announcing heading, restricted to same-directory detail links so
    chrome/navigation never qualifies. Empty unless at least two links sit
    under one such heading — a single link is not a directory.
    """
    soup = _content_soup(html)
    page_dir = url.split("#")[0].rsplit("/", 1)[0] + "/"
    page_self = url.split("#")[0]
    found: List[Tuple[str, str]] = []
    for h in soup.find_all(["h2", "h3", "h4", "h5", "strong", "b", "p"]):
        if not _TRACK_HEADING.search(clean_text(h.get_text(" "))):
            continue
        container = next(
            (s for s in h.find_next_siblings() if getattr(s, "find_all", None)),
            None) or h.parent
        anchors = container.find_all("a") if container else []
        candidates: List[Tuple[str, str]] = []
        for a in anchors:
            text = clean_text(a.get_text(" "))
            href = (a.get("href") or "").strip()
            if not text or not href or href.startswith("#") or not re.search(r"[a-zA-Z]", text):
                continue
            absu = urljoin(url, href).split("#")[0]
            if not absu.startswith(page_dir) or absu == page_self:
                continue
            words = text.split()
            if not 2 <= len(words) <= 12 or _NAV_PREFIX.match(text):
                continue
            candidates.append((text, absu))
        if len(candidates) >= 2:
            found.extend(candidates)
    out: List[Tuple[str, str]] = []
    seen = set()
    for text, absu in found:
        key = normalize_identity_text(text)
        if key and key not in seen and key not in _GENERIC_LISTING_TITLES:
            seen.add(key)
            out.append((text, absu))
    return out[:_TRACK_LINK_MAX]


async def _extract_program_directory(
    page: PageExtraction,
    html: str,
    url: str,
    page_text: str,
    provider_hint: str,
    dir_links: List[Tuple[str, str]],
) -> PageExtraction:
    """One parent program + authoritative tracks — never N opportunities.

    Track identity comes verbatim from the page's own link text; the LLM is
    used only to enrich the *parent* and can never name a track. Parent
    title is evidence-bound: the LLM title must appear on the page, else the
    authoritative h1 is used, else the page is rejected.
    """
    h1 = _h1_text(html)
    result = await llm_parser.extract_opportunities_with_llm(
        html, url, mode="single_opportunity")
    page.method = "llm" if result else "deterministic"
    ex = result.extracts[0] if result and result.extracts else None
    if ex is None:
        if not h1:
            page.rejected.append(("", "directory_parent_no_title"))
            return page
        ex = ScholarshipExtract(title=h1, provider=provider_hint or "",
                                portal_url=url, source="deterministic")
    if not title_on_page(ex.title or "", page_text):
        if h1 and title_on_page(h1, page_text):
            ex.title = h1
        else:
            page.rejected.append((ex.title or "", "directory_parent_title_not_on_page"))
            return page
    if not ex.is_critical_complete():
        page.rejected.append((ex.title or "", "generic_or_empty_title"))
        return page
    if not ex.provider:
        ex.provider = provider_hint
    if not ex.portal_url:
        ex.portal_url = url

    tracks: List[TrackExtract] = []
    for text, href in dir_links:
        tracks.append(TrackExtract(
            title=text,
            detail_url=href,
            eligible_disciplines=map_disciplines(text),
            eligible_credentials=map_credentials(text),
        ))
    ex.tracks = tracks
    # Parent eligibility covers every authoritative track field — the union
    # is evidence (each code came from a real link label), not a guess.
    if not ex.eligible_disciplines:
        ex.eligible_disciplines = sorted(
            {d for t in tracks for d in t.eligible_disciplines})

    _apply_title_funding_terms(ex)
    ex.deadline = _deadline_year_supported(ex.deadline, page_text)
    page.extracts.append(attach_verification(ex, text=page_text, source_url=url))
    return page


# ---------------------------------------------------------------------------
# Page extraction
# ---------------------------------------------------------------------------


@dataclass
class PageExtraction:
    url: str
    kind: str
    method: Optional[str] = None  # "deterministic" | "llm" | None
    extracts: List[ScholarshipExtract] = field(default_factory=list)
    rejected: List[Tuple[str, str]] = field(default_factory=list)
    urls_rejected: int = 0
    detail_attempted: int = 0
    detail_succeeded: int = 0
    detail_failed: int = 0
    error: Optional[str] = None
    chunked: bool = False                 # page was split for extraction (E2.5)
    chunk_stats: Dict[str, object] = field(default_factory=dict)

    @property
    def is_multi(self) -> bool:
        return self.kind in (PAGE_LISTING, PAGE_UNKNOWN) or len(self.extracts) > 1


@dataclass
class ExtractionStats:
    """Aggregated observability for a run (logged / returned in summaries)."""

    pages_single: int = 0
    pages_listing: int = 0
    pages_unknown: int = 0
    pages_irrelevant: int = 0
    opportunities_extracted: int = 0
    opportunities_rejected: int = 0
    urls_rejected: int = 0
    detail_fetch_attempted: int = 0
    detail_fetch_succeeded: int = 0
    detail_fetch_failed: int = 0
    extraction_errors: int = 0
    pages_chunked: int = 0
    chunks_planned: int = 0
    chunks_processed: int = 0
    chunk_llm_calls: int = 0
    chunk_failures: int = 0
    cross_chunk_duplicates: int = 0

    def add(self, page: PageExtraction) -> None:
        attr = {PAGE_SINGLE: "pages_single", PAGE_LISTING: "pages_listing",
                PAGE_UNKNOWN: "pages_unknown", PAGE_IRRELEVANT: "pages_irrelevant"}[page.kind]
        setattr(self, attr, getattr(self, attr) + 1)
        self.opportunities_extracted += len(page.extracts)
        self.opportunities_rejected += len(page.rejected)
        self.urls_rejected += page.urls_rejected
        self.detail_fetch_attempted += page.detail_attempted
        self.detail_fetch_succeeded += page.detail_succeeded
        self.detail_fetch_failed += page.detail_failed
        self.extraction_errors += 1 if page.error else 0
        if page.chunked:
            stats = page.chunk_stats or {}
            self.pages_chunked += 1
            self.chunks_planned += int(stats.get("chunks_planned", 0))
            self.chunks_processed += int(stats.get("chunks", 0))
            self.chunk_llm_calls += int(stats.get("calls", 0))
            self.chunk_failures += int(stats.get("failed_chunks", 0))
            self.cross_chunk_duplicates += int(stats.get("cross_chunk_duplicates", 0))

    def summary(self) -> dict:
        return dict(self.__dict__)


FetchFn = Callable[[str], Awaitable[Optional[str]]]


# ---------------------------------------------------------------------------
# Large-page chunked extraction (E2.5)
# ---------------------------------------------------------------------------

# Blocks that stay whole (a <ul> of scholarships is one unit); containers
# recurse so a deeply nested page still splits at real boundaries.
_CHUNK_LEAF_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table", "dl",
    "blockquote", "pre", "figure",
}
_CHUNK_CONTAINER_TAGS = {
    "body", "div", "section", "article", "main", "header", "footer",
    "aside", "form", "nav",
}
_CHUNK_BOUNDARY_TAGS = {"h1", "h2", "h3"}


def _content_blocks(root) -> List:
    """Flatten the content DOM into an ordered stream of standalone blocks:
    leaf blocks pass through intact, containers are unwrapped."""
    out: List = []

    def walk(el) -> None:
        for child in getattr(el, "children", None) or []:
            name = getattr(child, "name", None)
            if name is None:
                if str(child).strip():
                    out.append(child)
                continue
            if name in _CHUNK_LEAF_TAGS:
                out.append(child)
            elif name in _CHUNK_CONTAINER_TAGS:
                walk(child)
            else:
                out.append(child)

    walk(root)
    return out


def _piece_len(piece: str) -> int:
    return len(clean_text(BeautifulSoup(piece, "html.parser").get_text(" ")))


def _split_item_block(block, max_chars: int) -> List[Tuple[str, int]]:
    """Split one oversized list/table/definition-list at ITEM boundaries.

    Items are never cut mid-way (a <li>, a <tr>, or a <dt> with its <dd>s
    stays whole); consecutive items are regrouped under the same wrapper tag
    up to ``max_chars``. Non-item blocks are returned unchanged."""
    name = getattr(block, "name", None)
    if name in ("ul", "ol"):
        items = [str(li) for li in block.find_all("li", recursive=False)]
    elif name == "table":
        items = [str(tr) for tr in block.find_all("tr")]
    elif name == "dl":
        items, cur = [], ""
        for child in block.children:
            cname = getattr(child, "name", None)
            if cname == "dt" and cur:
                items.append(cur)
                cur = ""
            if cname in ("dt", "dd"):
                cur += str(child)
        if cur:
            items.append(cur)
    else:
        items = []
    if len(items) < 2:
        text = str(block)
        return [(text, _piece_len(text))]
    groups: List[Tuple[str, int]] = []
    cur_items: List[str] = []
    cur_len = 0
    for item in items:
        n = _piece_len(item)
        if cur_items and cur_len + n > max_chars:
            groups.append((f"<{name}>{''.join(cur_items)}</{name}>", cur_len))
            cur_items, cur_len = [], 0
        cur_items.append(item)
        cur_len += n
    if cur_items:
        groups.append((f"<{name}>{''.join(cur_items)}</{name}>", cur_len))
    return groups


def _listing_chunk_fragments(
    html: str,
    *,
    max_chars: int,
    max_chunks: int,
) -> Tuple[List[str], int]:
    """Split a large listing page into structural chunk fragments.

    Boundaries are heading elements (h1–h3); each fragment keeps the page's
    h1 as provider context and preserves its own <a> elements so URL
    acceptance still works per chunk. A heading section larger than
    ``max_chars`` is subdivided at block boundaries (its heading repeated as
    context), and a single list/table/definition list larger than
    ``max_chars`` at item boundaries (E4.5) — so no chunk silently exceeds
    the bound and gets truncated by the prompt window. Returns (fragments,
    chunks_planned) — chunks beyond ``max_chunks`` are dropped (fail-safe cap).
    """
    soup = _content_soup(html)
    h1 = soup.find("h1")
    h1_html = str(h1) if h1 else ""
    body = soup.body or soup

    sections: List[List[Tuple[object, str, int]]] = []
    current: List[Tuple[object, str, int]] = []
    for block in _content_blocks(body):
        piece = block if isinstance(block, str) else str(block)
        n = _piece_len(piece)
        if not n:
            continue
        if getattr(block, "name", None) in _CHUNK_BOUNDARY_TAGS and current:
            sections.append(current)
            current = []
        current.append((block, piece, n))
    if current:
        sections.append(current)

    units: List[Tuple[str, int]] = []
    for sec in sections:
        sec_len = sum(n for _, _, n in sec)
        if sec_len <= max_chars:
            units.append(("".join(p for _, p, _ in sec), sec_len))
            continue
        first = sec[0]
        heading = first[1] if getattr(first[0], "name", None) in _CHUNK_BOUNDARY_TAGS else ""
        heading_len = first[2] if heading else 0
        for idx, (block, piece, n) in enumerate(sec):
            if heading and idx == 0:
                continue
            parts = _split_item_block(block, max(1, max_chars - heading_len)) \
                if n > max_chars - heading_len and not isinstance(block, str) else [(piece, n)]
            for text, tlen in parts:
                units.append((heading + text, heading_len + tlen))

    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for seg, seg_len in units:
        if cur and cur_len + seg_len > max_chars:
            chunks.append("".join(cur))
            cur, cur_len = [], 0
        cur.append(seg)
        cur_len += seg_len
    if cur:
        chunks.append("".join(cur))

    planned = len(chunks)
    out = []
    for ch in chunks[:max_chunks]:
        out.append(ch if h1_html and h1_html in ch else h1_html + ch)
    return out, planned


async def _extract_listing_chunked(
    page: PageExtraction,
    html: str,
    url: str,
    *,
    max_items: int,
    limits: ExtractionLimits,
) -> Optional[llm_parser.LLMExtraction]:
    """Bounded chunked extraction for a page too large for one call.

    Each chunk is untrusted evidence extracted independently; the merged
    result flows through the same per-child validation as a single call.
    Cross-chunk duplicates collapse on normalized (title, provider). All
    chunks failing -> None (page-level extraction failure)."""
    fragments, planned = _listing_chunk_fragments(
        html, max_chars=limits.chunk_max_chars,
        max_chunks=limits.max_chunks_per_page)
    stats: Dict[str, object] = {
        "chunks": len(fragments), "chunks_planned": planned, "calls": 0,
        "failed_chunks": 0, "items_per_chunk": [], "cross_chunk_duplicates": 0,
    }
    merged = llm_parser.LLMExtraction()
    seen = set()
    for frag in fragments:
        if stats["calls"] >= limits.max_chunks_per_page:
            break  # one LLM call per chunk; chunk cap == call cap
        stats["calls"] += 1
        res = await llm_parser.extract_opportunities_with_llm(
            frag, url, mode=PAGE_LISTING, max_items=max_items)
        if res is None:
            stats["failed_chunks"] += 1
            continue
        merged.invalid_items += res.invalid_items
        got = 0
        for ex in res.extracts:
            key = (normalize_identity_text(ex.title or ""),
                   normalize_identity_text(ex.provider or ""))
            if key in seen:
                stats["cross_chunk_duplicates"] += 1
                continue
            seen.add(key)
            merged.extracts.append(ex)
            got += 1
        stats["items_per_chunk"].append(got)
    page.chunked = True
    page.chunk_stats = stats
    if stats["calls"] and stats["failed_chunks"] == stats["calls"]:
        return None
    return merged


async def extract_page(
    html: str,
    url: str,
    *,
    provider_hint: str = "",
    limits: Optional[ExtractionLimits] = None,
    fetch_detail: Optional[FetchFn] = None,
) -> PageExtraction:
    """Extract every opportunity on one page (see module docstring)."""
    limits = limits or ExtractionLimits.from_env()
    cls = classify_page(html, url)
    page = PageExtraction(url=url, kind=cls.kind)
    if cls.kind == PAGE_IRRELEVANT:
        return page

    page_text = html_to_text(html)

    # Program-directory mode (E1.5): an explicit professions/guidelines/tracks
    # section listing same-directory detail links is ONE parent program with
    # authoritative tracks — never N independent opportunities.
    dir_links = _program_track_links(html, url)
    if dir_links:
        return await _extract_program_directory(
            page, html, url, page_text, provider_hint, dir_links)

    # Deterministic single-record parsers only for single-opportunity pages.
    if cls.kind == PAGE_SINGLE:
        det = deterministic.parse_with_deterministic(html, url)
        if det and det.is_critical_complete():
            if not det.provider:
                det.provider = provider_hint
            page.method = "deterministic"
            _apply_title_funding_terms(det)
            page.extracts.append(attach_verification(det, text=page_text, source_url=url))
            return page

    listing_like = cls.kind in (PAGE_LISTING, PAGE_UNKNOWN)
    oversized = listing_like and len(page_text) > llm_parser.LISTING_MAX_CHARS
    if oversized:
        # Page text exceeds the single-call prompt window — extract in
        # bounded structural chunks rather than silently truncating (E2.5).
        result = await _extract_listing_chunked(
            page, html, url, max_items=limits.max_opportunities_per_page,
            limits=limits)
    else:
        result = await llm_parser.extract_opportunities_with_llm(
            html, url, mode=cls.kind, max_items=limits.max_opportunities_per_page,
        )
        if (result is None and listing_like
                and len(page_text) > llm_parser.SINGLE_MAX_CHARS):
            # A single call failed on substantial listing content (e.g. an
            # output-length truncation) — retry once via bounded chunking.
            result = await _extract_listing_chunked(
                page, html, url, max_items=limits.max_opportunities_per_page,
                limits=limits)
    if result is None:
        page.error = "LLM extraction failed"
        return page
    page.method = "llm"
    page.rejected += [("(malformed item)", "invalid_item")] * result.invalid_items

    multi = cls.kind in (PAGE_LISTING, PAGE_UNKNOWN) or len(result.extracts) > 1
    links = link_index(html, url)
    source_key = normalize_link(url)

    # 1. Per-child validation (isolated: one bad child never sinks siblings).
    children: List[Tuple[ScholarshipExtract, Optional[str], Optional[str]]] = []
    seen = set()
    for ex in result.extracts:
        try:
            title = ex.title or ""
            if len(children) >= limits.max_opportunities_per_page:
                page.rejected.append((title, "over_page_limit"))
                continue
            if not ex.is_critical_complete():
                page.rejected.append((title, "generic_or_empty_title"))
                continue
            if multi and not title_on_page(title, page_text):
                page.rejected.append((title, "title_not_on_page"))
                continue
            if not ex.provider:
                ex.provider = provider_hint
            key = (normalize_identity_text(title), normalize_identity_text(ex.provider))
            if key in seen:
                page.rejected.append((title, "duplicate_in_page"))
                continue
            app = accept_url(ex.portal_url, base_url=url, links=links) if ex.portal_url else None
            det = accept_url(ex.detail_url, base_url=url, links=links) if ex.detail_url else None
            page.urls_rejected += int(bool(ex.portal_url) and app is None)
            page.urls_rejected += int(bool(ex.detail_url) and det is None)
            seen.add(key)
            children.append((ex, app, det))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Rejecting malformed child on %s: %s", url, exc)
            page.rejected.append((getattr(ex, "title", "") or "", "malformed"))

    # 2. Per-child URL resolution. A URL shared by several children on the
    # same page (one generic "Apply" portal) is not opportunity-specific and
    # must not become anyone's identity URL; the listing URL is used instead
    # (C4 then keys the child on title+provider).
    usage: Dict[str, int] = {}
    for _, app, det in children:
        for u in {normalize_link(x) for x in (app, det) if x}:
            usage[u] = usage.get(u, 0) + 1

    def _specific(u: Optional[str]) -> bool:
        k = normalize_link(u) if u else ""
        return bool(k) and k != source_key and usage.get(k, 0) < 2

    all_titles = [ex.title for ex in result.extracts if ex.title]
    windows = evidence_windows(page_text, all_titles, max_segment=limits.max_segment_chars) if multi else []
    window_by_title = dict(zip(all_titles, windows))

    for ex, app, det in children:
        ex.portal_url = app if _specific(app) else det if _specific(det) else url
        ex.detail_url = det if _specific(det) else None
        ex.source_url = url

        # 3. Bounded detail fetch: listing -> detail only, never recursive.
        detail_text = ""
        if (multi and ex.detail_url and fetch_detail and limits.detail_fetch_enabled
                and page.detail_attempted < limits.max_detail_fetches_per_page):
            page.detail_attempted += 1
            try:
                detail_html = await fetch_detail(ex.detail_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Detail fetch failed for %s: %s", ex.detail_url, exc)
                detail_html = None
            if detail_html:
                page.detail_succeeded += 1
                detail_text = html_to_text(detail_html)
            else:
                page.detail_failed += 1

        # 4. Scoped evidence: a child is verified only against its own page
        # segment (+ its own detail page) — never a sibling's facts.
        evidence = (window_by_title.get(ex.title, "") if multi else page_text)
        if detail_text:
            evidence = f"{evidence} {detail_text}"

        # 5. Track validation (C8): a parent program may carry named tracks,
        # but a track name that never appears on the page is the same
        # fabrication class the child title-on-page guard exists to stop —
        # drop the track, not the parent. Track detail URLs face the same
        # real-link acceptance as opportunity URLs.
        if ex.tracks:
            kept = []
            for t in ex.tracks:
                if not title_on_page(t.title, page_text):
                    page.rejected.append((t.title, "track_not_on_page"))
                    continue
                if t.detail_url:
                    accepted = accept_url(t.detail_url, base_url=url, links=links)
                    if accepted is None:
                        page.urls_rejected += 1
                        t.detail_url = None
                    else:
                        t.detail_url = accepted
                kept.append(t)
            ex.tracks = kept

        _apply_title_funding_terms(ex)
        ex.deadline = _deadline_year_supported(ex.deadline, f"{page_text} {detail_text}")
        page.extracts.append(attach_verification(ex, text=evidence, source_url=url))

    return page

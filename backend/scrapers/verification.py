"""Source-evidence verification for extracted scholarship facts.

This module deliberately does not ask an LLM to grade another LLM.  It records
which important facts can be independently located in the fetched source text.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from .schema import ScholarshipExtract
from .utils.normalize import clean_text


def _text(html: str) -> str:
    return clean_text(BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True))


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _title_supported(title: str, text: str) -> bool:
    title_n, text_n = _norm(title), _norm(text)
    return bool(title_n and title_n in text_n)


def _amount_supported(amount: int | None, text: str) -> bool | None:
    if amount is None:
        return None
    digits = f"{amount:,}"
    compact = str(amount)
    return bool(re.search(rf"(?:\$\s*)?(?:{re.escape(digits)}|{re.escape(compact)})(?!\d)", text))


def _deadline_supported(deadline: str | None, text: str) -> bool | None:
    if not deadline:
        return None
    try:
        d = datetime.strptime(deadline, "%Y-%m-%d")
    except ValueError:
        return False
    month = d.strftime("%B")
    month_short = d.strftime("%b")
    day, year = str(d.day), str(d.year)
    patterns = [
        rf"\b(?:{month}|{month_short})\.?\s+{day}(?:st|nd|rd|th)?(?:,?\s+{year})?\b",
        rf"\b0?{d.month}[/-]0?{d.day}(?:[/-](?:{year}|{year[-2:]}))?\b",
        rf"\b{year}[/-]0?{d.month}[/-]0?{d.day}\b",
    ]
    return any(re.search(p, text, re.I) for p in patterns)


def _gpa_supported(gpa: float | None, text: str) -> bool | None:
    if gpa is None:
        return None
    number = f"{gpa:g}"
    return bool(re.search(rf"\b(?:GPA[^\d]{{0,20}}{re.escape(number)}|{re.escape(number)}[^\n]{{0,20}}GPA)\b", text, re.I))


_NUMERIC_CLAIM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    """All numeric literals in a text, normalized so formatting variants
    ($5,000 vs 5000.00) compare equal."""
    out: set[float] = set()
    for tok in _NUMERIC_CLAIM.findall(text or ""):
        try:
            out.add(float(tok.replace(",", "")))
        except ValueError:
            continue
    return out


def _description_grounded(description: str | None, text: str) -> bool | None:
    """Deterministic grounding check for a generated public_description.

    Every numeric claim the narrative makes (award amounts, deadlines,
    GPAs, caps, service durations, statistics) must independently appear
    in the source text — these are the highest-risk fabrications. Returns
    None when no description was asserted. False negatives are safe: an
    ungrounded-looking description is dropped to NULL, never published.

    Proper-noun claims (discipline names, provider phrasing) are governed
    by the extraction prompt's strict-grounding rules and review sampling
    rather than substring evidence — a narrative is not an atomic field.
    """
    if not description or not description.strip():
        return None
    claims = _numbers(description)
    return claims <= _numbers(text)


def html_to_text(html: str) -> str:
    return _text(html)


# ---------------------------------------------------------------------------
# Low-information gate (backfill hardening — pilot finding)
# ---------------------------------------------------------------------------
#
# A generated narrative can pass numeric grounding while adding nothing
# beyond the record's own title/provider (pilot: the FSAG directory-index
# description). These checks are deliberately deterministic and
# source-aware — not keyword censorship: a short description is fine when
# its substantive content is locatable in the evidence.

_ENGLISH_STOPS = frozenset(
    "a an the and or of to in for on at by with is are was were be been "
    "this that these those it its their his her our your my we you they "
    "who whom which what when where how all any both each more other some "
    "such no not only own same than then so too very can will just about "
    "into over after between through during before under again".split()
)

# Aid-domain vocabulary that describes ANY opportunity — membership here
# means a token carries no distinguishing information about THIS record.
_AID_FILLER = frozenset(
    "scholarship scholarships grant grants fellowship fellowships award "
    "awards program programs fund funds funding stipend stipends aid "
    "assistance financial opportunity opportunities eligible eligibility "
    "student students applicant applicants apply application applications "
    "provides provide provided offering offers offer supports support "
    "supporting helps help designed gives give receive awarded awards "
    "pursue pursuing education educational school college university "
    "degree undergraduate graduate tuition ensure ensuring ensures needed "
    "available open annually annual one-time renewable recipients winner "
    "winners selected selection dedicated committed".split()
)

_MIN_EVIDENCE_TOKENS = 12
_MIN_NOVEL_TOKENS = 2


def _content_tokens(text: str) -> set:
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").casefold())
        if t not in _ENGLISH_STOPS and len(t) > 2
    }


def description_low_information(
    description: str | None,
    *,
    title: str,
    provider: str,
    evidence_text: str,
) -> str | None:
    """Return a reason when the narrative adds no meaningful
    source-supported information, else None.

    Three conservative signals, any of which rejects:
      sparse_source  — the evidence itself is too thin to support a
                       meaningful narrative (index/listing fragments).
      restatement    — the description's content tokens are wholly covered
                       by the record's title + provider + generic aid
                       vocabulary; it restates the name, nothing more.
      unsupported    — the description introduces substantive terms that
                       mostly cannot be located in the evidence — the
                       prose layer a numeric-only grounding check cannot see.

    A legitimate concise description needs only ~2 novel tokens supported
    by the source; numbers are never required.
    """
    desc = (description or "").strip()
    if not desc:
        return None
    evidence = _content_tokens(evidence_text)
    if len(evidence) < _MIN_EVIDENCE_TOKENS:
        return "sparse_source"
    novel = _content_tokens(desc) - (
        _content_tokens(title) | _content_tokens(provider) | _AID_FILLER
    )
    if len(novel) < _MIN_NOVEL_TOKENS:
        return "restatement"
    supported = novel & evidence
    if len(supported) < max(_MIN_NOVEL_TOKENS, len(novel) // 2):
        return "unsupported"
    return None


def verify_extract_against_source(extract: ScholarshipExtract, html: str) -> dict[str, Any]:
    """Return field-level evidence without silently changing extracted values.

    `verified` means the asserted value was independently found in the fetched
    source text. `not_asserted` means the extract honestly left the field
    unknown. `unverified` means a concrete extracted value could not be found.
    """
    return verify_extract_against_text(extract, _text(html))


def verify_extract_against_text(extract: ScholarshipExtract, text: str) -> dict[str, Any]:
    """Verify against already-scoped evidence text (C5: a listing child is
    verified only against its own segment of the page, plus its own detail
    page when fetched — never against a sibling's facts)."""
    checks = {
        "title": _title_supported(extract.title, text),
        "award_amount": _amount_supported(extract.award_amount, text),
        "deadline": _deadline_supported(extract.deadline, text),
        "min_gpa": _gpa_supported(extract.min_gpa, text),
        # Narrative grounding is evidence-recorded but excluded from `asserted`:
        # an ungrounded description is dropped to NULL by attach_verification —
        # the consequence is losing prose, never burying an otherwise sound
        # record in needs_review.
        "public_description": _description_grounded(extract.public_description, text),
    }
    fields = {
        name: ("not_asserted" if value is None else "verified" if value else "unverified")
        for name, value in checks.items()
    }
    asserted = [v for k, v in checks.items() if k != "public_description" and v is not None]
    # Title is identity-critical. Any asserted core fact that cannot be found
    # keeps the record out of the automatically verified state.
    status = "verified" if asserted and all(asserted) else "needs_review"
    return {"status": status, "fields": fields}

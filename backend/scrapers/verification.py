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


def html_to_text(html: str) -> str:
    return _text(html)


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
    }
    fields = {
        name: ("not_asserted" if value is None else "verified" if value else "unverified")
        for name, value in checks.items()
    }
    asserted = [v for v in checks.values() if v is not None]
    # Title is identity-critical. Any asserted core fact that cannot be found
    # keeps the record out of the automatically verified state.
    status = "verified" if asserted and all(asserted) else "needs_review"
    return {"status": status, "fields": fields}

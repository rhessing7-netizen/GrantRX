"""Text, date, and currency normalization helpers for the scraper pipeline."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import List, Optional

from dateutil import parser as dateparser

# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def clean_text(value: Optional[str]) -> str:
    """Collapse whitespace and trim a string. Returns '' for None."""
    if not value:
        return ""
    return _WS_RE.sub(" ", value).strip()


def split_list(value: Optional[str], separators: str = ",;|") -> List[str]:
    """Split a delimited string into a cleaned list of items."""
    if not value:
        return []
    parts = re.split(f"[{separators}]", value)
    return [clean_text(p) for p in parts if clean_text(p)]


# ---------------------------------------------------------------------------
# Currency / amount parsing
# ---------------------------------------------------------------------------

_AMOUNT_RE = re.compile(r"[\$£€]?\s*([\d,]+(?:\.\d+)?)")
_MULT_RE = re.compile(r"(\d+)\s*(?:x|×|per)\s*(\d+)", re.IGNORECASE)


def parse_amount(value: Optional[str]) -> Optional[int]:
    """Parse a currency/award string into an integer dollar amount.

    Examples:
        "$5,000"            -> 5000
        "$2,500 per year"   -> 2500
        "Up to $10,000"     -> 10000
    """
    if not value:
        return None
    text = clean_text(value)
    if not text:
        return None

    mult = _MULT_RE.search(text)
    if mult:
        base = int(mult.group(1))
        return base

    match = _AMOUNT_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    try:
        amount = float(raw)
    except ValueError:
        return None
    if amount <= 0:
        return None
    return int(amount)


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_RELATIVE_RE = re.compile(
    r"\b(today|tomorrow|yesterday)\b",
    re.IGNORECASE,
)


def parse_date(value: Optional[str], default_year: Optional[int] = None) -> Optional[date]:
    """Parse a date string into a :class:`datetime.date`.

    Handles common formats, full month names, abbreviations, and relative
    terms (today/tomorrow). Returns None if unparseable.
    """
    if not value:
        return None
    text = clean_text(value)
    if not text:
        return None

    # Strip parenthetical notes like "(annually)" or "(rolling)"
    text = re.sub(r"\([^)]*\)", "", text).strip()
    if not text:
        return None

    lower = text.lower()
    today = date.today()
    if lower == "today":
        return today
    if lower == "tomorrow":
        return today + timedelta(days=1)
    if lower == "yesterday":
        return today - timedelta(days=1)

    try:
        parsed = dateparser.parse(text, fuzzy=True, default=datetime(today.year, 1, 1))
    except (ValueError, TypeError, dateparser.ParserError):
        return None

    if default_year is not None and parsed.year == datetime.today().year and parsed.month == 1 and parsed.day == 1:
        # dateutil used the default; only trust it if the original text mentioned a month/day
        if not re.search(r"\d", text):
            return None

    return parsed.date()


def add_one_year(d: date) -> date:
    """Return the same month/day one year later, handling Feb 29 -> Feb 28."""
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


# ---------------------------------------------------------------------------
# Discipline / credential mapping
# ---------------------------------------------------------------------------

DISCIPLINE_KEYWORDS = {
    "pharmacy": ["pharm", "pharmacy", "pharmd", "cph", "pharmacist"],
    "medicine": ["md", "do ", "doctor of medicine", "physician", "medical student", "med student"],
    "nursing": ["nurs", "bsn", "msn", "rn", "nurse"],
    "therapeutics_rehab": ["dpt", "physical therap", "occupational therap", "rehab", "therapeutics"],
    "diagnostic_imaging": ["radiolog", "imaging", "sonograph", "ct ", "mri", "diagnostic"],
    "public_health_emergency": ["public health", "emergency", "epidemio", "disaster", "mpa", "mph"],
}

CREDENTIAL_KEYWORDS = {
    "PharmD": ["pharmd", "doctor of pharmacy"],
    "BSN": ["bsn", "bachelor of science in nursing"],
    "MSN": ["msn", "master of science in nursing"],
    "DPT": ["dpt", "doctor of physical therapy"],
    "MD": ["md", "doctor of medicine"],
    "DO": ["do", "doctor of osteopathic"],
    "CPhT": ["cpht", "certified pharmacy technician"],
    "RN": ["rn", "registered nurse"],
    "MPH": ["mph", "master of public health"],
}


def map_disciplines(text: Optional[str]) -> List[str]:
    """Map free text to the clinical_discipline ENUM values."""
    if not text:
        return []
    lower = text.lower()
    found = set()
    for discipline, keywords in DISCIPLINE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            found.add(discipline)
    return sorted(found)


def map_credentials(text: Optional[str]) -> List[str]:
    """Map free text to a list of credential abbreviations."""
    if not text:
        return []
    lower = text.lower()
    found = set()
    for cred, keywords in CREDENTIAL_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            found.add(cred)
    return sorted(found)

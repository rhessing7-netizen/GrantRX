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

_CURRENCY_RE = re.compile(r"[\$£€]\s*([\d,]+(?:\.\d+)?)")
_PLAIN_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MULT_RE = re.compile(r"(\d+)\s*(?:x|×|per)\s*[\$£€]?\s*([\d,]+)", re.IGNORECASE)


def _is_year_like(token: str) -> bool:
    """True for year-shaped numbers that must not be mistaken for amounts."""
    plain = token.replace(",", "").split(".")[0]
    if len(plain) != 4:
        return False
    try:
        return 1900 <= int(plain) <= 2099
    except ValueError:
        return False


def parse_amount(value: Optional[str]) -> Optional[int]:
    """Parse a currency/award string into an integer dollar amount.

    Currency-anchored values are preferred. Bare numbers are accepted only when
    they are not year-like, so "2025-2026 award: $5,000" -> 5000 and "2025"
    alone -> None.

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
        # "2 x $5,000" / "3 awards of $1,000" — the second operand is the amount.
        try:
            amount = int(mult.group(2).replace(",", ""))
        except ValueError:
            amount = 0
        if amount > 0 and not _is_year_like(mult.group(2)):
            return amount

    # Prefer an explicitly currency-anchored number ($ / £ / €).
    match = _CURRENCY_RE.search(text)
    if match:
        raw = match.group(1).replace(",", "")
        try:
            amount = float(raw)
        except ValueError:
            return None
        return int(amount) if amount > 0 else None

    # Fallback: first non-year-like plain number.
    for m in _PLAIN_NUM_RE.finditer(text):
        token = m.group(0)
        if _is_year_like(token):
            continue
        try:
            amount = float(token.replace(",", ""))
        except ValueError:
            continue
        if amount <= 0:
            continue
        return int(amount)
    return None


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_RELATIVE_RE = re.compile(
    r"\b(today|tomorrow|yesterday)\b",
    re.IGNORECASE,
)

# A concrete deadline must contain a complete date including an explicit year.
# A bare "March 1" or "Spring 2026" would otherwise silently fabricate the
# month/day/year via dateparser defaults.
_MONTH = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
_EXPLICIT_DATE_RE = re.compile(
    r"(?:\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b"  # 2026-03-01
    r"|\b\d{1,2}[-/]\d{1,2}[-/](?:19|20)?\d{2}\b"  # 03/01/2026 or 3/1/26
    rf"|\b(?:{_MONTH})[a-z]*\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\s*,?\s*(?:19|20)?\d{{2}}\b"  # March 1, 2026
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH})[a-z]*\.?\s*,?\s*(?:19|20)?\d{{2}}\b"  # 1 March 2026
    r")",
    re.IGNORECASE,
)


def parse_date(value: Optional[str], default_year: Optional[int] = None) -> Optional[date]:
    """Parse a date string into a :class:`datetime.date`.

    Handles common formats, full month names, abbreviations, and relative
    terms (today/tomorrow). Returns None if unparseable.

    An explicit year is required: partial dates such as "March 1" or
    "Spring 2026" return None rather than having a month/day/year invented.
    ``default_year`` is retained for signature compatibility but no longer
    supplies a missing year.
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

    if not _EXPLICIT_DATE_RE.search(text):
        return None

    try:
        parsed = dateparser.parse(text, fuzzy=True)
    except (ValueError, TypeError, dateparser.ParserError):
        return None
    if parsed is None:
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

# ---------------------------------------------------------------------------
# Discipline / credential mapping
#
# IMPORTANT: these helpers turn free text into hard eligibility restrictions.
# They therefore match on word-boundary patterns only — plain substring search
# misreads ordinary prose ("do" inside "donors", "rn" inside "learn"/"return",
# "ct" inside "direct") and manufactures restrictions that wrongly gate users.
# Callers must pass targeted eligibility text (e.g. an eligibility/criteria
# section), never an entire page body.
# ---------------------------------------------------------------------------

_DISCIPLINE_PATTERNS = {
    # Healthcare subtree (canonical C8 codes; the six legacy enum values map
    # to themselves).
    "pharmacy": [r"\bpharm\w*", r"\bcphs\b"],
    "medicine": [r"\bdoctor of medicine\b", r"\bphysician", r"\bmedical student", r"\bmed student", r"\bmedicine\b", r"\bpre[- ]?med\b"],
    "nursing": [r"\bnurs", r"\bbsn\b", r"\bmsn\b", r"\brn\b"],
    "dentistry": [r"\bdent(?:al|istry|ist)\w*\b", r"\bdds\b", r"\bdmd\b"],
    "physician_assistant": [r"physician assistant", r"\bpa program\b", r"\bpre[- ]?pa\b"],
    "therapeutics_rehab": [r"\bdpt\b", r"\botd\b", r"physical therap", r"occupational therap", r"\brehab\b", r"therapeutics"],
    "diagnostic_imaging": [r"radiolog", r"imaging", r"sonograph", r"\bmri\b", r"\bct scan\b", r"ultrasound"],
    "public_health_emergency": [r"public health", r"emergency", r"epidemio", r"disaster", r"\bmph\b"],
    # General fields of study (C8) — same word-boundary discipline.
    "computer_science": [r"computer science", r"\bsoftware engineering\b", r"\bcomp\.? sci\b"],
    "engineering": [r"\bengineering\b", r"\bengineers?\b"],
    "mathematics": [r"\bmath(?:ematics)?\b", r"\bstatistics\b"],
    "biological_sciences": [r"\bbiology\b", r"\bbiolog\w*", r"\bzoology\b", r"\bbotany\b", r"\bmicrobiology\b", r"\bgenetics\b", r"\bneuroscience\b"],
    "physical_sciences": [r"\bchemistry\b", r"\bphysics\b", r"\bbiochemistry\b", r"\bastronomy\b", r"\bgeology\b"],
    "environmental_science": [r"environmental science", r"\benvironmental studies\b"],
    "business_administration": [r"business administration", r"\bbusiness major", r"\bmanagement\b", r"\bmba\b"],
    "accounting": [r"\baccounting\b", r"\baccountancy\b", r"\bcpa\b"],
    "finance": [r"\bfinance\b", r"\bfinancial\b"],
    "economics": [r"\beconomics\b"],
    "marketing": [r"\bmarketing\b"],
    "teaching_education": [r"\bteach(?:er|ing)\b", r"education major", r"\bk[- ]?12\b"],
    "psychology": [r"\bpsychology\b", r"\bpsych\b", r"\bpsyd\b"],
    "social_work": [r"social work", r"\bmsw\b", r"\blcsw\b"],
    "criminal_justice": [r"criminal justice", r"\bcriminology\b", r"\blaw enforcement\b"],
    "political_science": [r"political science", r"\bpoli[- ]?sci\b"],
    "communications": [r"\bcommunication\w*\b", r"\bjournalism\b", r"\bmedia studies\b"],
    "english_language": [r"\benglish major\b", r"\benglish literature\b", r"\bcreative writing\b"],
    "history": [r"\bhistory\b"],
    "law": [r"\blaw school\b", r"\bpre[- ]?law\b", r"\bjuris doctor\b", r"\bj\.?d\.?\b"],
    "trades_technical": [r"\btrade school\b", r"\bvocational\b", r"\btechnical (?:program|school|college)\b", r"\bapprenticeship\b"],
    "agriculture": [r"\bagricultur\w+\b", r"\bfarm\b", r"\banimal science\b"],
}

_CREDENTIAL_PATTERNS = {
    "PharmD": [r"\bpharm\.?d\b", r"doctor of pharmacy"],
    "BSN": [r"\bbsn\b", r"bachelor of science in nursing"],
    "MSN": [r"\bmsn\b", r"master of science in nursing"],
    "DPT": [r"\bdpt\b", r"doctor of physical therapy"],
    "MD": [r"\bm\.?d\.?\b", r"doctor of medicine"],
    "DO": [r"osteopathic", r"\bd\.o\.\b"],
    "CPhT": [r"\bcpht?\b", r"pharmacy technician"],
    "RN": [r"\br\.?n\.?\b", r"registered nurse"],
    "MPH": [r"\bmph\b", r"master of public health"],
}

# Backwards-compatible names for code that imports the keyword maps.
DISCIPLINE_KEYWORDS = _DISCIPLINE_PATTERNS
CREDENTIAL_KEYWORDS = _CREDENTIAL_PATTERNS


def map_disciplines(text: Optional[str]) -> List[str]:
    """Map eligibility text to canonical field-of-study codes (C8).

    Requires word-boundary pattern matches. Pass only explicit eligibility
    content; ambiguous or empty input returns [] (unrestricted).
    """
    if not text:
        return []
    lower = text.lower()
    found = set()
    for discipline, patterns in _DISCIPLINE_PATTERNS.items():
        if any(re.search(p, lower) for p in patterns):
            found.add(discipline)
    return sorted(found)


def map_credentials(text: Optional[str]) -> List[str]:
    """Map eligibility text to canonical credential codes.

    Requires word-boundary pattern matches. Pass only explicit eligibility
    content; ambiguous or empty input returns [] (unrestricted).
    """
    if not text:
        return []
    lower = text.lower()
    found = set()
    for cred, patterns in _CREDENTIAL_PATTERNS.items():
        if any(re.search(p, lower) for p in patterns):
            found.add(cred)
    return sorted(found)

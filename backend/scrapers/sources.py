"""Default source URL list and source schema for the scraper runner.

Sources can be defined in two ways:
1. Python defaults (DEFAULT_SOURCES below) — simple (name, url) tuples.
2. A JSON file at scrapers/sources.json (or pointed to by GRANTRX_SOURCES_JSON)
   with full SourceConfig fields: name, url, category, primary_discipline,
   target_credentials, state_restriction, scraper_type.

The runner loads sources.json if present, falling back to DEFAULT_SOURCES.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Source categories
# ---------------------------------------------------------------------------

CATEGORIES = {
    "national_association",
    "federal_program",
    "state_agency",
    "hospital_system",
    "diversity_affinity",
    "corporate_unrestricted",
    "corporate_healthcare",
    "regional_foundation",
    "honor_society",
    "chamber_of_commerce",
    "faith_based_community",
    "local_business",
    "institutional_department",
}

SCRAPER_TYPES = {"deterministic", "playwright", "llm_fallback"}

# ---------------------------------------------------------------------------
# Discipline normalization
# ---------------------------------------------------------------------------

# Maps human-readable discipline labels from sources.json to the system's
# clinical_discipline ENUM values used by the matcher.
_DISCIPLINE_MAP = {
    "pharmacy": "pharmacy",
    "medicine": "medicine",
    "nursing": "nursing",
    "physical therapy": "therapeutics_rehab",
    "occupational therapy": "therapeutics_rehab",
    "therapeutics_rehab": "therapeutics_rehab",
    "diagnostic imaging": "diagnostic_imaging",
    "radiology": "diagnostic_imaging",
    "public health": "public_health_emergency",
    "emergency": "public_health_emergency",
    "osteopathic medicine": "medicine",
    "physician assistant": "medicine",
    "dentistry": "any",  # no matching enum; treat as unrestricted
    "speech-language pathology": "therapeutics_rehab",
    "health administration": "public_health_emergency",
    # Allied Health, Therapy & Kinesiology
    "exercise science": "therapeutics_rehab",
    "kinesiology": "therapeutics_rehab",
    "athletic training": "therapeutics_rehab",
    "respiratory therapy": "therapeutics_rehab",
    # Public Health & Health Administration
    "health sciences": "public_health_emergency",
    "global health": "public_health_emergency",
    "epidemiology": "public_health_emergency",
    "healthcare management": "public_health_emergency",
    "health informatics": "public_health_emergency",
    "environmental health": "public_health_emergency",
    "environmental science": "public_health_emergency",
    # Diagnostic Imaging
    "radiologic technology": "diagnostic_imaging",
    "radiologic": "diagnostic_imaging",
    # Pre-clinical & general science -> medicine (pre-health fallback)
    "pre-medicine": "medicine",
    "pre-med": "medicine",
    "pre-nursing": "nursing",
    "pre-pharmacy": "pharmacy",
    "pre-dental": "medicine",
    "pre-veterinary": "medicine",
    "pre-vet": "medicine",
    "pre-physician assistant": "medicine",
    "pre-pa": "medicine",
    "medical laboratory science": "medicine",
    "dental hygiene": "medicine",
    # Biological Sciences -> medicine (pre-health)
    "biology": "medicine",
    "molecular": "medicine",
    "cellular biology": "medicine",
    "microbiology": "medicine",
    "genetics": "medicine",
    "neuroscience": "medicine",
    "botany": "medicine",
    "plant biology": "medicine",
    "zoology": "medicine",
    "ecology": "medicine",
    "evolutionary biology": "medicine",
    # Chemical & Physical Sciences -> medicine (pre-health)
    "chemistry": "medicine",
    "biochemistry": "medicine",
    "organic chemistry": "medicine",
    "analytical chemistry": "medicine",
    "physics": "medicine",
    "biophysics": "medicine",
    "astronomy": "medicine",
    "astrophysics": "medicine",
    # Earth & Environmental Sciences -> medicine (pre-health/STEM)
    "geology": "medicine",
    "earth science": "medicine",
    "geophysics": "medicine",
    "oceanography": "medicine",
    "atmospheric": "medicine",
    "meteorology": "medicine",
    "any": "any",
}


def normalize_discipline(value: str) -> str:
    """Normalize a human-readable discipline label to a system ENUM value.

    Examples:
        "Pharmacy (PharmD)" -> "pharmacy"
        "Medicine (MD)"     -> "medicine"
        "Nursing (BSN)"     -> "nursing"
        "any"               -> "any"
    """
    if not value:
        return "any"
    lower = value.strip().lower()
    if lower == "any":
        return "any"
    # Try exact key match first
    if lower in _DISCIPLINE_MAP:
        return _DISCIPLINE_MAP[lower]
    # Try prefix match (e.g. "pharmacy (pharmd)" -> "pharmacy")
    for key, mapped in _DISCIPLINE_MAP.items():
        if lower.startswith(key):
            return mapped
    # Fallback: check if any keyword is in the string
    for key, mapped in _DISCIPLINE_MAP.items():
        if key in lower:
            return mapped
    return "any"


# ---------------------------------------------------------------------------
# Source config schema
# ---------------------------------------------------------------------------


@dataclass
class SourceConfig:
    """Structured source definition for the three-tier scraper pipeline.

    Fields:
        name: Human-readable source name (used as provider hint).
        url: Target URL to scrape.
        category: One of the CATEGORIES values.
        primary_discipline: "any" or a specific clinical_discipline ENUM value.
        target_credentials: List of credential strings (e.g. ["PharmD", "BSN"]).
        state_restriction: Optional 2-letter state code for regional sources.
        scraper_type: Which tier to use: "deterministic", "playwright", or "llm_fallback".
    """

    name: str
    url: str
    category: str = "national_association"
    primary_discipline: str = "any"
    target_credentials: List[str] = field(default_factory=list)
    state_restriction: Optional[str] = None
    scraper_type: str = "deterministic"

    def to_tuple(self) -> Tuple[str, str]:
        """Backwards-compatible (provider_hint, url) tuple."""
        return (self.name, self.url)

    @classmethod
    def from_dict(cls, data: dict) -> "SourceConfig":
        return cls(
            name=data.get("name", ""),
            url=data["url"],
            category=data.get("category", "national_association"),
            primary_discipline=normalize_discipline(data.get("primary_discipline", "any")),
            target_credentials=data.get("target_credentials", []),
            state_restriction=data.get("state_restriction"),
            scraper_type=data.get("scraper_type", "deterministic"),
        )


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def _sources_json_path() -> Optional[Path]:
    """Find the sources.json file.

    Priority:
      1. GRANTRX_SOURCES_JSON env var (explicit path)
      2. scrapers/sources.json (co-located with this module)
    """
    env_path = os.getenv("GRANTRX_SOURCES_JSON")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    co_located = Path(__file__).parent / "sources.json"
    if co_located.exists():
        return co_located
    return None


def load_sources_from_json() -> Optional[List[SourceConfig]]:
    """Load SourceConfig list from sources.json if available. Returns None if not found."""
    path = _sources_json_path()
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        return None
    return [SourceConfig.from_dict(item) for item in data]


def load_sources() -> List[SourceConfig]:
    """Load sources from JSON if available, otherwise from Python defaults."""
    json_sources = load_sources_from_json()
    if json_sources is not None:
        return json_sources
    return DEFAULT_SOURCE_CONFIGS


# ---------------------------------------------------------------------------
# Default sources (Python fallback)
# ---------------------------------------------------------------------------

DEFAULT_SOURCE_CONFIGS: List[SourceConfig] = [
    SourceConfig(
        name="American Pharmacists Association",
        url="https://www.pharmacist.com/education/student-resources/scholarships",
        category="national_association",
        primary_discipline="pharmacy",
        target_credentials=["PharmD", "CPhT"],
        scraper_type="deterministic",
    ),
    SourceConfig(
        name="American Association of Colleges of Nursing",
        url="https://www.aacnnursing.org/Students/Scholarships-Financial-Aid",
        category="national_association",
        primary_discipline="nursing",
        target_credentials=["BSN", "MSN", "RN"],
        scraper_type="deterministic",
    ),
    SourceConfig(
        name="California Student Aid Commission",
        url="https://www.csac.ca.gov/scholarships",
        category="regional_foundation",
        primary_discipline="any",
        state_restriction="CA",
        scraper_type="playwright",
    ),
    SourceConfig(
        name="New York State Higher Education Services Corporation",
        url="https://www.hesc.ny.gov/pay-for-college/scholarships.html",
        category="regional_foundation",
        primary_discipline="any",
        state_restriction="NY",
        scraper_type="playwright",
    ),
]


# Backwards-compatible tuple list for code that hasn't been migrated yet
DEFAULT_SOURCES: List[Tuple[str, str]] = [s.to_tuple() for s in DEFAULT_SOURCE_CONFIGS]

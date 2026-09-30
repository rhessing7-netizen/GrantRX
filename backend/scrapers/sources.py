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
    "university_listing",
    # Employer tuition assistance & service-obligation categories
    "employer_tuition_benefit",
    "clinical_employee_pipeline",
    "government_employee_benefit",
    "accrediting_body",
}

SCRAPER_TYPES = {"deterministic", "playwright", "llm_fallback"}

# ---------------------------------------------------------------------------
# Discipline normalization
# ---------------------------------------------------------------------------

# C8: the canonical field-of-study registry lives in scrapers.utils.taxonomy.
# The old _DISCIPLINE_MAP collapsed every label into the six clinical_discipline
# enum values (or "any"); normalization now returns canonical field-of-study
# codes. `normalize_discipline` keeps its name/signature for callers.
from .utils.taxonomy import ANY_FIELD, normalize_field_of_study


def normalize_discipline(value: str) -> str:
    """Normalize a human-readable discipline label to a canonical field code.

    Used for source-coverage hints: unmapped values return ``ANY_FIELD``
    ("this source is not discipline-scoped"), which is a source hint, not an
    applicant-eligibility assertion.
    """
    if not value:
        return ANY_FIELD
    return normalize_field_of_study(value) or ANY_FIELD


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

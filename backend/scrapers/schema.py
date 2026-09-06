"""Canonical scholarship extraction record shared across parser stages."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ScholarshipExtract(BaseModel):
    """Schema produced by deterministic and LLM parsers alike.

    `portal_url` and `provider` are set by the runner before DB upsert.
    Critical fields used to decide whether to invoke the LLM fallback:
    `title`, `award_amount`, `deadline`.
    """

    # Core Identification & Link
    title: str
    provider: str = ""
    portal_url: str = ""
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    source_category: str = "general"

    # Financial & Deadlines
    award_amount: Optional[int] = None
    is_renewable: bool = False
    deadline: Optional[str] = None  # ISO YYYY-MM-DD

    # Academic Scoping (General & Specific)
    is_general_major: bool = Field(
        default=False,
        description="True if open to ANY major/unrestricted",
    )
    eligible_disciplines: List[str] = Field(
        default_factory=list,
        description="Empty or ['any'] for all majors; else specific tracks",
    )
    eligible_credentials: List[str] = Field(
        default_factory=list,
        description="e.g. ['High School', 'Associate', 'Bachelor', 'Master', 'Doctorate', 'Vocational']",
    )
    academic_levels: List[str] = Field(
        default_factory=list,
        description="['high_school_senior', 'undergraduate_freshman', 'undergraduate', 'graduate', 'doctoral']",
    )
    min_gpa: Optional[float] = None
    max_sai: Optional[int] = None

    # Geographic Targeting (National, State, Metro, Hyper-Local)
    scope: str = Field(
        default="national",
        description="'national', 'state', 'metro', 'county', or 'city'",
    )
    state_restrictions: List[str] = []
    metro_restrictions: List[str] = []  # MSA names or "cbsa:XXXXX" codes
    county_restrictions: List[str] = Field(
        default_factory=list,
        description="Specific counties (e.g. ['Wayne County', 'Cuyahoga County'])",
    )
    city_restrictions: List[str] = Field(
        default_factory=list,
        description="Specific municipalities or towns",
    )

    # Competition & Hyper-Local Tagging
    is_local: bool = Field(
        default=False,
        description="True if restricted to a specific county, town, high school, church, or community",
    )
    competition_level: str = Field(
        default="medium",
        description="'low' (hyper-local, specific school/county), 'medium' (statewide/niche), 'high' (national open-brand)",
    )
    target_community: Optional[str] = None

    # Affiliations & Tags
    required_affiliations: List[str] = []
    matching_tags: List[str] = []
    estimated_next_cycle: Optional[str] = None

    # Source metadata
    source: str = "deterministic"  # or "llm"

    # Provider alignment & local discovery fields
    provider_type: Optional[str] = None
    provider_mission: Optional[str] = None
    provider_core_values: List[str] = []

    def is_critical_complete(self) -> bool:
        """Return True if all critical fields are populated and parseable."""
        return bool(self.title) and self.award_amount is not None and bool(self.deadline)


class ParseError(BaseModel):
    url: str
    reason: str
    stage: str = "deterministic"

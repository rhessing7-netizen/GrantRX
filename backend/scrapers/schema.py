"""Canonical scholarship extraction record shared across parser stages."""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field


class TrackExtract(BaseModel):
    """One named track/variant inside a parent funding program (C8).

    A track shares the parent's administration and application. It may carry
    its own eligibility, award, deadline and detail URL, but it is not an
    independently persisted opportunity — it never gets its own
    ``identity_key``.
    """

    title: str
    detail_url: Optional[str] = None
    award_amount: Optional[int] = None
    deadline: Optional[str] = None  # ISO YYYY-MM-DD
    eligible_disciplines: List[str] = Field(default_factory=list)
    eligible_credentials: List[str] = Field(default_factory=list)


class ScholarshipExtract(BaseModel):
    """Schema produced by deterministic and LLM parsers alike.

    `portal_url` and `provider` are set by the runner before DB upsert.
    A record is publishable when it has a title; award amount and deadline may
    legitimately be unknown, variable, rolling, or not yet announced.
    """

    # Core Identification & Link
    title: str
    provider: str = ""
    portal_url: str = ""
    # Opportunity-specific detail page found on a listing (C5). Extraction-time
    # only — not persisted; it can become portal_url when no application link.
    detail_url: Optional[str] = None
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
    # NULL means the geography was never established — an explicitly
    # unrestricted award stores 'national'. Unknown must never masquerade as
    # national (C8 / C6.5 calibration finding).
    scope: Optional[str] = Field(
        default=None,
        description="'national', 'state', 'metro', 'county', 'city', or null when unstated",
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

    # Employer tuition assistance, service-obligation, and vendor-platform fields
    funding_type: Optional[str] = Field(
        default=None,
        description=(
            "Funding mechanism when stated: 'scholarship', 'grant', "
            "'fellowship', 'tuition_reimbursement', 'employer_sponsorship', "
            "'loan_repayment', 'service_contingent', 'prize', 'other'. "
            "Null when unknown — never fabricated."
        ),
    )
    employment_required: bool = Field(
        default=False,
        description=(
            "True if the applicant must be an employee or hired into an "
            "apprentice/technician pipeline of the sponsoring employer."
        ),
    )
    min_employment_tenure_months: Optional[int] = Field(
        default=None,
        description="Minimum months of employment required before benefit eligibility.",
    )
    annual_benefit_cap: Optional[int] = Field(
        default=None,
        description="Annual cap on the tuition benefit in whole US dollars, if any.",
    )
    benefit_coverage_model: Optional[str] = Field(
        default=None,
        description=(
            "Coverage model: 'direct_bill' (employer pays school directly), "
            "'reimbursement' (student pays, employer reimburses), or "
            "'forgivable_loan' (loan forgiven over service/tenure)."
        ),
    )
    partner_network: Optional[str] = Field(
        default=None,
        description=(
            "Education-benefit partner network, e.g. 'guild', 'instride', "
            "'edassist', or 'internal' if administered by the employer directly."
        ),
    )
    has_service_commitment: bool = Field(
        default=False,
        description=(
            "True if the recipient owes post-graduation work (e.g. 2 years "
            "in a rural health clinic or hospital network)."
        ),
    )
    service_commitment_duration_months: Optional[int] = Field(
        default=None,
        description="Length of the required post-graduation service commitment in months.",
    )
    vendor_platform: Optional[str] = Field(
        default=None,
        description=(
            "Scholarship management platform hosting the application, e.g. "
            "'academicworks', 'kaleidoscope', 'smarterselect', 'openwater'."
        ),
    )

    # Additional eligibility dimensions (C8). All record-only: the profile
    # side does not yet collect these attributes, so they inform display and
    # notices rather than hard gates.
    citizenship_requirement: Optional[str] = Field(
        default=None,
        description="Canonical citizenship code or null when unstated.",
    )
    enrollment_statuses: List[str] = Field(
        default_factory=list,
        description="Canonical enrollment codes (full_time/part_time/enrolled/accepted/graduating); empty when unstated.",
    )
    institution_restrictions: List[str] = Field(
        default_factory=list,
        description="Named institutions the award is limited to; empty when unstated.",
    )
    military_affiliation_requirement: Optional[str] = Field(
        default=None,
        description="Canonical military-affiliation code or null when unstated.",
    )

    # Parent-program tracks (C8). Named variants of this one program — never
    # independently persisted opportunities.
    tracks: List[TrackExtract] = Field(default_factory=list)

    def is_critical_complete(self) -> bool:
        """Return True when the opportunity has enough identity to persist.

        Unknown award amounts and deadlines are valid source states and must not
        be converted into invented values. Generic directory/listing headings
        are not opportunity titles.
        """
        title = re.sub(r"[^a-z0-9]+", " ", (self.title or "").casefold()).strip()
        return bool(title) and title not in _GENERIC_LISTING_TITLES


# Directory/listing headings that describe a page of opportunities, not an
# individual opportunity. Exact-match only so that specifically named programs
# (e.g. "Community Health Scholarship Fund") are never rejected.
_GENERIC_LISTING_TITLES = {
    "scholarship",
    "scholarships",
    "scholarship opportunities",
    "scholarship program",
    "scholarship programs",
    "student scholarships",
    "financial aid",
    "financial aid scholarships",
    "grants",
    "grant programs",
    "funding opportunities",
    "funding",
    "awards",
    "awards and grants",
    "scholarships and grants",
    "grants and scholarships",
    "tuition assistance",
    "outside scholarships",
    "external scholarships",
    "external aid",
    "scholarship search",
    "scholarship finder",
    "opportunities",
    "apply",
}


class ParseError(BaseModel):
    url: str
    reason: str
    stage: str = "deterministic"

import re
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClinicalDiscipline(str, Enum):
    pharmacy = "pharmacy"
    medicine = "medicine"
    nursing = "nursing"
    therapeutics_rehab = "therapeutics_rehab"
    diagnostic_imaging = "diagnostic_imaging"
    public_health_emergency = "public_health_emergency"


class AppStatus(str, Enum):
    saved = "saved"
    in_progress = "in_progress"
    submitted = "submitted"
    awarded = "awarded"
    archived = "archived"


class SubscriptionTier(str, Enum):
    free = "free"
    premium = "premium"


class ProfileBase(BaseModel):
    # Multi-select arrays (new preferred fields — all optional)
    disciplines: List[str] = []
    target_credentials: List[str] = []
    # Legacy single-choice fields (kept for backward compatibility)
    primary_discipline: Optional[str] = None
    target_credential: Optional[str] = None
    clinical_phase: Optional[str] = None
    gpa: Optional[float] = Field(None, ge=0.0, le=4.0)
    state_residence: Optional[str] = Field(None, max_length=2)
    metro_area: Optional[str] = None
    sai_score: Optional[int] = None
    first_gen: bool = False
    minority_flag: bool = False
    professional_affiliations: List[str] = []
    hobbies: List[str] = []
    subscription_tier: SubscriptionTier = SubscriptionTier.free


class ProfileCreate(ProfileBase):
    id: Optional[UUID] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    terms_accepted: bool = False
    privacy_accepted: bool = False
    marketing_opt_in: bool = False


class ProfileUpdate(BaseModel):
    id: Optional[UUID] = None
    disciplines: Optional[List[str]] = None
    target_credentials: Optional[List[str]] = None
    primary_discipline: Optional[str] = None
    target_credential: Optional[str] = None
    clinical_phase: Optional[str] = None
    gpa: Optional[float] = Field(None, ge=0.0, le=4.0)
    state_residence: Optional[str] = Field(None, max_length=2)
    metro_area: Optional[str] = None
    sai_score: Optional[int] = None
    first_gen: Optional[bool] = None
    minority_flag: Optional[bool] = None
    professional_affiliations: Optional[List[str]] = None
    hobbies: Optional[List[str]] = None
    subscription_tier: Optional[SubscriptionTier] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    terms_accepted: Optional[bool] = None
    privacy_accepted: Optional[bool] = None
    marketing_opt_in: Optional[bool] = None
    has_completed_tour: Optional[bool] = None


class ProfileOut(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: Optional[str] = None
    email: Optional[str] = None
    terms_accepted_at: Optional[datetime] = None
    privacy_accepted_at: Optional[datetime] = None
    marketing_opt_in: bool = False
    marketing_opt_in_at: Optional[datetime] = None
    has_completed_tour: bool = False
    searches_used_this_week: int = 0
    search_cycle_reset_at: Optional[datetime] = None
    feed_token: Optional[str] = None
    stripe_subscription_status: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ScholarshipBase(BaseModel):
    title: str
    provider: str
    portal_url: str
    award_amount: Optional[int] = Field(None, ge=0)
    deadline: Optional[date] = None
    # C8: canonical field-of-study codes — free text over the taxonomy
    # registry, not the retired 6-value clinical enum. [] = unknown,
    # ["any"] = explicitly unrestricted.
    eligible_disciplines: List[str] = []
    eligible_credentials: List[str] = []
    min_gpa: float = 0.0
    max_sai: Optional[int] = None
    state_restrictions: List[str] = []
    metro_restrictions: List[str] = []
    required_affiliations: List[str] = []
    matching_tags: List[str] = []
    is_archived: bool = False
    estimated_next_cycle: Optional[date] = None
    # Academic criteria — general major & academic levels
    is_general_major: bool = False
    academic_levels: List[str] = []
    # Geographic targeting — null = geography never established (unknown
    # must not masquerade as 'national').
    scope: Optional[str] = None
    county_restrictions: List[str] = []
    city_restrictions: List[str] = []
    # Provider alignment & local discovery
    provider_type: Optional[str] = None
    provider_mission: Optional[str] = None
    provider_core_values: List[str] = []
    is_local: bool = False
    competition_level: str = "medium"
    target_community: Optional[str] = None
    # Employer tuition assistance, service-obligation, and vendor-platform fields
    # null = funding mechanism never stated (unknown is not 'scholarship').
    funding_type: Optional[str] = None
    employment_required: bool = False
    min_employment_tenure_months: Optional[int] = None
    annual_benefit_cap: Optional[int] = None
    benefit_coverage_model: Optional[str] = None
    partner_network: Optional[str] = None
    has_service_commitment: bool = False
    service_commitment_duration_months: Optional[int] = None
    vendor_platform: Optional[str] = None
    # C8 eligibility dimensions (record-only)
    citizenship_requirement: Optional[str] = None
    enrollment_statuses: List[str] = []
    institution_restrictions: List[str] = []
    military_affiliation_requirement: Optional[str] = None

    @field_validator("enrollment_statuses", "institution_restrictions", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        # ORM array columns read None on un-flushed objects — treat as empty.
        return v or []


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    detail_url: Optional[str] = None
    award_amount: Optional[int] = None
    deadline: Optional[date] = None
    eligible_disciplines: Optional[List[str]] = None
    eligible_credentials: Optional[List[str]] = None


class ScholarshipCreate(ScholarshipBase):
    pass


class ScholarshipOut(ScholarshipBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    # Source provenance & verification state (server-owned; never accepted
    # from client input — ScholarshipCreate deliberately lacks these fields).
    source_url: Optional[str] = None
    extraction_method: Optional[str] = None
    verification_status: str = "legacy_unverified"
    verified_fields: dict = {}
    verified_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # C8: named tracks/variants within this program
    tracks: List[TrackOut] = []


class VaultDocument(BaseModel):
    name: str
    url: str
    uploaded_at: Optional[str] = None
    type: str = "Other"  # Personal Statement, Transcript, Letter of Rec, etc.


class ChecklistItem(BaseModel):
    id: str
    text: str
    completed: bool = False


class UserScholarshipBase(BaseModel):
    status: AppStatus = AppStatus.saved
    custom_deadline_reminder: Optional[datetime] = None
    user_notes: Optional[str] = None
    application_notes: Optional[str] = None
    documents: List[VaultDocument] = []
    checklist: List[ChecklistItem] = []


class UserScholarshipCreate(UserScholarshipBase):
    scholarship_id: UUID


class UserScholarshipUpdate(BaseModel):
    status: Optional[AppStatus] = None
    custom_deadline_reminder: Optional[datetime] = None
    user_notes: Optional[str] = None
    application_notes: Optional[str] = None
    documents: Optional[List[VaultDocument]] = None
    checklist: Optional[List[ChecklistItem]] = None


class UserScholarshipOut(UserScholarshipBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    scholarship_id: UUID
    is_dismissed: bool = False
    scholarship: Optional[ScholarshipOut] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Matching & tier-gating response schemas
# ---------------------------------------------------------------------------


class MatchedScholarshipOut(BaseModel):
    scholarship_id: UUID
    title: str
    provider: str
    portal_url: str
    award_amount: Optional[int] = None
    deadline: Optional[str] = None
    score: int = Field(..., ge=0, le=100)
    missing_criteria: List[str] = []
    is_locked: bool = False
    masked_title: Optional[str] = None
    masked_provider: Optional[str] = None
    metro_restrictions: List[str] = []
    eligible_disciplines: List[str] = []
    # Employer / service-obligation informational fields (defaults keep
    # existing feed payloads backward-compatible).
    # null = funding mechanism never established — not asserted 'scholarship'.
    funding_type: Optional[str] = None
    employment_required: bool = False
    has_service_commitment: bool = False
    annual_benefit_cap: Optional[int] = None
    vendor_platform: Optional[str] = None
    # Optional detail fields populated for the preview drawer. Defaults
    # keep existing feed payloads backward-compatible.
    provider_mission: Optional[str] = None
    provider_core_values: List[str] = []
    eligible_credentials: List[str] = []
    min_gpa: Optional[float] = None
    max_sai: Optional[float] = None
    state_restrictions: List[str] = []
    is_general_major: bool = False
    # Per-bucket score composition (keys: gpa, geo, sai, affiliations,
    # local_boost). Powers the "Why am I seeing this?" popover.
    score_breakdown: Dict[str, int] = {}
    # Verification state for consumer trust display
    # ("verified" | "needs_review" | "legacy_unverified").
    verification_status: str = "legacy_unverified"
    # C8: record-only eligibility dimensions + program tracks. Defaults keep
    # payloads backward-compatible.
    citizenship_requirement: Optional[str] = None
    enrollment_statuses: List[str] = []
    institution_restrictions: List[str] = []
    military_affiliation_requirement: Optional[str] = None
    tracks: List[Dict] = []


class MatchPreviewRequest(BaseModel):
    """Partial profile submitted by the onboarding wizard for a live
    projection of how many grants (and how much funding) would match."""

    disciplines: List[str] = []
    target_credentials: List[str] = []
    primary_discipline: Optional[str] = None
    target_credential: Optional[str] = None
    clinical_phase: Optional[str] = None
    gpa: Optional[float] = Field(None, ge=0.0, le=4.0)
    state_residence: Optional[str] = Field(None, max_length=2)
    metro_area: Optional[str] = None
    sai_score: Optional[int] = None
    first_gen: bool = False
    minority_flag: bool = False
    professional_affiliations: List[str] = []
    hobbies: List[str] = []


class MatchPreviewOut(BaseModel):
    projected_count: int
    projected_funding_total: int


class MatchedFeedOut(BaseModel):
    results: List[MatchedScholarshipOut]
    total: int
    visible: int
    tier: str
    searches_used_this_week: int
    search_limit: Optional[int] = None
    reset_at: str


class UsageOut(BaseModel):
    tier: str
    searches_used_this_week: int
    search_limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_at: str
    is_premium: bool


# ---------------------------------------------------------------------------
# Calendar & .ICS
# ---------------------------------------------------------------------------


class CalendarEventOut(BaseModel):
    tracking_id: UUID
    scholarship_id: UUID
    title: str
    provider: str
    deadline: str
    status: str
    award_amount: Optional[int] = None
    custom_deadline_reminder: Optional[datetime] = None
    user_notes: Optional[str] = None


class CalendarFeedOut(BaseModel):
    feed_url: str
    feed_token: str


# ---------------------------------------------------------------------------
# Stripe billing
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    plan: str = Field(..., pattern="^(monthly|annual)$")
    success_url: str = "http://localhost:3000/?upgrade=success"
    cancel_url: str = "http://localhost:3000/?upgrade=cancelled"


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class PortalUrlResponse(BaseModel):
    url: str


class ScholarshipReportCreate(BaseModel):
    reason: str = Field(..., pattern="^(broken_link|inaccurate_deadline|expired)$")
    notes: Optional[str] = None


class ScholarshipReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scholarship_id: UUID
    reason: str
    notes: Optional[str] = None
    status: str = "open"
    created_at: Optional[datetime] = None


class CancellationFeedbackCreate(BaseModel):
    reason: str = Field(..., pattern="^(won_scholarship|too_expensive|not_enough_opportunities|finished_cycle|other)$")
    award_amount: Optional[int] = None
    comments: Optional[str] = None


class CancellationFeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reason: str
    award_amount: Optional[int] = None
    comments: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Financial Planner
# ---------------------------------------------------------------------------


class StudentCollegeBudgetBase(BaseModel):
    # Direct educational costs
    tuition_fees: int = 0
    books_supplies: int = 0
    clinical_lab_fees: int = 0
    # Living & personal costs
    housing_rent: int = 0
    food_groceries: int = 0
    utilities_wifi: int = 0
    transportation: int = 0
    health_insurance: int = 0
    personal_misc: int = 0
    # Income / resources
    family_contribution: int = 0
    work_study_wages: int = 0
    other_grants: int = 0
    # Loan configuration
    program_years: int = 4
    interest_rate: float = 7.5


class StudentCollegeBudgetUpdate(BaseModel):
    tuition_fees: Optional[int] = None
    books_supplies: Optional[int] = None
    clinical_lab_fees: Optional[int] = None
    housing_rent: Optional[int] = None
    food_groceries: Optional[int] = None
    utilities_wifi: Optional[int] = None
    transportation: Optional[int] = None
    health_insurance: Optional[int] = None
    personal_misc: Optional[int] = None
    family_contribution: Optional[int] = None
    work_study_wages: Optional[int] = None
    other_grants: Optional[int] = None
    program_years: Optional[int] = None
    interest_rate: Optional[float] = None


class FinancialPlannerOut(BaseModel):
    # Budget values
    budget: StudentCollegeBudgetBase
    # Computed totals
    total_direct_educational: int
    total_living_personal: int
    total_annual_expenses: int  # COA
    total_non_loan_income: int
    total_planned_scholarships: int
    net_unfunded_annual: int
    # Loan calculations
    estimated_total_debt: float
    monthly_loan_payment: float
    total_lifetime_interest: float
    # Planning goals
    three_x_cushion: int  # 3 * COA
    five_x_safety_buffer: int  # 5 * COA
    cushion_progress_pct: float  # funded / 3x COA * 100


# ---------------------------------------------------------------------------
# In-app AI Support Assistant
# ---------------------------------------------------------------------------


class SupportChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class SupportChatResponse(BaseModel):
    reply: str
    conversation_id: str
    turn_count: int
    turns_remaining: int
    is_escalated: bool
    message: str


class SupportEscalateRequest(BaseModel):
    conversation_id: Optional[str] = None
    subject: Optional[str] = None


class SupportEscalateResponse(BaseModel):
    ticket_id: str
    is_escalated: bool
    message: str


# ---------------------------------------------------------------------------
# Early Access / Waitlist (R3)
# ---------------------------------------------------------------------------


class WaitlistAudienceType(str, Enum):
    """Audience choices offered by the public early-access form."""

    student = "student"
    parent = "parent"
    college_staff = "college_staff"
    counselor = "counselor"
    scholarship_organization = "scholarship_organization"
    other = "other"


class WaitlistEducationType(str, Enum):
    undergraduate = "undergraduate"
    graduate = "graduate"
    professional = "professional"
    trade = "trade"
    other = "other"


_EARLY_ACCESS_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# Attribution inputs are untrusted free text: bounded so arbitrary values can
# never cause unsafe database behavior (oversized payloads, control bytes).
_ATTRIBUTION_MAX = 120
_LANDING_PAGE_MAX = 500


def _clean_optional_text(value):
    """Trim free text and strip control characters; empty -> None."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    cleaned = _CONTROL_CHARS_RE.sub("", value).strip()
    return cleaned or None


class EarlyAccessSignupRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., min_length=3, max_length=254)
    audience_type: WaitlistAudienceType
    education_type: Optional[WaitlistEducationType] = None
    # Explicit marketing/early-access consent — required, never pre-checked.
    consent: bool
    consent_source: Optional[str] = Field("early_access_form", max_length=120)
    # Acquisition attribution — channel, referral code, and UTM parameters
    # are distinct concepts and stay in distinct fields.
    referral_source: Optional[str] = Field(None, max_length=_ATTRIBUTION_MAX)
    referral_code: Optional[str] = Field(None, max_length=_ATTRIBUTION_MAX)
    referred_by: Optional[str] = Field(None, max_length=_ATTRIBUTION_MAX)
    utm_source: Optional[str] = Field(None, max_length=_ATTRIBUTION_MAX)
    utm_medium: Optional[str] = Field(None, max_length=_ATTRIBUTION_MAX)
    utm_campaign: Optional[str] = Field(None, max_length=_ATTRIBUTION_MAX)
    utm_content: Optional[str] = Field(None, max_length=_ATTRIBUTION_MAX)
    utm_term: Optional[str] = Field(None, max_length=_ATTRIBUTION_MAX)
    landing_page: Optional[str] = Field(None, max_length=_LANDING_PAGE_MAX)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        normalized = (v or "").strip().lower()
        if not _EARLY_ACCESS_EMAIL_RE.match(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized

    @field_validator("consent")
    @classmethod
    def _consent_required(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("Consent is required to join the early-access list.")
        return v

    @field_validator("first_name", mode="before")
    @classmethod
    def _clean_first_name(cls, v):
        return _clean_optional_text(v)

    @field_validator(
        "consent_source",
        "referral_source",
        "referral_code",
        "referred_by",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "landing_page",
        mode="before",
    )
    @classmethod
    def _clean_attribution(cls, v):
        return _clean_optional_text(v)


class EarlyAccessSignupResponse(BaseModel):
    status: str = "ok"
    already_registered: bool = False
    message: str

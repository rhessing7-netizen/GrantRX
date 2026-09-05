from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    primary_discipline: Optional[ClinicalDiscipline] = None
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
    primary_discipline: Optional[ClinicalDiscipline] = None
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


class ProfileOut(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: Optional[str] = None
    email: Optional[str] = None
    terms_accepted_at: Optional[datetime] = None
    privacy_accepted_at: Optional[datetime] = None
    marketing_opt_in: bool = False
    marketing_opt_in_at: Optional[datetime] = None
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
    award_amount: int = Field(..., ge=0)
    deadline: date
    eligible_disciplines: List[ClinicalDiscipline] = []
    eligible_credentials: List[str] = []
    min_gpa: float = 0.0
    max_sai: Optional[int] = None
    state_restrictions: List[str] = []
    metro_restrictions: List[str] = []
    required_affiliations: List[str] = []
    matching_tags: List[str] = []
    is_archived: bool = False
    estimated_next_cycle: Optional[date] = None
    # Provider alignment & local discovery
    provider_type: Optional[str] = None
    provider_mission: Optional[str] = None
    provider_core_values: List[str] = []
    is_local: bool = False
    target_community: Optional[str] = None


class ScholarshipCreate(ScholarshipBase):
    pass


class ScholarshipOut(ScholarshipBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


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
    award_amount: int
    deadline: str
    score: int = Field(..., ge=0, le=100)
    missing_criteria: List[str] = []
    is_locked: bool = False
    masked_title: Optional[str] = None
    masked_provider: Optional[str] = None
    metro_restrictions: List[str] = []
    eligible_disciplines: List[str] = []


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
    award_amount: int
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

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID
from sqlalchemy.orm import relationship

from ..database import Base

_CLINICAL_DISCIPLINES = [
    "pharmacy",
    "medicine",
    "nursing",
    "therapeutics_rehab",
    "diagnostic_imaging",
    "public_health_emergency",
]

_APP_STATUSES = ["saved", "in_progress", "submitted", "awarded", "archived"]
_SUBSCRIPTION_TIERS = ["free", "premium"]

ClinicalDisciplineEnum = ENUM(
    *_CLINICAL_DISCIPLINES,
    name="clinical_discipline",
    create_type=False,
)

AppStatusEnum = ENUM(
    *_APP_STATUSES,
    name="app_status",
    create_type=False,
)

SubscriptionTierEnum = ENUM(
    *_SUBSCRIPTION_TIERS,
    name="subscription_tier",
    create_type=False,
)


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Multi-select arrays (new — preferred over single-choice fields below)
    disciplines = Column(ARRAY(Text), default=list)
    target_credentials = Column(ARRAY(Text), default=list)
    # Legacy single-choice fields (kept for backward compatibility, now nullable)
    primary_discipline = Column(ClinicalDisciplineEnum, nullable=True)
    target_credential = Column(Text, nullable=True)
    clinical_phase = Column(Text, nullable=True)
    gpa = Column(Float, nullable=True)
    state_residence = Column(Text, nullable=True)
    metro_area = Column(Text, nullable=True)  # MSA name or metro slug
    sai_score = Column(Integer, nullable=True)
    first_gen = Column(Boolean, default=False)
    minority_flag = Column(Boolean, default=False)
    professional_affiliations = Column(ARRAY(Text), default=list)
    hobbies = Column(ARRAY(Text), default=list)
    subscription_tier = Column(SubscriptionTierEnum, default="free")
    searches_used_this_week = Column(Integer, default=0)
    search_cycle_reset_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    feed_token = Column(Text, unique=True, nullable=False, default=lambda: uuid.uuid4().hex)
    stripe_customer_id = Column(Text, nullable=True)
    stripe_subscription_id = Column(Text, nullable=True)
    stripe_subscription_status = Column(Text, nullable=True)
    # User identity & legal consent
    full_name = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True)
    privacy_accepted_at = Column(DateTime(timezone=True), nullable=True)
    marketing_opt_in = Column(Boolean, default=False)
    marketing_opt_in_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class Scholarship(Base):
    __tablename__ = "scholarships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    provider = Column(Text, nullable=False)
    portal_url = Column(Text, nullable=False)
    award_amount = Column(Integer, nullable=False)
    deadline = Column(Date, nullable=False)
    eligible_disciplines = Column(ARRAY(ClinicalDisciplineEnum), nullable=True)
    eligible_credentials = Column(ARRAY(Text), default=list)
    min_gpa = Column(Float, default=0.0)
    max_sai = Column(Integer, nullable=True)
    state_restrictions = Column(ARRAY(Text), default=list)
    metro_restrictions = Column(ARRAY(Text), default=list)
    required_affiliations = Column(ARRAY(Text), default=list)
    matching_tags = Column(ARRAY(Text), default=list)
    is_archived = Column(Boolean, default=False)
    estimated_next_cycle = Column(Date, nullable=True)
    # Provider alignment & local discovery fields
    provider_type = Column(String, nullable=True)
    provider_mission = Column(Text, nullable=True)
    provider_core_values = Column(ARRAY(Text), default=list)
    is_local = Column(Boolean, default=False, index=True)
    target_community = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class UserScholarship(Base):
    __tablename__ = "user_scholarships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    scholarship_id = Column(UUID(as_uuid=True), ForeignKey("scholarships.id", ondelete="CASCADE"), nullable=False)
    status = Column(AppStatusEnum, default="saved")
    is_dismissed = Column(Boolean, default=False)
    is_planned = Column(Boolean, default=False)
    target_submission_date = Column(Date, nullable=True)
    custom_deadline_reminder = Column(DateTime(timezone=True), nullable=True)
    user_notes = Column(Text, nullable=True)
    # Application Document Vault
    application_notes = Column(Text, nullable=True)
    documents = Column(JSONB, default=list)  # [{name, url, uploaded_at, type}]
    checklist = Column(JSONB, default=list)  # [{id, text, completed}]
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # ORM relationship so joinedload(UserScholarship.scholarship) works
    scholarship = relationship("Scholarship", lazy="joined")


class StudentCollegeBudget(Base):
    __tablename__ = "student_college_budgets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    # Direct educational costs
    tuition_fees = Column(Integer, default=0)
    books_supplies = Column(Integer, default=0)
    clinical_lab_fees = Column(Integer, default=0)
    # Living & personal costs
    housing_rent = Column(Integer, default=0)
    food_groceries = Column(Integer, default=0)
    utilities_wifi = Column(Integer, default=0)
    transportation = Column(Integer, default=0)
    health_insurance = Column(Integer, default=0)
    personal_misc = Column(Integer, default=0)
    # Income / resources
    family_contribution = Column(Integer, default=0)
    work_study_wages = Column(Integer, default=0)
    other_grants = Column(Integer, default=0)
    # Loan configuration
    program_years = Column(Integer, default=4)
    interest_rate = Column(Float, default=7.5)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # ORM relationship
    profile = relationship("Profile", backref="college_budget")


class ScholarshipReport(Base):
    __tablename__ = "scholarship_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scholarship_id = Column(UUID(as_uuid=True), ForeignKey("scholarships.id", ondelete="CASCADE"), nullable=False)
    reported_by = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=False)  # broken_link | inaccurate_deadline | expired
    notes = Column(Text, nullable=True)
    status = Column(Text, default="open")  # open | reviewed | resolved
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    scholarship = relationship("Scholarship", backref="reports")


class CancellationFeedback(Base):
    __tablename__ = "cancellation_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=False)  # won_scholarship | too_expensive | not_enough_opportunities | finished_cycle | other
    award_amount = Column(Integer, nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

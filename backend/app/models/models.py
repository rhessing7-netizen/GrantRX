import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
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
    # C8: canonical field-of-study code (was clinical_discipline ENUM). Text
    # storage so new disciplines never need a migration; normalization lives
    # in scrapers/utils/taxonomy.py.
    primary_discipline = Column(Text, nullable=True)
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
    has_completed_tour = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class Scholarship(Base):
    __tablename__ = "scholarships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    provider = Column(Text, nullable=False)
    portal_url = Column(Text, nullable=False)
    award_amount = Column(Integer, nullable=True)
    deadline = Column(Date, nullable=True)
    # C8: canonical field-of-study codes (was ARRAY(clinical_discipline)).
    # [] = unknown eligibility, ['any'] = explicitly unrestricted.
    eligible_disciplines = Column(ARRAY(Text), nullable=True)
    eligible_credentials = Column(ARRAY(Text), default=list)
    min_gpa = Column(Float, default=0.0)
    max_sai = Column(Integer, nullable=True)
    state_restrictions = Column(ARRAY(Text), default=list)
    metro_restrictions = Column(ARRAY(Text), default=list)
    required_affiliations = Column(ARRAY(Text), default=list)
    matching_tags = Column(ARRAY(Text), default=list)
    # Legacy compatibility mirror of lifecycle_status == 'archived'. Written
    # only via app.services.lifecycle; migration 023 installs a trigger that
    # derives it from lifecycle_status so the two cannot drift.
    is_archived = Column(Boolean, default=False)
    estimated_next_cycle = Column(Date, nullable=True)
    # Catalog lifecycle (migration 023) — authoritative publication state.
    # draft | published | stale | archived; see app.services.lifecycle.
    lifecycle_status = Column(String, nullable=False, default="published", index=True)
    # deadline_passed | dead_link | discontinued | source_removed | duplicate | manual
    archive_reason = Column(String, nullable=True)
    # Positive re-extraction from source (NULL = never observed under C3).
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    # Any check (observation or link check).
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    # Reserved for a reliable absence signal (not yet produced — see lifecycle).
    consecutive_misses = Column(Integer, nullable=False, default=0)
    # Academic criteria — general major & academic levels
    is_general_major = Column(Boolean, default=False, index=True)
    academic_levels = Column(ARRAY(Text), default=list)
    # Geographic targeting
    # NULL = geography never established; 'national' = explicitly unrestricted.
    scope = Column(String, nullable=True, index=True)
    county_restrictions = Column(ARRAY(Text), default=list)
    city_restrictions = Column(ARRAY(Text), default=list)
    # Provider alignment & local discovery fields
    provider_type = Column(String, nullable=True)
    provider_mission = Column(Text, nullable=True)
    provider_core_values = Column(ARRAY(Text), default=list)
    is_local = Column(Boolean, default=False, index=True)
    competition_level = Column(String, default="medium", index=True)
    target_community = Column(String, nullable=True)
    # Employer tuition assistance, service-obligation, and vendor-platform fields
    # NULL = funding mechanism never stated (was 'scholarship' default — same
    # unknown-vs-unrestricted defect class as scope; C8).
    funding_type = Column(String, nullable=True, index=True)
    employment_required = Column(Boolean, default=False, index=True)
    min_employment_tenure_months = Column(Integer, nullable=True)
    annual_benefit_cap = Column(Integer, nullable=True)
    benefit_coverage_model = Column(String, nullable=True)
    partner_network = Column(String, nullable=True)
    has_service_commitment = Column(Boolean, default=False, index=True)
    service_commitment_duration_months = Column(Integer, nullable=True)
    vendor_platform = Column(String, nullable=True)

    # C8 eligibility dimensions — record-only (profiles don't collect these
    # attributes yet): persisted for display/notices, never hard gates.
    citizenship_requirement = Column(String, nullable=True)
    enrollment_statuses = Column(ARRAY(Text), default=list)
    institution_restrictions = Column(ARRAY(Text), default=list)
    military_affiliation_requirement = Column(String, nullable=True)

    # C8: named tracks/variants of this program (see ScholarshipTrack).
    tracks = relationship(
        "ScholarshipTrack",
        back_populates="scholarship",
        cascade="all, delete-orphan",
        order_by="ScholarshipTrack.sort_order",
    )

    # Source provenance and factual verification
    source_url = Column(Text, nullable=True)
    extraction_method = Column(String, nullable=True)
    verification_status = Column(String, nullable=False, default="legacy_unverified", index=True)
    verified_fields = Column(JSONB, default=dict)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    # Persisted opportunity identity (migration 024 / Catalog Batch C4).
    # identity_key: unique canonical identity ("u:<url>" or "tp:<title|provider>").
    # identity_fallback_key: the tp: companion stored alongside URL identities
    # so provider URL migrations still match. Both unique-indexed.
    identity_key = Column(Text, nullable=True, index=True)
    identity_fallback_key = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_scholarships_scope_local", "scope", "is_local"),
        Index("idx_scholarships_deadline_active", "deadline", "is_archived"),
    )


class ScholarshipTrack(Base):
    """A named track/variant inside a parent funding program (C8).

    Tracks share the parent's administration and application identity — they
    never receive their own ``identity_key`` and are never matched
    independently. A track carries the fields that legitimately differ across
    tracks (eligibility, award, deadline, detail URL); everything else comes
    from the parent ``Scholarship``.
    """

    __tablename__ = "scholarship_tracks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scholarship_id = Column(
        UUID(as_uuid=True),
        ForeignKey("scholarships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(Text, nullable=False)
    detail_url = Column(Text, nullable=True)
    award_amount = Column(Integer, nullable=True)
    deadline = Column(Date, nullable=True)
    eligible_disciplines = Column(ARRAY(Text), nullable=True)
    eligible_credentials = Column(ARRAY(Text), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    scholarship = relationship("Scholarship", back_populates="tracks")

    __table_args__ = (
        Index("uq_track_parent_title", "scholarship_id", "title", unique=True),
    )


class UserScholarship(Base):
    __tablename__ = "user_scholarships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    scholarship_id = Column(UUID(as_uuid=True), ForeignKey("scholarships.id", ondelete="CASCADE"), nullable=False)
    status = Column(AppStatusEnum, default="saved")
    is_dismissed = Column(Boolean, default=False)
    is_planned = Column(Boolean, default=False)
    # Rows created solely by the dismiss endpoint to record feed-curation state.
    # They never represent a Save and are excluded from tracking/Kanban listings.
    dismiss_only = Column(Boolean, default=False, nullable=False)
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


class CrawlerSeed(Base):
    """Autonomous crawler seed queue.

    Stores both manually curated seeds (from seeds.json) and dynamically
    discovered directory hubs. The crawler pulls the next batch from this
    table and enqueues newly discovered hub URLs during traversal.
    """

    __tablename__ = "crawler_seeds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(Text, unique=True, nullable=False)
    source_name = Column(Text, nullable=True)
    category = Column(Text, default="discovered_directory")
    priority = Column(Integer, default=1)
    status = Column(Text, default="queued")  # queued | crawled | failed | quarantined | ignored
    error_count = Column(Integer, default=0)
    last_crawled_at = Column(DateTime(timezone=True), nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    discovered_from_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class CatalogSource(Base):
    """Durable source registry (C7): one row per configured authoritative
    catalog source — identity, fetch mode, deterministic scheduling, durable
    health, and persisted HTTP validators/content hashes."""

    __tablename__ = "catalog_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_key = Column(Text, nullable=False)  # unique; stable across URL moves
    name = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    category = Column(Text, default="national_association")
    primary_discipline = Column(Text, default="any")
    target_credentials = Column(JSONB, default=list)
    state_restriction = Column(Text, nullable=True)
    scraper_type = Column(Text, default="deterministic")
    enabled = Column(Boolean, default=True)
    # deterministic scheduling
    check_interval_seconds = Column(Integer, default=604800)
    peak_months = Column(JSONB, nullable=True)
    peak_interval_seconds = Column(Integer, nullable=True)
    next_check_at = Column(DateTime(timezone=True), nullable=True)
    # durable health + bounded failure info
    health = Column(Text, default="unknown")
    consecutive_failures = Column(Integer, default=0)
    consecutive_unchanged = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    last_resolved_url = Column(Text, nullable=True)
    # check history
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    last_fetch_ok_at = Column(DateTime(timezone=True), nullable=True)
    last_extracted_at = Column(DateTime(timezone=True), nullable=True)
    last_check_outcome = Column(Text, nullable=True)
    last_http_status = Column(Integer, nullable=True)
    # durable fetch metadata (C6 in-run state, promoted to durable)
    content_hash = Column(Text, nullable=True)
    extracted_hash = Column(Text, nullable=True)
    etag = Column(Text, nullable=True)
    last_modified = Column(Text, nullable=True)
    # bounded observability
    checks_total = Column(Integer, default=0)
    extractions_total = Column(Integer, default=0)
    skips_total = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SupportConversation(Base):
    """In-app AI support chat session with turn counter and escalation state."""

    __tablename__ = "support_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True)
    user_email = Column(Text, nullable=False)
    turn_count = Column(Integer, default=0)
    is_escalated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SupportTicket(Base):
    """Persisted email-escalation ticket created on exhaustion or manual request."""

    __tablename__ = "support_tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True)
    user_email = Column(Text, nullable=False)
    subject = Column(Text, nullable=False)
    conversation_summary = Column(Text, nullable=False)
    transcript = Column(JSONB, nullable=False)
    status = Column(Text, default="open")  # open | resolved | in_progress
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class WaitlistLead(Base):
    """Pre-launch early-access / waitlist lead (R3).

    The EdFintia database is the source of truth: a lead is committed here
    BEFORE any email-marketing provider sync is attempted, so a provider
    outage can never lose a signup. Duplicate submissions update profile and
    consent evidence but preserve FIRST-TOUCH acquisition attribution —
    referral_source, referral_code, referred_by, utm_*, and landing_page are
    distinct concepts and are only filled when still empty.

    ``status`` doubles as the segment column: 'waitlist' for the public
    early-access form, with room for later specialized values
    (student | parent | college | counselor | creator | campus_ambassador |
    media | nonprofit | founding_user) without schema changes.
    """

    __tablename__ = "waitlist_leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Normalized (trimmed + lowercased) before persistence; unique per lead.
    email = Column(Text, nullable=False, unique=True)
    first_name = Column(Text, nullable=False)
    # student | parent | college_staff | counselor | scholarship_organization | other
    audience_type = Column(Text, nullable=False)
    # undergraduate | graduate | professional | trade | other (optional)
    education_type = Column(Text, nullable=True)
    # waitlist | student | parent | college | counselor | creator |
    # campus_ambassador | media | nonprofit | founding_user
    status = Column(Text, nullable=False, default="waitlist", index=True)
    # First-touch acquisition attribution (never overwritten on duplicates).
    referral_source = Column(Text, nullable=True)
    referral_code = Column(Text, nullable=True)
    referred_by = Column(Text, nullable=True)
    utm_source = Column(Text, nullable=True)
    utm_medium = Column(Text, nullable=True)
    utm_campaign = Column(Text, nullable=True)
    utm_content = Column(Text, nullable=True)
    utm_term = Column(Text, nullable=True)
    landing_page = Column(Text, nullable=True)
    # Explicit consent evidence — recorded at submission time.
    consent_timestamp = Column(DateTime(timezone=True), nullable=False)
    consent_source = Column(Text, nullable=False)
    # Email-marketing provider sync state (EmailOctopus adapter, R3).
    # pending | synced | failed | skipped (provider unconfigured)
    provider_sync_status = Column(Text, nullable=False, default="pending", index=True)
    provider_synced_at = Column(DateTime(timezone=True), nullable=True)
    provider_last_error = Column(Text, nullable=True)
    # Lead -> account conversion linkage (marked on profile creation).
    converted_to_user = Column(Boolean, nullable=False, default=False)
    converted_at = Column(DateTime(timezone=True), nullable=True)
    converted_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_waitlist_leads_created_at", "created_at"),
        Index("idx_waitlist_leads_referral_source", "referral_source"),
        Index("idx_waitlist_leads_audience_type", "audience_type"),
    )

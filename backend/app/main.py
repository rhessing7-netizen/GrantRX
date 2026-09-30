import logging
import os
import secrets
from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Header, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .database import get_db, SessionLocal
from .config import API_BASE_URL, PORTAL_RETURN_URL, allowed_origins
from .middleware.auth import JWTMiddleware, User, get_current_user
from .middleware.tier_guard import (
    ACTIVE_TRACKING_STATUSES,
    FREE_ACTIVE_TRACKING_LIMIT,
    apply_tier_gating,
    consume_search,
    get_usage,
)
from .models.models import (
    CancellationFeedback,
    Profile,
    Scholarship,
    ScholarshipReport,
    StudentCollegeBudget,
    UserScholarship,
    WaitlistLead,
)
from .schemas.schemas import (
    CalendarEventOut,
    CalendarFeedOut,
    CancellationFeedbackCreate,
    CancellationFeedbackOut,
    CheckoutRequest,
    CheckoutResponse,
    EarlyAccessSignupRequest,
    EarlyAccessSignupResponse,
    FinancialPlannerOut,
    MatchedFeedOut,
    MatchedScholarshipOut,
    MatchPreviewOut,
    MatchPreviewRequest,
    PortalUrlResponse,
    ProfileCreate,
    ProfileOut,
    ProfileUpdate,
    ScholarshipCreate,
    ScholarshipOut,
    ScholarshipReportCreate,
    ScholarshipReportOut,
    StudentCollegeBudgetBase,
    StudentCollegeBudgetUpdate,
    SupportChatRequest,
    SupportChatResponse,
    SupportEscalateRequest,
    SupportEscalateResponse,
    UsageOut,
    UserScholarshipCreate,
    UserScholarshipOut,
    UserScholarshipUpdate,
)
from .services import lifecycle
from .services.email_marketing import get_email_marketing_provider, waitlist_tags_for_audience
from .services.rate_limit import SlidingWindowRateLimiter
from .services.archiver import (
    apply_staleness_policy,
    archive_expired_scholarships,
    get_archival_summary,
)
from .services.calendar_service import generate_ics_feed as generate_subscription_ics_feed, get_calendar_events
from .services.email_service import welcome_email
from .services.matcher import match_scholarships
from .services.profile_service import SubscriptionCancellationError, delete_account
from .services.stripe_service import (
    create_billing_portal_session,
    create_checkout_session,
    handle_webhook_event,
    verify_webhook_signature,
)
from .workers.ingestion import run_ingestion
from .services.export_service import (
    generate_asana_csv,
    generate_gcal_url,
    generate_ics_feed as generate_export_ics_feed,
)
from .services.outline_service import (
    EssayOutlineRequest,
    EssayOutlineResponse,
    generate_essay_outline,
)
from .services.support_service import escalate as escalate_support, handle_chat

logger = logging.getLogger(__name__)

app = FastAPI(title="EdFintia API", version="0.1.0")

app.add_middleware(JWTMiddleware)

# ---------------------------------------------------------------------------
# CORS — production origins via ALLOWED_ORIGINS env var (comma-separated).
# Falls back to localhost dev origins when not set.
# ---------------------------------------------------------------------------
_allowed_origins = allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def run_startup_archival():
    """Archive expired scholarships on application startup."""
    try:
        db = SessionLocal()
        try:
            count = archive_expired_scholarships(db)
            if count:
                logger.info("Startup archival: %d expired scholarship(s) archived", count)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Startup archival skipped: %s", exc)


@app.get("/")
@app.head("/")
async def root():
    return {"status": "healthy", "service": "EdFintia API"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/me", response_model=dict)
def me(user: User = Depends(get_current_user)):
    return {
        "user_id": str(user.id),
        "email": user.email,
        "role": user.role,
    }


@app.get("/profiles/me", response_model=ProfileOut)
def get_my_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


@app.post("/profiles", response_model=ProfileOut)
def create_profile(
    payload: ProfileCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upsert a profile. If one already exists for this user, update it."""
    from datetime import timezone

    existing = db.query(Profile).filter(Profile.id == user.id).first()

    # Map consent flags to timestamps
    now = datetime.now(timezone.utc)
    # subscription_tier is server-controlled (Stripe webhooks) — never accept
    # it from a client payload, including the model's "free" default on upsert.
    data = payload.model_dump(
        exclude={"id", "terms_accepted", "privacy_accepted", "subscription_tier"}
    )

    if payload.terms_accepted:
        data["terms_accepted_at"] = now
    if payload.privacy_accepted:
        data["privacy_accepted_at"] = now
    if payload.marketing_opt_in:
        data["marketing_opt_in_at"] = now

    if existing:
        # Update existing profile (explicit null clears whitelisted fields)
        _apply_profile_update(existing, data)
        existing.updated_at = now
        db.commit()
        db.refresh(existing)
        _mark_waitlist_conversion(db, [data.get("email"), user.email], user.id)
        return existing

    profile = Profile(id=user.id, **data)
    db.add(profile)
    db.commit()
    db.refresh(profile)

    _mark_waitlist_conversion(db, [data.get("email"), user.email], user.id)

    # Send welcome email on initial onboarding
    if profile.email:
        try:
            welcome_email(to=profile.email, name=profile.full_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Welcome email failed for %s: %s", profile.email, exc)

    return profile


# Profile columns that may be explicitly cleared by sending null in an update.
# Whitelisted to genuinely nullable optional fields so protected/non-nullable
# fields (subscription_tier, arrays, booleans) can never be nulled out.
PROFILE_CLEARABLE_FIELDS = frozenset(
    {
        "primary_discipline",
        "target_credential",
        "clinical_phase",
        "gpa",
        "state_residence",
        "metro_area",
        "sai_score",
        "full_name",
        "email",
    }
)


def _apply_profile_update(profile, data):
    """Apply PATCH-like semantics: unset keys keep existing values, explicit
    null clears whitelisted nullable fields, other explicit nulls are ignored."""
    for key, value in data.items():
        if value is not None or key in PROFILE_CLEARABLE_FIELDS:
            setattr(profile, key, value)


def _mark_waitlist_conversion(db: Session, emails, user_id: UUID) -> None:
    """Mark matching early-access leads as converted (lead -> account).

    Called when a profile is created/upserted. Best-effort and non-fatal —
    a failure here must never block profile creation.
    """
    from datetime import timezone

    normalized = {e.strip().lower() for e in emails if e}
    if not normalized:
        return
    try:
        now = datetime.now(timezone.utc)
        marked = False
        for email in normalized:
            lead = (
                db.query(WaitlistLead)
                .filter(WaitlistLead.email == email)
                .first()
            )
            if lead and not lead.converted_to_user:
                lead.converted_to_user = True
                lead.converted_at = now
                lead.converted_user_id = user_id
                lead.updated_at = now
                marked = True
        if marked:
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Waitlist conversion marking failed: %s", exc)


@app.put("/profiles", response_model=ProfileOut)
def update_profile(
    payload: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the current user's profile (partial update)."""
    from datetime import timezone

    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    now = datetime.now(timezone.utc)
    data = payload.model_dump(
        exclude={"id", "terms_accepted", "privacy_accepted", "subscription_tier"},
        exclude_unset=True,
    )

    if payload.terms_accepted:
        data["terms_accepted_at"] = now
    if payload.privacy_accepted:
        data["privacy_accepted_at"] = now
    if payload.marketing_opt_in:
        data["marketing_opt_in_at"] = now

    _apply_profile_update(profile, data)
    profile.updated_at = now
    db.commit()
    db.refresh(profile)
    return profile


@app.get("/scholarships", response_model=List[ScholarshipOut])
def list_scholarships(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dismissed_ids = {
        row[0]
        for row in db.query(UserScholarship.scholarship_id)
        .filter(
            UserScholarship.user_id == user.id,
            UserScholarship.is_dismissed == True,  # noqa: E712
        )
        .all()
    }
    # Consumer discovery surfaces published opportunities only (draft, stale,
    # and archived are excluded), and excludes needs_review records pending
    # verification clearance (E1.5). Tracked/saved history is served
    # separately by /user-scholarships and is unaffected.
    scholarships = (
        db.query(Scholarship)
        .filter(Scholarship.lifecycle_status == lifecycle.PUBLISHED)
        .filter(Scholarship.verification_status != "needs_review")
        .all()
    )
    if dismissed_ids:
        scholarships = [s for s in scholarships if s.id not in dismissed_ids]
    return scholarships


@app.post("/scholarships", response_model=ScholarshipOut, status_code=status.HTTP_201_CREATED)
def create_scholarship(
    payload: ScholarshipCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role != "service_role":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "detail": "PAYWALL_REQUIRED",
                "feature": "admin_scholarship_create",
                "upgrade_url": "/billing",
            },
        )

    data = payload.model_dump()
    # is_archived is a legacy compatibility input; lifecycle is authoritative.
    requested_archived = bool(data.pop("is_archived", False))
    scholarship = Scholarship(**data)
    # Admin-curated records are published (not observed — no last_seen_at).
    # A past deadline or an explicit archive request archives with a reason.
    if requested_archived:
        lifecycle.archive(scholarship, lifecycle.MANUAL)
    elif scholarship.deadline and scholarship.deadline < date.today():
        lifecycle.archive(scholarship, lifecycle.DEADLINE_PASSED)
    else:
        lifecycle.publish(scholarship)
    # Persisted identity (C4): a record that cannot establish a stable
    # identity must not be inserted — it could never be safely refreshed.
    from scrapers.utils.identity import compute_identity_keys

    scholarship.identity_key, scholarship.identity_fallback_key = compute_identity_keys(
        scholarship.title, scholarship.provider, scholarship.portal_url,
    )
    if not scholarship.identity_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot determine a stable opportunity identity from title/provider/portal_url.",
        )
    db.add(scholarship)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An opportunity with this identity already exists.",
        )
    db.refresh(scholarship)
    return scholarship


@app.get("/user-scholarships", response_model=List[UserScholarshipOut])
def list_user_scholarships(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(UserScholarship)
        .options(joinedload(UserScholarship.scholarship))
        .filter(
            UserScholarship.user_id == user.id,
            UserScholarship.dismiss_only == False,  # noqa: E712
        )
        .all()
    )


@app.post("/user-scholarships", response_model=UserScholarshipOut, status_code=status.HTTP_201_CREATED)
def track_scholarship(
    payload: UserScholarshipCreate,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Idempotent save: a user can only have one tracking record per
    # scholarship (enforced by UNIQUE(user_id, scholarship_id)). Re-saving
    # returns the existing record instead of raising a 500.
    existing = (
        db.query(UserScholarship)
        .filter(
            UserScholarship.user_id == user.id,
            UserScholarship.scholarship_id == payload.scholarship_id,
        )
        .first()
    )
    if existing:
        response.status_code = status.HTTP_200_OK
        # The same free-tier active-application cap applies when an existing
        # row transitions INTO an active status via re-save — otherwise a
        # saved/dismissed row could bypass the limit that PATCH enforces.
        current_status = getattr(existing.status, "value", existing.status)
        requested = getattr(payload.status, "value", payload.status)
        entering_active = (
            requested in ACTIVE_TRACKING_STATUSES
            and current_status not in ACTIVE_TRACKING_STATUSES
        )
        if entering_active:
            profile = db.query(Profile).filter(Profile.id == user.id).first()
            if profile and profile.subscription_tier != "premium":
                active_count = (
                    db.query(UserScholarship)
                    .filter(
                        UserScholarship.user_id == user.id,
                        UserScholarship.id != existing.id,
                        UserScholarship.status.in_(ACTIVE_TRACKING_STATUSES),
                    )
                    .count()
                )
                if active_count >= FREE_ACTIVE_TRACKING_LIMIT:
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail={
                            "detail": "PAYWALL_REQUIRED",
                            "feature": "kanban_tracking",
                            "upgrade_url": "/billing",
                            "limit": FREE_ACTIVE_TRACKING_LIMIT,
                        },
                    )
        if getattr(existing, "dismiss_only", False):
            # Converting a dismiss-only marker into a real tracking record:
            # the user is explicitly saving this scholarship now.
            existing.dismiss_only = False
            existing.is_dismissed = False
            existing.status = payload.status
            existing.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(existing)
        return existing

    # Free-tier paywall: users may save any number of scholarships, but only
    # In Progress + Submitted count as active applications. Enforce this rule
    # server-side so API clients cannot bypass the browser check.
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if (
        profile
        and profile.subscription_tier != "premium"
        and payload.status.value in ACTIVE_TRACKING_STATUSES
    ):
        active_count = (
            db.query(UserScholarship)
            .filter(
                UserScholarship.user_id == user.id,
                UserScholarship.status.in_(ACTIVE_TRACKING_STATUSES),
            )
            .count()
        )
        if active_count >= FREE_ACTIVE_TRACKING_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "detail": "PAYWALL_REQUIRED",
                    "feature": "kanban_tracking",
                    "upgrade_url": "/billing",
                    "limit": FREE_ACTIVE_TRACKING_LIMIT,
                },
            )

    data = payload.model_dump()
    tracking = UserScholarship(user_id=user.id, **data)
    db.add(tracking)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request created the row between the existence check and
        # the insert. The UNIQUE constraint is the final integrity boundary;
        # return the winning row so the save is still idempotent.
        db.rollback()
        existing = (
            db.query(UserScholarship)
            .filter(
                UserScholarship.user_id == user.id,
                UserScholarship.scholarship_id == payload.scholarship_id,
            )
            .first()
        )
        if existing:
            response.status_code = status.HTTP_200_OK
            return existing
        raise
    db.refresh(tracking)
    return tracking


@app.patch("/user-scholarships/{tracking_id}", response_model=UserScholarshipOut)
def update_tracking(
    tracking_id: UUID,
    payload: UserScholarshipUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracking = (
        db.query(UserScholarship)
        .filter(UserScholarship.id == tracking_id, UserScholarship.user_id == user.id)
        .first()
    )
    if not tracking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracking not found")

    update_data = payload.model_dump(exclude_unset=True)

    # Enforce the same active-application limit on status transitions. Saved,
    # Awarded, and Archived do not consume an active slot.
    requested_status = update_data.get("status")
    current_status = tracking.status.value if hasattr(tracking.status, "value") else tracking.status
    requested_status_value = (
        requested_status.value if hasattr(requested_status, "value") else requested_status
    )
    entering_active = (
        requested_status_value in ACTIVE_TRACKING_STATUSES
        and current_status not in ACTIVE_TRACKING_STATUSES
    )
    if entering_active:
        profile = db.query(Profile).filter(Profile.id == user.id).first()
        if profile and profile.subscription_tier != "premium":
            active_count = (
                db.query(UserScholarship)
                .filter(
                    UserScholarship.user_id == user.id,
                    UserScholarship.id != tracking.id,
                    UserScholarship.status.in_(ACTIVE_TRACKING_STATUSES),
                )
                .count()
            )
            if active_count >= FREE_ACTIVE_TRACKING_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "detail": "PAYWALL_REQUIRED",
                        "feature": "kanban_tracking",
                        "upgrade_url": "/billing",
                        "limit": FREE_ACTIVE_TRACKING_LIMIT,
                    },
                )

    for field, value in update_data.items():
        setattr(tracking, field, value)
    tracking.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(tracking)
    return tracking


@app.delete("/user-scholarships/{tracking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tracking(
    tracking_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracking = (
        db.query(UserScholarship)
        .filter(UserScholarship.id == tracking_id, UserScholarship.user_id == user.id)
        .first()
    )
    if not tracking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracking not found")
    db.delete(tracking)
    db.commit()
    return None


@app.post("/ingest")
def ingest_sources(user: User = Depends(get_current_user)):
    if user.role != "service_role":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "detail": "PAYWALL_REQUIRED",
                "feature": "admin_ingest",
                "upgrade_url": "/billing",
            },
        )
    run_ingestion()
    return {"status": "ingestion queued"}


# ---------------------------------------------------------------------------
# Matching engine + tier-gated feed
# ---------------------------------------------------------------------------


@app.post("/api/scholarships/match-preview", response_model=MatchPreviewOut)
def preview_match_count(
    body: MatchPreviewRequest,
    db: Session = Depends(get_db),
):
    """Live matching projection for the onboarding wizard.

    Runs the real matcher (including discipline/credential hard gates)
    against a transient, never-persisted Profile built from the partial
    onboarding form, and returns the number of eligible grants plus the
    summed award pool. Public: the wizard runs before a profile exists.
    """
    transient = Profile(
        disciplines=body.disciplines,
        target_credentials=body.target_credentials,
        primary_discipline=body.primary_discipline,
        target_credential=body.target_credential,
        clinical_phase=body.clinical_phase,
        gpa=body.gpa,
        state_residence=body.state_residence,
        metro_area=body.metro_area,
        sai_score=body.sai_score,
        first_gen=body.first_gen,
        minority_flag=body.minority_flag,
        professional_affiliations=body.professional_affiliations,
        hobbies=body.hobbies,
    )
    scholarships = (
        db.query(Scholarship)
        .filter(Scholarship.lifecycle_status == lifecycle.PUBLISHED)
        .filter(Scholarship.verification_status != "needs_review")
        .all()
    )
    results = match_scholarships(transient, scholarships)
    return MatchPreviewOut(
        projected_count=len(results),
        projected_funding_total=sum(r.award_amount or 0 for r in results),
    )


@app.get("/api/scholarships/matched", response_model=MatchedFeedOut)
def get_matched_scholarships(
    query: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    # Only consume a search quota when the user submits an explicit,
    # non-empty keyword search. Faceted filter changes, match refreshes,
    # pagination, sorting, and modal opens do NOT consume a search.
    keyword = (query or "").strip()
    if keyword:
        consume_search(profile, db)

    scholarships = db.query(Scholarship).all()

    # Exclude scholarships the user has dismissed from the feed
    dismissed_ids = {
        row[0]
        for row in db.query(UserScholarship.scholarship_id)
        .filter(
            UserScholarship.user_id == user.id,
            UserScholarship.is_dismissed == True,  # noqa: E712
        )
        .all()
    }
    if dismissed_ids:
        scholarships = [s for s in scholarships if s.id not in dismissed_ids]

    raw_results = match_scholarships(profile, scholarships)

    # Apply keyword filtering on top of the matched results
    if keyword:
        q_lower = keyword.lower()
        raw_results = [
            r for r in raw_results
            if q_lower in r.title.lower()
            or q_lower in r.provider.lower()
            or any(q_lower in c.lower() for c in r.missing_criteria)
        ]

    gated = apply_tier_gating(profile, raw_results)

    usage = get_usage(profile)

    return MatchedFeedOut(
        results=[MatchedScholarshipOut(**r.__dict__) for r in gated],
        total=len(raw_results),
        visible=sum(1 for r in gated if not r.is_locked),
        tier=profile.subscription_tier,
        searches_used_this_week=usage["searches_used_this_week"],
        search_limit=usage["search_limit"],
        reset_at=usage["reset_at"],
    )


@app.post("/api/scholarships/{scholarship_id}/dismiss")
def dismiss_scholarship(
    scholarship_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hide a scholarship from the user's Discovery Feed.

    Upserts a UserScholarship record with is_dismissed=True.
    """
    scholarship = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not scholarship:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scholarship not found")

    existing = (
        db.query(UserScholarship)
        .filter(
            UserScholarship.user_id == user.id,
            UserScholarship.scholarship_id == scholarship_id,
        )
        .first()
    )
    if existing:
        existing.is_dismissed = True
        existing.updated_at = datetime.utcnow()
    else:
        # Dismissal is a discovery preference, not a pipeline state. The row is
        # marked dismiss_only so it is excluded from Saved/Kanban listings and
        # deleted by undismiss instead of becoming a phantom "saved" record.
        db.add(
            UserScholarship(
                user_id=user.id,
                scholarship_id=scholarship_id,
                is_dismissed=True,
                dismiss_only=True,
            )
        )
    db.commit()
    return {"status": "dismissed", "scholarship_id": str(scholarship_id)}


@app.post("/api/scholarships/{scholarship_id}/undismiss")
def undismiss_scholarship(
    scholarship_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reverse a dismissal so the scholarship reappears in the feed."""
    existing = (
        db.query(UserScholarship)
        .filter(
            UserScholarship.user_id == user.id,
            UserScholarship.scholarship_id == scholarship_id,
        )
        .first()
    )
    if not existing or not existing.is_dismissed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dismissal not found")

    if getattr(existing, "dismiss_only", False):
        # The row exists solely to record the dismissal — undo removes it
        # entirely so no phantom "saved" tracking record is left behind.
        db.delete(existing)
    else:
        # A real tracking record: restore discovery visibility while
        # preserving its saved/in-progress/submitted status.
        existing.is_dismissed = False
        existing.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "restored", "scholarship_id": str(scholarship_id)}


@app.get("/api/user/usage", response_model=UsageOut)
def get_user_usage(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    usage = get_usage(profile)
    # Persist any cycle reset that may have occurred
    db.commit()
    return UsageOut(**usage)


# ---------------------------------------------------------------------------
# Calendar & .ICS feed
# ---------------------------------------------------------------------------


@app.get("/api/calendar/events", response_model=List[CalendarEventOut])
def get_calendar_events_endpoint(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    events = get_calendar_events(db, user.id)
    return [CalendarEventOut(**ev) for ev in events]


@app.get("/api/calendar/feed.ics")
def get_ics_feed(
    token: str,
    db: Session = Depends(get_db),
):
    """Public .ics subscription endpoint authenticated by feed_token.

    No JWT required — the token in the query string authenticates the feed.
    Compatible with Apple Calendar, Google Calendar, and Outlook.
    """
    ics_content = generate_subscription_ics_feed(db, token)
    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={
            "Content-Disposition": "attachment; filename=grantrx-scholarships.ics",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@app.get("/api/calendar/feed-url", response_model=CalendarFeedOut)
def get_feed_url(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the .ics subscription URL + token for the authenticated user."""
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    base = API_BASE_URL
    feed_url = f"{base}/api/calendar/feed.ics?token={profile.feed_token}"
    return CalendarFeedOut(feed_url=feed_url, feed_token=profile.feed_token)


@app.post("/api/calendar/feed-token/rotate", response_model=CalendarFeedOut)
def rotate_feed_token(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rotate the private calendar subscription token.

    Rotation immediately invalidates the previous public .ics URL.  Users can
    use this if a subscription URL is accidentally shared or otherwise
    exposed.
    """
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    profile.feed_token = secrets.token_hex(24)
    db.commit()
    db.refresh(profile)

    feed_url = f"{API_BASE_URL}/api/calendar/feed.ics?token={profile.feed_token}"
    return CalendarFeedOut(feed_url=feed_url, feed_token=profile.feed_token)


# ---------------------------------------------------------------------------
# Stripe billing
# ---------------------------------------------------------------------------


@app.post("/api/billing/create-checkout-session", response_model=CheckoutResponse)
def create_checkout(
    payload: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    if profile.subscription_tier == "premium":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already subscribed to Premium",
        )

    try:
        session = create_checkout_session(
            user_id=str(user.id),
            email=profile.email or user.email,
            plan=payload.plan,
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Stripe error: {exc}") from exc

    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


@app.post("/api/billing/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Stripe webhook endpoint. Verifies signature and processes events.

    This endpoint is public (no JWT) — authentication is via Stripe's
    webhook signature header.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        event = verify_webhook_signature(payload, signature)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Stripe webhook signature verification failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature") from exc

    result = handle_webhook_event(db, event)
    return {"received": True, **result}


@app.post("/api/v1/billing/portal", response_model=PortalUrlResponse)
def create_billing_portal(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Stripe Customer Portal session for self-service billing management.

    Allows premium users to update their card, view invoices, or cancel
    their subscription without contacting support.
    """
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    if not profile.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe customer account found. Upgrade to Premium first.",
        )

    return_url = PORTAL_RETURN_URL
    try:
        session = create_billing_portal_session(
            customer_id=profile.stripe_customer_id,
            return_url=return_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Stripe error: {exc}") from exc

    return PortalUrlResponse(url=session.url)


@app.post(
    "/api/v1/billing/cancellation-feedback",
    response_model=CancellationFeedbackOut,
    status_code=201,
)
def submit_cancellation_feedback(
    payload: CancellationFeedbackCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Collect exit-survey feedback when a user initiates cancellation.

    Stored for churn analysis and product improvement. The user is then
    redirected to the Stripe Billing Portal by the frontend.
    """
    feedback = CancellationFeedback(
        user_id=user.id,
        reason=payload.reason,
        award_amount=payload.award_amount,
        comments=payload.comments,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


# ---------------------------------------------------------------------------
# Scholarship issue reporting (crowdsourced)
# ---------------------------------------------------------------------------


@app.post(
    "/api/v1/scholarships/{scholarship_id}/report",
    response_model=ScholarshipReportOut,
    status_code=201,
)
def report_scholarship(
    scholarship_id: UUID,
    payload: ScholarshipReportCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Report inaccurate information for a scholarship (broken link, wrong deadline, expired).

    Creates a record in the scholarship_reports table for admin review.
    """
    scholarship = (
        db.query(Scholarship)
        .filter(Scholarship.id == scholarship_id)
        .first()
    )
    if not scholarship:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scholarship not found")

    report = ScholarshipReport(
        scholarship_id=scholarship_id,
        reported_by=user.id,
        reason=payload.reason,
        notes=payload.notes,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


# ---------------------------------------------------------------------------
# Account deletion (self-serve, GDPR/CCPA-friendly)
# ---------------------------------------------------------------------------


@app.delete("/api/v1/profile/me")
def delete_my_account(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete the authenticated user's account and all personal data.

    Cancels any active Stripe subscription, removes user_scholarships,
    student_college_budgets, scholarship_reports filed by the user, the
    profile row, and Supabase Auth credentials (when configured).
    """
    try:
        result = delete_account(db, str(user.id))
    except SubscriptionCancellationError as exc:
        # Do not delete an account while an active recurring charge may remain.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if result.get("status") == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["message"])
    return result


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


def _verify_admin_key(x_admin_key: Optional[str]) -> None:
    """Verify the X-Admin-Key header against the GRANTRX_ADMIN_KEY env var."""
    expected = os.getenv("GRANTRX_ADMIN_KEY")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints disabled — GRANTRX_ADMIN_KEY not set",
        )
    if not x_admin_key or x_admin_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Admin-Key header",
        )


def _run_scrape_background(
    category: Optional[str],
    limit: Optional[int],
    state: Optional[str],
) -> None:
    """Background task that runs the scraper pipeline synchronously."""
    import asyncio

    from scrapers.runner import run_pipeline

    try:
        asyncio.run(
            run_pipeline(
                target="all",
                dry_run=False,
                persist=True,
                category=category if category else None,
                state=state if state else None,
                limit=limit,
            )
        )
        logger.info("Background scrape completed (category=%s, limit=%s, state=%s)", category, limit, state)
    except Exception as exc:  # noqa: BLE001
        logger.error("Background scrape failed: %s", exc)


@app.post("/api/admin/scrape/trigger")
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    category: Optional[str] = None,
    limit: Optional[int] = None,
    state: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None),
):
    """Trigger a scraper pipeline run in the background.

    Protected by the X-Admin-Key header (compared against GRANTRX_ADMIN_KEY env var).

    Query params:
        category: Filter by source category (e.g. "national_association")
        limit: Max number of sources to process
        state: Filter by 2-letter state code
    """
    _verify_admin_key(x_admin_key)

    background_tasks.add_task(_run_scrape_background, category, limit, state)
    return {
        "status": "queued",
        "message": "Scrape task initiated in background",
        "params": {"category": category, "limit": limit, "state": state},
    }


@app.post("/api/admin/archive-expired")
def trigger_archival(
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Manually trigger archival of expired scholarships (and the opt-in
    staleness pass when CATALOG_STALENESS_ENABLED is set)."""
    _verify_admin_key(x_admin_key)
    count = archive_expired_scholarships(db)
    staled = apply_staleness_policy(db)
    return {"status": "ok", "archived": count, "staled": staled}


@app.get("/api/admin/archival-summary")
def archival_summary(
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Return a summary of scholarship archival state."""
    _verify_admin_key(x_admin_key)
    return get_archival_summary(db)


@app.get("/api/admin/source-registry/summary")
def source_registry_summary(
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Counts of registered catalog sources by health + due-now total (C7)."""
    _verify_admin_key(x_admin_key)
    from scrapers.source_registry import registry_summary

    return registry_summary(db)


@app.get("/api/admin/source-registry")
def source_registry_list(
    health: Optional[str] = None,
    enabled: Optional[bool] = None,
    due_only: bool = False,
    limit: int = 200,
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Bounded source-registry listing for operators (C7).

    Exposes scheduling/health metadata only — never page bodies, headers,
    or other sensitive diagnostics."""
    _verify_admin_key(x_admin_key)
    from datetime import datetime as _dt

    from app.models.models import CatalogSource

    q = db.query(CatalogSource)
    if health:
        q = q.filter(CatalogSource.health == health)
    if enabled is not None:
        q = q.filter(CatalogSource.enabled.is_(enabled))
    if due_only:
        q = q.filter(
            (CatalogSource.next_check_at.is_(None))
            | (CatalogSource.next_check_at <= _dt.utcnow())
        )
    rows = q.order_by(CatalogSource.next_check_at.asc().nullsfirst()).limit(
        min(max(limit, 1), 500)).all()
    return [
        {
            "source_key": r.source_key,
            "name": r.name,
            "url": r.url,
            "category": r.category,
            "enabled": r.enabled,
            "health": r.health,
            "next_check_at": r.next_check_at.isoformat() if r.next_check_at else None,
            "last_attempted_at": r.last_attempted_at.isoformat() if r.last_attempted_at else None,
            "last_fetch_ok_at": r.last_fetch_ok_at.isoformat() if r.last_fetch_ok_at else None,
            "last_extracted_at": r.last_extracted_at.isoformat() if r.last_extracted_at else None,
            "last_check_outcome": r.last_check_outcome,
            "last_http_status": r.last_http_status,
            "consecutive_failures": r.consecutive_failures,
            "consecutive_unchanged": r.consecutive_unchanged,
            "checks_total": r.checks_total,
            "extractions_total": r.extractions_total,
            "skips_total": r.skips_total,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Financial Planner — College Budget & Debt Simulator
# ---------------------------------------------------------------------------


def _compute_financial_planner(
    budget: StudentCollegeBudget,
    total_planned_scholarships: int,
) -> FinancialPlannerOut:
    """Run the financial planner calculation engine."""
    total_direct_educational = (
        budget.tuition_fees + budget.books_supplies + budget.clinical_lab_fees
    )
    total_living_personal = (
        budget.housing_rent + budget.food_groceries + budget.utilities_wifi
        + budget.transportation + budget.health_insurance + budget.personal_misc
    )
    total_annual_expenses = total_direct_educational + total_living_personal

    total_non_loan_income = (
        budget.family_contribution + budget.work_study_wages + budget.other_grants
    )

    net_unfunded_annual = max(
        0,
        total_annual_expenses - (total_planned_scholarships + total_non_loan_income),
    )

    # 10-year (120 months) amortization
    principal = net_unfunded_annual * budget.program_years
    monthly_rate = budget.interest_rate / 100.0 / 12.0
    num_payments = 120

    if principal > 0 and monthly_rate > 0:
        factor = (1 + monthly_rate) ** num_payments
        monthly_payment = principal * (monthly_rate * factor) / (factor - 1)
    elif principal > 0:
        monthly_payment = principal / num_payments
    else:
        monthly_payment = 0.0

    total_paid = monthly_payment * num_payments
    total_lifetime_interest = max(0.0, total_paid - principal)

    three_x_cushion = total_annual_expenses * 3
    five_x_safety_buffer = total_annual_expenses * 5
    total_funding = total_planned_scholarships + total_non_loan_income
    cushion_progress_pct = (
        round(total_funding / three_x_cushion * 100, 1) if three_x_cushion > 0 else 0.0
    )

    return FinancialPlannerOut(
        budget=StudentCollegeBudgetBase(
            tuition_fees=budget.tuition_fees,
            books_supplies=budget.books_supplies,
            clinical_lab_fees=budget.clinical_lab_fees,
            housing_rent=budget.housing_rent,
            food_groceries=budget.food_groceries,
            utilities_wifi=budget.utilities_wifi,
            transportation=budget.transportation,
            health_insurance=budget.health_insurance,
            personal_misc=budget.personal_misc,
            family_contribution=budget.family_contribution,
            work_study_wages=budget.work_study_wages,
            other_grants=budget.other_grants,
            program_years=budget.program_years,
            interest_rate=budget.interest_rate,
        ),
        total_direct_educational=total_direct_educational,
        total_living_personal=total_living_personal,
        total_annual_expenses=total_annual_expenses,
        total_non_loan_income=total_non_loan_income,
        total_planned_scholarships=total_planned_scholarships,
        net_unfunded_annual=net_unfunded_annual,
        estimated_total_debt=round(principal, 2),
        monthly_loan_payment=round(monthly_payment, 2),
        total_lifetime_interest=round(total_lifetime_interest, 2),
        three_x_cushion=three_x_cushion,
        five_x_safety_buffer=five_x_safety_buffer,
        cushion_progress_pct=cushion_progress_pct,
    )


@app.get("/api/v1/financial-planner/budget", response_model=FinancialPlannerOut)
def get_financial_planner(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the user's college budget and computed financial planner metrics."""
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if not profile:
        # Budgets are FK'd to profiles — a JWT user without a profile must get
        # a clean 404, not an FK violation 500.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    budget = (
        db.query(StudentCollegeBudget)
        .filter(StudentCollegeBudget.user_id == user.id)
        .first()
    )
    if not budget:
        budget = StudentCollegeBudget(user_id=user.id)
        db.add(budget)
        db.commit()
        db.refresh(budget)

    # Aggregate total planned scholarships
    planned = (
        db.query(UserScholarship)
        .filter(
            UserScholarship.user_id == user.id,
            UserScholarship.is_planned == True,  # noqa: E712
        )
        .all()
    )
    total_planned_scholarships = sum(
        (t.scholarship.award_amount or 0) for t in planned if t.scholarship
    )

    return _compute_financial_planner(budget, total_planned_scholarships)


@app.put("/api/v1/financial-planner/budget", response_model=FinancialPlannerOut)
def update_financial_planner(
    update: StudentCollegeBudgetUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the user's college budget values and loan settings."""
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    budget = (
        db.query(StudentCollegeBudget)
        .filter(StudentCollegeBudget.user_id == user.id)
        .first()
    )
    if not budget:
        budget = StudentCollegeBudget(user_id=user.id)
        db.add(budget)

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(budget, field, value)
    budget.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(budget)

    # Aggregate total planned scholarships
    planned = (
        db.query(UserScholarship)
        .filter(
            UserScholarship.user_id == user.id,
            UserScholarship.is_planned == True,  # noqa: E712
        )
        .all()
    )
    total_planned_scholarships = sum(
        (t.scholarship.award_amount or 0) for t in planned if t.scholarship
    )

    return _compute_financial_planner(budget, total_planned_scholarships)


# ---------------------------------------------------------------------------
# Calendar & Asana Multi-Export
# ---------------------------------------------------------------------------


@app.get("/api/v1/planner/export/gcal-url/{scholarship_id}")
def get_gcal_url(
    scholarship_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a Google Calendar web intent URL for a single scholarship."""
    scholarship = (
        db.query(Scholarship)
        .filter(Scholarship.id == scholarship_id)
        .first()
    )
    if not scholarship:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    if not scholarship.deadline:
        raise HTTPException(status_code=400, detail="Scholarship has no deadline")

    url = generate_gcal_url(
        scholarship_title=scholarship.title,
        deadline=scholarship.deadline,
        portal_url=scholarship.portal_url,
        provider=scholarship.provider,
    )
    return {"url": url}


@app.get("/api/v1/planner/export/asana-csv")
def export_asana_csv(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download planned scholarships as an Asana-compatible CSV file."""
    planned = (
        db.query(UserScholarship)
        .options(joinedload(UserScholarship.scholarship))
        .filter(
            UserScholarship.user_id == user.id,
            UserScholarship.is_planned == True,  # noqa: E712
        )
        .all()
    )

    items = []
    for t in planned:
        s = t.scholarship
        if not s:
            continue
        items.append({
            "title": s.title,
            "deadline": s.deadline.isoformat() if s.deadline else "",
            "portal_url": s.portal_url or "",
            "provider": s.provider or "",
            "award_amount": s.award_amount or 0,
            "status": t.status,
        })

    csv_content = generate_asana_csv(items)

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="grantrx_planner_asana.csv"',
        },
    )


@app.get("/api/v1/planner/export/calendar.ics")
def export_ics_calendar(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download all tracked scholarships as an .ics calendar feed."""
    tracked = (
        db.query(UserScholarship)
        .options(joinedload(UserScholarship.scholarship))
        .filter(
            UserScholarship.user_id == user.id,
            UserScholarship.is_dismissed == False,  # noqa: E712
            UserScholarship.status != "archived",
        )
        .all()
    )

    items = []
    for t in tracked:
        s = t.scholarship
        if not s:
            continue
        items.append({
            "title": s.title,
            "deadline": s.deadline.isoformat() if s.deadline else "",
            "portal_url": s.portal_url or "",
            "provider": s.provider or "",
            "award_amount": s.award_amount or 0,
        })

    ics_content = generate_export_ics_feed(items)

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={
            "Content-Disposition": 'attachment; filename="grantrx_deadlines.ics"',
        },
    )


# ---------------------------------------------------------------------------
# AI Statement Coach — 4-Part Essay Outliner
# ---------------------------------------------------------------------------


class OutlineRequestBody(BaseModel):
    """Request body for the essay outline endpoint."""
    prompt: str = ""
    word_limit: Optional[int] = 500
    user_discipline: Optional[str] = None
    user_credential: Optional[str] = None
    lived_experience_notes: Optional[str] = None
    work_volunteer_experience: Optional[str] = None
    academic_topics_of_interest: Optional[str] = None


@app.post("/api/v1/scholarships/{scholarship_id}/outline", response_model=EssayOutlineResponse)
async def generate_outline(
    scholarship_id: UUID,
    body: OutlineRequestBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a 4-part essay outline tailored to the scholarship provider's mission."""
    scholarship = (
        db.query(Scholarship)
        .filter(Scholarship.id == scholarship_id)
        .first()
    )
    if not scholarship:
        raise HTTPException(status_code=404, detail="Scholarship not found")

    # Pull profile for discipline/credential if not provided in body
    profile = db.query(Profile).filter(Profile.id == user.id).first()

    request = EssayOutlineRequest(
        scholarship_title=scholarship.title,
        provider=scholarship.provider,
        prompt=body.prompt,
        word_limit=body.word_limit,
        provider_mission=scholarship.provider_mission,
        provider_core_values=scholarship.provider_core_values or [],
        user_discipline=body.user_discipline or (
            profile.disciplines[0] if profile and profile.disciplines else None
        ),
        user_credential=body.user_credential or (
            profile.target_credentials[0] if profile and profile.target_credentials else None
        ),
        lived_experience_notes=body.lived_experience_notes,
        work_volunteer_experience=body.work_volunteer_experience,
        academic_topics_of_interest=body.academic_topics_of_interest,
    )

    outline = await generate_essay_outline(request)
    if outline is None:
        raise HTTPException(
            status_code=503,
            detail="Essay outline service unavailable. Please try again later.",
        )
    return outline


# ---------------------------------------------------------------------------
# In-app AI Support Assistant
# ---------------------------------------------------------------------------


@app.post("/api/v1/support/chat", response_model=SupportChatResponse)
async def support_chat(
    body: SupportChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Process one turn of the in-app AI support assistant.

    Enforces a 4-turn limit per conversation with terminal email escalation.
    Jailbreak and off-topic queries are rejected before reaching the LLM.
    """
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    tier = profile.subscription_tier if profile else "free"
    user_email = profile.email if profile and profile.email else (user.email or "unknown@grantrx.com")

    result = await handle_chat(
        db=db,
        user_id=str(user.id),
        user_email=user_email,
        tier=str(tier),
        message=body.message,
        conversation_id=body.conversation_id,
    )
    return SupportChatResponse(**result)


@app.post("/api/v1/support/escalate", response_model=SupportEscalateResponse)
async def support_escalate(
    body: SupportEscalateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly trigger human email escalation before exhausting turns."""
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    tier = profile.subscription_tier if profile else "free"
    user_email = profile.email if profile and profile.email else (user.email or "unknown@grantrx.com")

    # Reconstruct a minimal transcript from the most recent ticket if present.
    from .models.models import SupportTicket

    prior = (
        db.query(SupportTicket)
        .filter(SupportTicket.user_id == user.id)
        .order_by(SupportTicket.created_at.desc())
        .first()
    )
    transcript = list(prior.transcript or []) if prior else [
        {"role": "user", "content": "User requested human support."}
    ]

    ticket = escalate_support(
        db=db,
        user_id=str(user.id),
        user_email=user_email,
        tier=str(tier),
        transcript=transcript,
        subject=body.subject,
    )
    return SupportEscalateResponse(
        ticket_id=str(ticket.id),
        is_escalated=True,
        message="A support ticket and email transcript have been sent to our team.",
    )


# ---------------------------------------------------------------------------
# Early Access / Waitlist signup (R3)
# ---------------------------------------------------------------------------

# Public-endpoint abuse protection. Per-process sliding window; keys are
# client hosts held in memory only — never persisted for attribution.
early_access_rate_limiter = SlidingWindowRateLimiter(
    limit=int(os.getenv("EARLY_ACCESS_RATE_LIMIT", "10")),
    window_seconds=int(os.getenv("EARLY_ACCESS_RATE_WINDOW_SECONDS", "300")),
)

# First-touch attribution: these fields are only ever filled while empty —
# a resubmission must not erase the original acquisition source. Channel,
# referral code, and UTM parameters remain distinct fields.
_FIRST_TOUCH_FIELDS = (
    "referral_source",
    "referral_code",
    "referred_by",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "landing_page",
)


@app.post(
    "/api/v1/early-access",
    response_model=EarlyAccessSignupResponse,
    status_code=201,
)
def early_access_signup(
    payload: EarlyAccessSignupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Public early-access / waitlist signup.

    DB-FIRST: the lead is validated, normalized, and committed to the EdFintia
    database BEFORE any email-marketing provider sync is attempted. A provider
    failure (or missing provider configuration) after a successful commit
    still returns success — the lead is never lost, and the sync state is
    recorded on the lead for later retry. Duplicate submissions are
    idempotent: they refresh profile/consent fields and fill still-empty
    attribution, preserve first-touch values and created_at, and return a
    friendly success rather than a conflict error.
    """
    client_host = request.client.host if request.client else "unknown"
    if not early_access_rate_limiter.allow(client_host):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again in a few minutes.",
        )

    from datetime import timezone

    now = datetime.now(timezone.utc)
    email = payload.email  # already trimmed + lowercased by the request schema
    consent_source = payload.consent_source or "early_access_form"
    attribution = {field: getattr(payload, field) for field in _FIRST_TOUCH_FIELDS}

    lead = db.query(WaitlistLead).filter(WaitlistLead.email == email).first()
    already_registered = lead is not None

    if lead is None:
        lead = WaitlistLead(
            email=email,
            first_name=payload.first_name,
            audience_type=payload.audience_type.value,
            education_type=(
                payload.education_type.value if payload.education_type else None
            ),
            status="waitlist",
            consent_timestamp=now,
            consent_source=consent_source,
            provider_sync_status="pending",
            **attribution,
        )
        db.add(lead)
    else:
        lead.first_name = payload.first_name
        lead.audience_type = payload.audience_type.value
        if payload.education_type is not None:
            lead.education_type = payload.education_type.value
        for field, value in attribution.items():
            if value and not getattr(lead, field):
                setattr(lead, field, value)
        lead.consent_timestamp = now
        lead.consent_source = consent_source
        lead.updated_at = now

    try:
        db.commit()
    except IntegrityError:
        # Concurrent first-time signup with the same email — the unique index
        # is the final integrity boundary. Re-read and treat as a duplicate.
        db.rollback()
        lead = db.query(WaitlistLead).filter(WaitlistLead.email == email).first()
        if lead is None:
            raise
        already_registered = True

    if already_registered:
        response.status_code = status.HTTP_200_OK
    db.refresh(lead)

    # An account already exists for this email -> the lead is converted.
    if not lead.converted_to_user:
        existing_account = (
            db.query(Profile).filter(Profile.email == email).first()
        )
        if existing_account:
            lead.converted_to_user = True
            lead.converted_at = datetime.now(timezone.utc)
            lead.converted_user_id = existing_account.id
            db.commit()

    # Provider sync AFTER durable save. Any failure is recorded on the lead
    # for later retry and is never surfaced to the visitor.
    provider = get_email_marketing_provider()
    try:
        if provider is None:
            if lead.provider_sync_status == "pending":
                lead.provider_sync_status = "skipped"
        else:
            result = provider.subscribe_or_update(
                email=lead.email,
                first_name=lead.first_name,
                tags=waitlist_tags_for_audience(lead.audience_type),
            )
            lead.provider_sync_status = result.status
            if result.status == "synced":
                lead.provider_synced_at = datetime.now(timezone.utc)
                lead.provider_last_error = None
            elif result.status == "failed":
                lead.provider_last_error = result.error
                logger.warning(
                    "Waitlist provider sync failed for lead %s: %s",
                    getattr(lead, "id", "?"),
                    result.error,
                )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning(
            "Waitlist provider sync errored for lead %s: %s",
            getattr(lead, "id", "?"),
            exc,
        )

    return EarlyAccessSignupResponse(
        status="ok",
        already_registered=already_registered,
        message=(
            "You're already on the early-access list — watch your inbox for updates."
            if already_registered
            else "You're on the early-access list — watch your inbox for updates."
        ),
    )

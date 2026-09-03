import logging
import os
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Header, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload

from .database import get_db, SessionLocal
from .middleware.auth import JWTMiddleware, User, get_current_user
from .middleware.tier_guard import (
    FREE_ACTIVE_TRACKING_LIMIT,
    apply_tier_gating,
    consume_search,
    get_usage,
)
from .models.models import Profile, Scholarship, UserScholarship
from .schemas.schemas import (
    CalendarEventOut,
    CalendarFeedOut,
    CheckoutRequest,
    CheckoutResponse,
    MatchedFeedOut,
    MatchedScholarshipOut,
    ProfileCreate,
    ProfileOut,
    ProfileUpdate,
    ScholarshipCreate,
    ScholarshipOut,
    UsageOut,
    UserScholarshipCreate,
    UserScholarshipOut,
    UserScholarshipUpdate,
)
from .services.archiver import archive_expired_scholarships, get_archival_summary
from .services.calendar_service import generate_ics_feed, get_calendar_events
from .services.matcher import match_scholarships
from .services.stripe_service import (
    create_checkout_session,
    handle_webhook_event,
    verify_webhook_signature,
)
from .workers.ingestion import run_ingestion

logger = logging.getLogger(__name__)

app = FastAPI(title="GrantRx API", version="0.1.0")

app.add_middleware(JWTMiddleware)

# ---------------------------------------------------------------------------
# CORS — production origins via ALLOWED_ORIGINS env var (comma-separated).
# Falls back to localhost dev origins when not set.
# ---------------------------------------------------------------------------
_default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:60201",
    "https://grant-rx.vercel.app",
    "https://*.vercel.app",
]
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
if _allowed_origins_env.strip():
    _allowed_origins = [
        o.strip() for o in _allowed_origins_env.split(",") if o.strip()
    ]
else:
    _allowed_origins = _default_origins

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
    data = payload.model_dump(exclude={"id", "terms_accepted", "privacy_accepted"})

    if payload.terms_accepted:
        data["terms_accepted_at"] = now
    if payload.privacy_accepted:
        data["privacy_accepted_at"] = now
    if payload.marketing_opt_in:
        data["marketing_opt_in_at"] = now

    if existing:
        # Update existing profile
        for key, value in data.items():
            if value is not None:
                setattr(existing, key, value)
        existing.updated_at = now
        db.commit()
        db.refresh(existing)
        return existing

    profile = Profile(id=user.id, **data)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


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
    data = payload.model_dump(exclude={"id", "terms_accepted", "privacy_accepted"}, exclude_unset=True)

    if payload.terms_accepted:
        data["terms_accepted_at"] = now
    if payload.privacy_accepted:
        data["privacy_accepted_at"] = now
    if payload.marketing_opt_in:
        data["marketing_opt_in_at"] = now

    for key, value in data.items():
        if value is not None:
            setattr(profile, key, value)
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
    scholarships = db.query(Scholarship).filter(Scholarship.is_archived == False).all()
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
    scholarship = Scholarship(**data)
    db.add(scholarship)
    db.commit()
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
        .filter(UserScholarship.user_id == user.id)
        .all()
    )


@app.post("/user-scholarships", response_model=UserScholarshipOut, status_code=status.HTTP_201_CREATED)
def track_scholarship(
    payload: UserScholarshipCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Free-tier paywall: max 3 active (non-archived) tracked applications
    profile = db.query(Profile).filter(Profile.id == user.id).first()
    if profile and profile.subscription_tier != "premium":
        active_count = (
            db.query(UserScholarship)
            .filter(
                UserScholarship.user_id == user.id,
                UserScholarship.status != "archived",
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
                },
            )

    data = payload.model_dump()
    tracking = UserScholarship(user_id=user.id, **data)
    db.add(tracking)
    db.commit()
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

    for field, value in payload.model_dump(exclude_unset=True).items():
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
        db.add(
            UserScholarship(
                user_id=user.id,
                scholarship_id=scholarship_id,
                is_dismissed=True,
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
    ics_content = generate_ics_feed(db, token)
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

    base = os.getenv("APP_BASE_URL", "http://localhost:8000")
    feed_url = f"{base}/api/calendar/feed.ics?token={profile.feed_token}"
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
    """Manually trigger archival of expired scholarships."""
    _verify_admin_key(x_admin_key)
    count = archive_expired_scholarships(db)
    return {"status": "ok", "archived": count}


@app.get("/api/admin/archival-summary")
def archival_summary(
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Return a summary of scholarship archival state."""
    _verify_admin_key(x_admin_key)
    return get_archival_summary(db)

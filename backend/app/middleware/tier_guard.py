"""Free-tier access control: search quota and paywall.

Rules:
  - Free tier: max 3 explicit non-empty keyword searches per 7-day rolling
    cycle. The 4th attempt -> HTTP 402 with the paywall payload.
    Every legitimately matched result is fully visible to every tier —
    there is no subscription-based result masking, blurring, or locking.
  - Premium tier: unlimited searches.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models.models import Profile

FREE_SEARCH_LIMIT = 3
SEARCH_CYCLE_DAYS = 7
FREE_ACTIVE_TRACKING_LIMIT = 3  # max active Kanban apps for free tier
ACTIVE_TRACKING_STATUSES = ("in_progress", "submitted")


def _utcnow() -> datetime:
    """Return a timezone-aware UTC datetime (compatible with DB columns)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Quota helpers
# ---------------------------------------------------------------------------


def _cycle_reset_at(profile: Profile) -> datetime:
    """Return the timestamp at which the current 7-day search cycle resets."""
    base = profile.search_cycle_reset_at or _utcnow()
    # Ensure base is timezone-aware
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(days=SEARCH_CYCLE_DAYS)


def _maybe_reset_cycle(profile: Profile, now: datetime | None = None) -> bool:
    """If the rolling cycle has elapsed, reset the counter.

    Returns True if a reset occurred.
    """
    now = now or _utcnow()
    # Ensure now is timezone-aware
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if profile.search_cycle_reset_at is None:
        profile.search_cycle_reset_at = now
        return False
    reset_at = profile.search_cycle_reset_at
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=timezone.utc)
    if now >= reset_at + timedelta(days=SEARCH_CYCLE_DAYS):
        profile.searches_used_this_week = 0
        profile.search_cycle_reset_at = now
        return True
    return False


def get_usage(profile: Profile, now: datetime | None = None) -> dict:
    """Return a usage summary for the user."""
    now = now or _utcnow()
    _maybe_reset_cycle(profile, now)

    is_premium = profile.subscription_tier == "premium"
    limit = None if is_premium else FREE_SEARCH_LIMIT
    used = profile.searches_used_this_week or 0
    reset_at = _cycle_reset_at(profile)

    return {
        "tier": profile.subscription_tier,
        "searches_used_this_week": used,
        "search_limit": limit,
        "remaining": (limit - used) if limit is not None else None,
        "reset_at": reset_at.isoformat(),
        "is_premium": is_premium,
    }


def consume_search(profile: Profile, db: Session, now: datetime | None = None) -> None:
    """Increment the search counter for free users. Raises HTTP 402 if over limit.

    Premium users are a no-op.
    """
    now = now or _utcnow()
    _maybe_reset_cycle(profile, now)

    if profile.subscription_tier == "premium":
        return

    used = profile.searches_used_this_week or 0
    if used >= FREE_SEARCH_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "detail": "PAYWALL_SEARCH_LIMIT_REACHED",
                "feature": "keyword_search",
                "upgrade_url": "/billing",
                "limit": FREE_SEARCH_LIMIT,
                "used": used,
            },
        )

    profile.searches_used_this_week = used + 1
    db.commit()

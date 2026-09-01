"""Free-tier access control: search quota, paywall, and result masking.

Rules:
  - Free tier: max 10 searches per 7-day rolling cycle.
    * 11th attempt -> HTTP 402 with upgrade_required payload.
    * Top 3 results are fully visible; results 4+ are masked
      (title/provider hidden, `is_locked: true`, no portal_url).
  - Premium tier: unlimited searches, no masking.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models.models import Profile
from ..services.matcher import MatchResult

FREE_SEARCH_LIMIT = 10
SEARCH_CYCLE_DAYS = 7
FREE_VISIBLE_RESULTS = 3
FREE_ACTIVE_TRACKING_LIMIT = 3  # max active (non-archived) Kanban apps for free tier


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
                "detail": "PAYWALL_REQUIRED",
                "feature": "keyword_search",
                "upgrade_url": "/billing",
            },
        )

    profile.searches_used_this_week = used + 1
    db.commit()


# ---------------------------------------------------------------------------
# Result masking
# ---------------------------------------------------------------------------


def _mask_title(title: str) -> str:
    """Obfuscate a scholarship title for locked free-tier results."""
    if not title:
        return "██████████"
    # Keep first word, mask the rest
    parts = title.split()
    if len(parts) <= 1:
        return title[0] + " " + "█" * max(6, len(title) - 2)
    return parts[0] + " " + " ".join("█" * max(4, len(p)) for p in parts[1:])


def _mask_provider(provider: str) -> str:
    if not provider:
        return "██████████"
    return provider[0] + " " + "█" * max(4, len(provider) - 1)


def apply_tier_gating(
    profile: Profile,
    results: List[MatchResult],
) -> List[MatchResult]:
    """Mask free-tier results beyond the top N. Premium users see everything."""
    if profile.subscription_tier == "premium":
        return results

    masked: List[MatchResult] = []
    for idx, r in enumerate(results):
        if idx < FREE_VISIBLE_RESULTS:
            masked.append(r)
        else:
            masked.append(
                MatchResult(
                    scholarship_id=r.scholarship_id,
                    title=r.title,
                    provider=r.provider,
                    portal_url="",  # hide application link
                    award_amount=r.award_amount,
                    deadline=r.deadline,
                    score=r.score,
                    missing_criteria=r.missing_criteria,
                    is_locked=True,
                    masked_title=_mask_title(r.title),
                    masked_provider=_mask_provider(r.provider),
                )
            )
    return masked

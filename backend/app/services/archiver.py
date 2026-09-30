"""Nightly deadline archival service.

Archives (lifecycle ``archived`` / reason ``deadline_passed``) every
not-yet-archived opportunity whose deadline has passed, and sets
`estimated_next_cycle` to one year after the deadline (for recurring annual
awards). Transitions go through ``app.services.lifecycle`` so the legacy
``is_archived`` mirror stays in sync.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.services import lifecycle

logger = logging.getLogger(__name__)


def archive_expired_scholarships(db: Session) -> int:
    """Archive all non-archived scholarships whose deadline is earlier than today.

    Args:
        db: SQLAlchemy session.

    Returns:
        Number of scholarships archived.
    """
    from app.models.models import Scholarship

    today = date.today()
    rows = (
        db.query(Scholarship)
        .filter(Scholarship.deadline < today, Scholarship.lifecycle_status != lifecycle.ARCHIVED)
        .all()
    )
    count = 0
    now = datetime.now(timezone.utc)
    for s in rows:
        lifecycle.archive(s, lifecycle.DEADLINE_PASSED)
        s.updated_at = now
        count += 1
        logger.info("Archived expired scholarship: '%s' (deadline %s)", s.title, s.deadline)

    if count:
        db.commit()
        logger.info("Archived %d expired scholarship(s)", count)
    else:
        logger.debug("No expired scholarships to archive")

    return count


def apply_staleness_policy(db: Session, policy: lifecycle.StalenessPolicy | None = None) -> int:
    """Mark published records stale per the (opt-in) freshness policy.

    Disabled unless CATALOG_STALENESS_ENABLED is set: observation coverage is
    still partial, so automatic staling is an owner decision. Records never
    observed under C3 semantics (last_seen_at NULL) are never staled.
    """
    from app.models.models import Scholarship

    policy = policy or lifecycle.staleness_policy_from_env()
    if not policy.enabled:
        return 0
    rows = db.query(Scholarship).filter(Scholarship.lifecycle_status == lifecycle.PUBLISHED).all()
    count = sum(1 for s in rows if lifecycle.apply_staleness(s, policy))
    if count:
        db.commit()
        logger.info("Marked %d scholarship(s) stale", count)
    return count


def get_archival_summary(db: Session) -> dict:
    """Return a summary of archival/lifecycle state for monitoring use."""
    from app.models.models import Scholarship

    today = date.today()
    total = db.query(Scholarship).count()
    by_status = {
        status: db.query(Scholarship).filter(Scholarship.lifecycle_status == status).count()
        for status in lifecycle.LIFECYCLE_STATUSES
    }
    expired_but_active = (
        db.query(Scholarship)
        .filter(Scholarship.deadline < today, Scholarship.lifecycle_status != lifecycle.ARCHIVED)
        .count()
    )
    return {
        "total": total,
        # "active" retains its historical meaning: consumer-discoverable.
        "active": by_status[lifecycle.PUBLISHED],
        "archived": by_status[lifecycle.ARCHIVED],
        "expired_but_not_archived": expired_but_active,
        "lifecycle": by_status,
    }

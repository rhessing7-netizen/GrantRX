"""Nightly deadline archival service.

Flips `is_archived = True` for any active scholarship whose deadline has passed,
and sets `estimated_next_cycle` to one year after the deadline (for recurring
annual awards).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def archive_expired_scholarships(db: Session) -> int:
    """Archive all active scholarships whose deadline is earlier than today.

    Sets `is_archived = True` and `estimated_next_cycle = deadline + 1 year`
    for each expired scholarship. Commits the transaction.

    Args:
        db: SQLAlchemy session.

    Returns:
        Number of scholarships archived.
    """
    from app.models.models import Scholarship
    from scrapers.utils.normalize import add_one_year

    today = date.today()
    rows = (
        db.query(Scholarship)
        .filter(Scholarship.deadline < today, Scholarship.is_archived == False)  # noqa: E712
        .all()
    )
    count = 0
    now = datetime.now(timezone.utc)
    for s in rows:
        s.is_archived = True
        s.estimated_next_cycle = add_one_year(s.deadline)
        s.updated_at = now
        count += 1
        logger.info("Archived expired scholarship: '%s' (deadline %s)", s.title, s.deadline)

    if count:
        db.commit()
        logger.info("Archived %d expired scholarship(s)", count)
    else:
        logger.debug("No expired scholarships to archive")

    return count


def get_archival_summary(db: Session) -> dict:
    """Return a summary of archival state for monitoring/dashboard use."""
    from app.models.models import Scholarship

    today = date.today()
    total = db.query(Scholarship).count()
    active = db.query(Scholarship).filter(Scholarship.is_archived == False).count()  # noqa: E712
    archived = db.query(Scholarship).filter(Scholarship.is_archived == True).count()  # noqa: E712
    expired_but_active = (
        db.query(Scholarship)
        .filter(Scholarship.deadline < today, Scholarship.is_archived == False)  # noqa: E712
        .count()
    )
    return {
        "total": total,
        "active": active,
        "archived": archived,
        "expired_but_not_archived": expired_but_active,
    }

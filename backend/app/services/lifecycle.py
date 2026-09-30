"""Authoritative opportunity lifecycle model (Catalog Batch C3).

Lifecycle states
----------------
``draft``      Not yet publishable. No current ingestion path produces drafts;
               the state exists so a stricter publication policy can be
               introduced later without another schema change.
``published``  Eligible for consumer discovery (feed, list, match preview).
``stale``      Not positively observed within the freshness policy window.
               Hidden from discovery; republished on the next observation.
``archived``   Removed from discovery with a machine-readable ``archive_reason``.

Lifecycle and verification are independent dimensions: owner policy keeps
``needs_review`` / ``legacy_unverified`` records publishable with a
"Verification pending" indicator, so nothing here consults verification.

``is_archived`` is a legacy compatibility column. ``lifecycle_status`` is
authoritative; every transition below writes both, and migration 023 installs
a trigger that derives ``is_archived`` from ``lifecycle_status`` so the two
cannot drift even if a future writer forgets.

Observation semantics
---------------------
``last_seen_at``      the opportunity was positively re-extracted from its
                      source (a real observation).
``last_checked_at``   something about the record was checked (observation or
                      a link check). A link check is NOT an observation.
``consecutive_misses`` reserved for a reliable absence signal. The current
                      pipeline extracts one opportunity per page and cannot
                      tell "this known opportunity was expected but absent",
                      so nothing increments it yet (C5/C7 will). ``record_miss``
                      exists for that future caller.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

DRAFT = "draft"
PUBLISHED = "published"
STALE = "stale"
ARCHIVED = "archived"
LIFECYCLE_STATUSES = (DRAFT, PUBLISHED, STALE, ARCHIVED)

DEADLINE_PASSED = "deadline_passed"
DEAD_LINK = "dead_link"
DISCONTINUED = "discontinued"
SOURCE_REMOVED = "source_removed"
DUPLICATE = "duplicate"
MANUAL = "manual"
ARCHIVE_REASONS = (DEADLINE_PASSED, DEAD_LINK, DISCONTINUED, SOURCE_REMOVED, DUPLICATE, MANUAL)

# Reasons an automated refresh may reverse, given the right evidence.
# Anything else (manual, discontinued, duplicate, source_removed) is sticky.
_AUTO_RECOVERABLE = {DEADLINE_PASSED, DEAD_LINK}


# ---------------------------------------------------------------------------
# Staleness policy (configurable, disabled by default)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StalenessPolicy:
    enabled: bool = False
    max_days_unseen: int = 180
    max_consecutive_misses: int = 3


def staleness_policy_from_env() -> StalenessPolicy:
    """Read the staleness policy from environment variables.

    CATALOG_STALENESS_ENABLED (default "false") — automatic staling is an
    owner decision because observation coverage is still partial (one
    opportunity per page; not every source is scheduled).
    """
    return StalenessPolicy(
        enabled=os.getenv("CATALOG_STALENESS_ENABLED", "false").strip().lower() in ("1", "true", "yes"),
        max_days_unseen=int(os.getenv("CATALOG_STALE_AFTER_DAYS", "180")),
        max_consecutive_misses=int(os.getenv("CATALOG_STALE_AFTER_MISSES", "3")),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def current_status(s) -> str:
    """Return the authoritative lifecycle status for a scholarship object.

    Objects that have not been assigned a lifecycle yet (pre-flush ORM
    instances, pre-023 rows seen by older code) fall back to the legacy
    ``is_archived`` flag.
    """
    status = getattr(s, "lifecycle_status", None)
    if isinstance(status, str) and status in LIFECYCLE_STATUSES:
        return status
    return ARCHIVED if getattr(s, "is_archived", False) is True else PUBLISHED


def is_discoverable(s) -> bool:
    """True when the opportunity may appear in consumer discovery.

    Lifecycle AND verification are consulted (E1.5): a ``needs_review``
    record stays persisted and administratively accessible, but must not
    reach matching/feed/search until its verification is cleared. Lifecycle
    remains authoritative for publish/stale/archive; verification is an
    independent consumer-visibility condition, not a lifecycle state.
    """
    if current_status(s) != PUBLISHED:
        return False
    return getattr(s, "verification_status", None) != "needs_review"


def _set_status(s, status: str, reason: Optional[str]) -> None:
    s.lifecycle_status = status
    s.archive_reason = reason
    s.is_archived = status == ARCHIVED  # legacy compatibility mirror


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def publish(s) -> None:
    _set_status(s, PUBLISHED, None)


def archive(s, reason: str, *, today: Optional[date] = None) -> None:
    """Archive with a machine-readable reason."""
    if reason not in ARCHIVE_REASONS:
        raise ValueError(f"unknown archive reason: {reason!r}")
    _set_status(s, ARCHIVED, reason)
    if reason == DEADLINE_PASSED and getattr(s, "deadline", None):
        from scrapers.utils.normalize import add_one_year

        s.estimated_next_cycle = add_one_year(s.deadline)


def mark_stale(s) -> None:
    _set_status(s, STALE, None)


def record_observation(s, *, now: Optional[datetime] = None) -> None:
    """The opportunity was positively re-extracted from its source."""
    now = now or _now()
    s.last_seen_at = now
    s.last_checked_at = now
    s.consecutive_misses = 0


def record_check(s, *, now: Optional[datetime] = None) -> None:
    """Something about the record was checked (e.g. a link check).

    Deliberately does not touch ``last_seen_at``: a reachable URL is not
    evidence that the opportunity itself is still offered.
    """
    s.last_checked_at = now or _now()


def record_miss(s, *, now: Optional[datetime] = None) -> None:
    """Reserved for a reliable absence signal (see module docstring)."""
    s.last_checked_at = now or _now()
    s.consecutive_misses = int(getattr(s, "consecutive_misses", 0) or 0) + 1


def initialize_new(s, *, today: Optional[date] = None, now: Optional[datetime] = None) -> None:
    """Initial lifecycle for a newly ingested opportunity.

    New extractions are observations. Past deadline → archived; otherwise
    published (pending-verification records remain publishable by policy).
    """
    today = today or date.today()
    record_observation(s, now=now)
    deadline = getattr(s, "deadline", None)
    if deadline and deadline < today:
        archive(s, DEADLINE_PASSED)
    else:
        publish(s)


def apply_refresh(
    s,
    *,
    destination_verified: bool,
    today: Optional[date] = None,
    now: Optional[datetime] = None,
) -> None:
    """Lifecycle transition after an existing opportunity is re-extracted.

    Args:
        destination_verified: the persisted portal URL was confirmed live AND
            opportunity-specific during this run. Required to reverse a
            ``dead_link`` archive.

    Rules:
      * Every refresh is an observation (last_seen/last_checked, misses=0).
      * A past deadline archives (``deadline_passed``) from any state.
      * ``archived/deadline_passed`` republishes only with an explicit future
        deadline (a genuine new cycle). A NULL deadline is not evidence of a
        new cycle.
      * ``archived/dead_link`` republishes only with destination evidence.
      * Other archive reasons are never reversed automatically.
      * ``stale`` republishes: an observation is exactly what stale lacked.
      * ``draft`` stays draft: publication policy, not ingestion, promotes it.
    """
    today = today or date.today()
    record_observation(s, now=now)
    status = current_status(s)
    reason = getattr(s, "archive_reason", None)
    deadline = getattr(s, "deadline", None)
    deadline_past = bool(deadline and deadline < today)

    if status == ARCHIVED:
        if reason not in _AUTO_RECOVERABLE and isinstance(reason, str):
            return  # sticky (manual / discontinued / duplicate / source_removed)
        if reason == DEAD_LINK:
            if destination_verified and not deadline_past:
                publish(s)
            return
        # deadline_passed, or a legacy archive with no recorded reason
        if deadline and not deadline_past:
            publish(s)
        return

    if deadline_past:
        archive(s, DEADLINE_PASSED)
        return
    if status == STALE:
        publish(s)
    elif status != DRAFT:
        # published (or unassigned legacy object) — keep/normalize published
        publish(s)


def apply_staleness(s, policy: StalenessPolicy, *, now: Optional[datetime] = None) -> bool:
    """Mark a published record stale when the freshness policy is exceeded.

    Only records that have a real observation timestamp can age out; rows
    that were never observed under C3 semantics (``last_seen_at IS NULL``)
    are not staled on the basis of a fabricated observation date.
    Returns True when the record transitioned.
    """
    if not policy.enabled or current_status(s) != PUBLISHED:
        return False
    now = now or _now()
    misses = int(getattr(s, "consecutive_misses", 0) or 0)
    last_seen = getattr(s, "last_seen_at", None)
    too_many_misses = misses >= policy.max_consecutive_misses
    too_old = bool(last_seen and last_seen < now - timedelta(days=policy.max_days_unseen))
    if too_many_misses or too_old:
        mark_stale(s)
        return True
    return False

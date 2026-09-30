"""Durable source registry & scheduling (Catalog Batch C7).

One authoritative control plane for configured catalog sources. It answers:

  what sources exist -> which are enabled -> when is each due -> what is its
  health -> did its content change -> should extraction run again?

Design rules:

- sources.json remains the authoring surface; ``sync_sources`` imports it
  into ``catalog_sources`` idempotently (same key+url -> update in place,
  preserving health/scheduling/fetch state).
- Health is semantically safe: a transient failure is never death, robots
  denial is not a broken site, and a 404/410 means "this URL is gone" — the
  provider may merely have moved the page, so it escalates to
  ``needs_url_review`` (a human decision) rather than retiring the source.
- Scheduling is deterministic: every enabled source gets a next_check_at.
  Base interval slows for repeatedly unchanged pages, shortens during
  configured peak months, and transient failures use bounded backoff that
  never quarantines.
- Unchanged-content skip: a page whose content hash matches the hash at its
  last successful extraction does not pay for another LLM call; its
  opportunities' ``last_seen_at`` is still advanced so C3 observations stay
  correct. A forced re-extraction interval bounds detail-page drift.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from .fetch_policy import (
    OUTCOME_ACCESS_DENIED,
    OUTCOME_INVALID_URL,
    OUTCOME_NETWORK_ERROR,
    OUTCOME_NOT_MODIFIED,
    OUTCOME_OK,
    OUTCOME_PERMANENT_HTTP,
    OUTCOME_ROBOTS_DENIED,
    OUTCOME_ROBOTS_UNAVAILABLE,
    OUTCOME_TIMEOUT,
    OUTCOME_TRANSIENT_HTTP,
    FetchResult,
)
from .sources import SourceConfig, load_sources

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Health states
# ---------------------------------------------------------------------------

HEALTH_UNKNOWN = "unknown"                      # imported, never checked
HEALTH_HEALTHY = "healthy"
HEALTH_REDIRECTED = "redirected_or_moved"       # page resolves via redirect
HEALTH_PERMANENT_NOT_FOUND = "permanent_not_found"  # definitive 4xx this check
HEALTH_TRANSIENT = "transient_failure"          # network/5xx/timeout — retryable
HEALTH_ROBOTS_DENIED = "robots_denied"
HEALTH_ROBOTS_UNAVAILABLE = "robots_unavailable"
HEALTH_ACCESS_DENIED = "access_denied"           # HTTP 403 refusal — never URL death
HEALTH_NEEDS_URL_REVIEW = "needs_url_review"    # manual owner action required
HEALTH_RETIRED = "retired"                      # owner-disabled; never scheduled

HEALTH_STATES = {
    HEALTH_UNKNOWN, HEALTH_HEALTHY, HEALTH_REDIRECTED, HEALTH_PERMANENT_NOT_FOUND,
    HEALTH_TRANSIENT, HEALTH_ROBOTS_DENIED, HEALTH_ROBOTS_UNAVAILABLE,
    HEALTH_ACCESS_DENIED, HEALTH_NEEDS_URL_REVIEW, HEALTH_RETIRED,
}

# Health states the scheduler never selects automatically.
UNSCHEDULED_HEALTHS = {HEALTH_NEEDS_URL_REVIEW, HEALTH_RETIRED}

# ---------------------------------------------------------------------------
# Scheduling policy (env-tunable, deterministic)
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    import os

    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def base_interval_seconds() -> int:
    return _env_int("SOURCE_CHECK_INTERVAL_SECONDS", 7 * 86400)


def peak_interval_seconds() -> int:
    return _env_int("SOURCE_PEAK_INTERVAL_SECONDS", 3 * 86400)


def max_interval_seconds() -> int:
    return _env_int("SOURCE_MAX_INTERVAL_SECONDS", 28 * 86400)


def unchanged_slow_after() -> int:
    """Consecutive unchanged checks before the interval lengthens."""
    return _env_int("SOURCE_UNCHANGED_SLOW_AFTER", 4)


def unchanged_slowest_after() -> int:
    return _env_int("SOURCE_UNCHANGED_SLOWEST_AFTER", 8)


def force_reextract_seconds() -> int:
    """Even an unchanged page is re-extracted this often — detail-page and
    link drift are not visible in the listing hash (C3 observation safety)."""
    return _env_int("SOURCE_FORCE_REEXTRACT_SECONDS", 30 * 86400)


def permanent_review_threshold() -> int:
    """Consecutive permanent 4xx checks before needs_url_review."""
    return _env_int("SOURCE_PERMANENT_REVIEW_THRESHOLD", 2)


def robots_recheck_seconds() -> int:
    """Robots policies change — denied/unavailable re-enters normal rotation."""
    return _env_int("SOURCE_ROBOTS_RECHECK_SECONDS", 7 * 86400)


# Bounded transient retry (mirrors crawler_seeds semantics): after the last
# step the delay holds at 72h — a transient failure NEVER quarantines.
TRANSIENT_BACKOFF = (
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(hours=24),
    timedelta(hours=72),
)


def transient_retry_delay(failures: int) -> timedelta:
    index = max(0, min(failures - 1, len(TRANSIENT_BACKOFF) - 1))
    return TRANSIENT_BACKOFF[index]


def base_interval_for(src, now: datetime) -> timedelta:
    """The scheduled interval for a source: peak-month override, then
    unchanged-content slowdown, both capped at the max interval."""
    interval = src.check_interval_seconds or base_interval_seconds()
    peak_months = src.peak_months or []
    if src.peak_interval_seconds and now.month in peak_months:
        interval = min(interval, src.peak_interval_seconds)
    streak = src.consecutive_unchanged or 0
    if streak >= unchanged_slowest_after():
        interval *= 4
    elif streak >= unchanged_slow_after():
        interval *= 2
    return timedelta(seconds=min(interval, max_interval_seconds()))


# ---------------------------------------------------------------------------
# Identity keys
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:80] or "source"


def source_key_for(name: str, url: str, taken: set) -> str:
    """Deterministic stable key: slug(name), disambiguated by a short URL
    hash on collision so two different sources never share a key."""
    base = slugify(name)
    if base not in taken:
        return base
    suffix = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    key = f"{base}-{suffix}"
    n = 2
    while key in taken:  # pathological: two same-named sources, same hash prefix
        key = f"{base}-{suffix}{n}"
        n += 1
    return key


# ---------------------------------------------------------------------------
# Outcome -> health classification (pure)
# ---------------------------------------------------------------------------

_TRANSIENT_OUTCOMES = {
    OUTCOME_TRANSIENT_HTTP, OUTCOME_TIMEOUT, OUTCOME_NETWORK_ERROR,
}


def classify_health(current_health: str, result: FetchResult) -> str:
    """Map a fetch outcome to the source's new health state.

    Semantics:
      ok + redirect            -> redirected_or_moved (a working check)
      ok, no redirect          -> healthy
      304                      -> health unchanged (a working check)
      permanent 4xx            -> permanent_not_found; if ALREADY
                                  permanent_not_found the URL is confirmed
                                  stale -> needs_url_review (manual action)
      transient                -> transient_failure (never death)
      robots denied/unavail    -> matching robots state (not a failure)
      403 access denied        -> access_denied (a refusal, never URL death;
                                  repeated 403s stay access_denied — they can
                                  never escalate into 404-style stale review)
      invalid configured URL   -> needs_url_review (config defect)
    """
    if result.outcome == OUTCOME_OK:
        if result.final_url:
            return HEALTH_REDIRECTED
        return HEALTH_HEALTHY
    if result.outcome == OUTCOME_NOT_MODIFIED:
        return current_health if current_health in HEALTH_STATES else HEALTH_HEALTHY
    if result.outcome == OUTCOME_PERMANENT_HTTP:
        if current_health == HEALTH_PERMANENT_NOT_FOUND:
            return HEALTH_NEEDS_URL_REVIEW
        return HEALTH_PERMANENT_NOT_FOUND
    if result.outcome == OUTCOME_ACCESS_DENIED:
        return HEALTH_ACCESS_DENIED
    if result.outcome in _TRANSIENT_OUTCOMES:
        return HEALTH_TRANSIENT
    if result.outcome == OUTCOME_ROBOTS_DENIED:
        return HEALTH_ROBOTS_DENIED
    if result.outcome == OUTCOME_ROBOTS_UNAVAILABLE:
        return HEALTH_ROBOTS_UNAVAILABLE
    if result.outcome == OUTCOME_INVALID_URL:
        return HEALTH_NEEDS_URL_REVIEW
    return HEALTH_TRANSIENT


def next_check_for(src, new_health: str, now: datetime) -> Optional[datetime]:
    """Deterministic next-check time, or None when the source leaves the
    automatic schedule (needs_url_review / retired)."""
    if new_health in UNSCHEDULED_HEALTHS:
        return None
    if new_health == HEALTH_TRANSIENT:
        # apply_check has already incremented consecutive_failures.
        return now + transient_retry_delay(src.consecutive_failures or 1)
    if new_health in (HEALTH_ROBOTS_DENIED, HEALTH_ROBOTS_UNAVAILABLE,
                      HEALTH_ACCESS_DENIED):
        return now + timedelta(seconds=robots_recheck_seconds())
    return now + base_interval_for(src, now)


# ---------------------------------------------------------------------------
# LLM-skip decision
# ---------------------------------------------------------------------------


def extraction_pending(src) -> bool:
    """True when the last successfully extracted content differs from the
    last fetched content — i.e. there is content on record that never made
    it through extraction."""
    return (src.extracted_hash or "") != (src.content_hash or "")


def should_extract(src, result: FetchResult, now: datetime) -> Tuple[bool, str]:
    """Whether this fetch's content should pay for extraction.

    Only a fetch carrying real body content can extract. The skip is safe
    when ALL hold:
      - content_hash equals the hash at the last successful extraction
        (304 responses and identical re-fetches land here), and
      - the last extraction is younger than the force-reextract window
        (bounds detail-page/link drift invisible to the listing hash).
    """
    if result.outcome == OUTCOME_NOT_MODIFIED:
        return False, "not_modified"
    if result.outcome != OUTCOME_OK or not result.text:
        return False, "no_content"
    if src.extracted_hash is None:
        return True, "never_extracted"
    if result.content_hash and result.content_hash != src.extracted_hash:
        return True, "changed"
    last = _naive(src.last_extracted_at)
    if last is None or (_naive(now) - last).total_seconds() >= force_reextract_seconds():
        return True, "forced_refresh"
    return False, "unchanged"


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------


def _columns():
    from app.models.models import CatalogSource

    return CatalogSource


def _all_source_keys(db: Session) -> set:
    CatalogSource = _columns()
    return {r.source_key for r in db.query(CatalogSource.source_key).all()}


def _row_by_url(db: Session, url: str):
    CatalogSource = _columns()
    return db.query(CatalogSource).filter(CatalogSource.url == url).first()


def _row_by_key(db: Session, key: str):
    CatalogSource = _columns()
    return db.query(CatalogSource).filter(CatalogSource.source_key == key).first()


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    """timestamptz columns hydrate timezone-aware while pipeline callers pass
    naive utcnow — normalize both sides so comparisons never TypeError."""
    if dt is not None and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def is_due(src, now: datetime) -> bool:
    """Pure mirror of the SQL due-selection — kept identical to
    ``get_due_sources`` so tests can assert the rule without a database."""
    return bool(
        src.enabled
        and src.health not in UNSCHEDULED_HEALTHS
        and (src.next_check_at is None or _naive(src.next_check_at) <= _naive(now))
    )


def sync_sources(db: Session, configs: Optional[Sequence[SourceConfig]] = None) -> dict:
    """Import configured sources into catalog_sources, idempotently.

    Match order: existing row by URL, else by source_key. Matched rows get
    their *configured* fields refreshed; health/scheduling/fetch state and
    ``enabled`` are preserved — re-running the import never resets a source's
    operational state.
    """
    CatalogSource = _columns()
    if configs is None:
        configs = load_sources()

    taken = _all_source_keys(db)
    # Slugs shared by multiple configured sources are ambiguous for URL
    # maintenance — those rows are only ever matched by URL or suffixed key.
    name_counts = Counter(slugify(c.name or "") for c in configs if c.url)
    created = updated = 0
    for cfg in configs:
        if not cfg.url:
            continue
        row = _row_by_url(db, cfg.url)
        if row is None and name_counts[slugify(cfg.name or "")] == 1:
            # URL may have been maintained in sources.json: match the same
            # configured source by its unambiguous base slug.
            row = _row_by_key(db, slugify(cfg.name or ""))
        if row is None:
            key = source_key_for(cfg.name, cfg.url, taken)
            row = _row_by_key(db, key)
        if row is not None and cfg.url != row.url:
            # Authoritative URL maintenance: same configured source pointing
            # at a new URL adopts it in place, preserving identity/history.
            row.url = cfg.url
        if row is None:
                row = CatalogSource(
                    source_key=key, url=cfg.url,
                    health=HEALTH_UNKNOWN,
                    next_check_at=datetime.utcnow(),  # new source: due now
                )
                db.add(row)
                taken.add(key)
                created += 1
        row.name = cfg.name or row.name
        row.category = cfg.category or row.category
        row.primary_discipline = cfg.primary_discipline or row.primary_discipline
        row.target_credentials = list(cfg.target_credentials or [])
        row.state_restriction = cfg.state_restriction
        row.scraper_type = cfg.scraper_type or row.scraper_type
        if row.next_check_at is None and row.health not in UNSCHEDULED_HEALTHS:
            row.next_check_at = datetime.utcnow()
        updated += 1
    db.commit()
    return {"configured": len(configs), "created": created, "updated": updated}


def sync_seeds(db: Session, seeds: Optional[Sequence[dict]] = None,
               *, priority: int = 5) -> dict:
    """Import curated crawl seeds (seeds.json) into the crawler_seeds queue,
    idempotently.

    Reconciliation decision (C7): ``crawler_seeds`` remains the single
    discovery queue — curated seeds are imported into it rather than living
    as a parallel file-only universe, and the queue is drained by the
    explicitly scheduled ``--dynamic-queue`` processor. Existing rows keep
    their status (a 'crawled' curated seed re-enters via the normal
    re-crawl window, it is not reset)."""
    if seeds is None:
        import json
        from pathlib import Path

        path = Path(__file__).parent / "seeds.json"
        seeds = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    inserted = skipped = 0
    for s in seeds:
        url = (s.get("url") or "").strip()
        if not url:
            skipped += 1
            continue
        res = db.execute(
            text(
                """
                INSERT INTO crawler_seeds (url, source_name, category, priority, status)
                VALUES (:url, :name, :cat, :pri, 'queued')
                ON CONFLICT (url) DO NOTHING
                """
            ),
            {"url": url, "name": s.get("name") or None,
             "cat": s.get("category") or "curated_seed", "pri": priority},
        )
        inserted += res.rowcount if res.rowcount and res.rowcount > 0 else 0
        if not (res.rowcount and res.rowcount > 0):
            skipped += 1
    db.commit()
    return {"seeds": len(seeds), "inserted": inserted, "skipped_existing": skipped}


def get_due_sources(db: Session, *, limit: Optional[int] = None,
                    now: Optional[datetime] = None,
                    source_keys: Optional[Sequence[str]] = None) -> List:
    """Enabled sources whose check is due, unscheduled-health excluded.

    ``next_check_at IS NULL`` on a schedulable health state means "never
    checked" -> due immediately (NULLS FIRST keeps new sources ahead).
    ``source_keys`` optionally scopes the run to a subset of registered
    sources (e.g. a targeted ingestion batch)."""
    CatalogSource = _columns()
    now = now or datetime.utcnow()
    q = (
        db.query(CatalogSource)
        .filter(
            CatalogSource.enabled.is_(True),
            CatalogSource.health.notin_(UNSCHEDULED_HEALTHS),
            (CatalogSource.next_check_at.is_(None))
            | (CatalogSource.next_check_at <= now),
        )
    )
    if source_keys:
        q = q.filter(CatalogSource.source_key.in_(list(source_keys)))
    q = q.order_by(CatalogSource.next_check_at.asc().nullsfirst())
    if limit:
        q = q.limit(limit)
    return q.all()


def apply_check(src, result: FetchResult, now: datetime) -> str:
    """Pure mutation step of record_check: health transition, durable
    validators/hash, failure/unchanged counters, bounded diagnostics, and the
    next deterministic check time. Split out so unit tests need no database."""
    new_health = classify_health(src.health, result)

    src.last_attempted_at = now
    src.checks_total = (src.checks_total or 0) + 1
    src.last_check_outcome = result.outcome
    src.last_http_status = result.http_status
    src.last_error = (result.error or "")[:500] or None

    if result.outcome == OUTCOME_OK:
        src.last_fetch_ok_at = now
        if result.etag:
            src.etag = result.etag
        if result.last_modified:
            src.last_modified = result.last_modified
        if result.final_url:
            src.last_resolved_url = result.final_url
        previous_hash = src.content_hash
        if result.content_hash:
            src.content_hash = result.content_hash
            if previous_hash == result.content_hash:
                src.consecutive_unchanged = (src.consecutive_unchanged or 0) + 1
            elif previous_hash is None:
                src.consecutive_unchanged = 0  # first successful fetch
            else:
                src.consecutive_unchanged = 0  # content changed
    elif result.outcome == OUTCOME_NOT_MODIFIED:
        src.last_fetch_ok_at = now
        src.consecutive_unchanged = (src.consecutive_unchanged or 0) + 1

    if result.outcome == OUTCOME_PERMANENT_HTTP or result.outcome in _TRANSIENT_OUTCOMES:
        src.consecutive_failures = (src.consecutive_failures or 0) + 1
    elif result.outcome in (OUTCOME_OK, OUTCOME_NOT_MODIFIED,
                            OUTCOME_ROBOTS_DENIED, OUTCOME_ROBOTS_UNAVAILABLE,
                            OUTCOME_ACCESS_DENIED):
        src.consecutive_failures = 0

    src.health = new_health
    src.next_check_at = next_check_for(src, new_health, now)
    src.updated_at = now
    return new_health


def record_check(db: Session, src, result: FetchResult,
                 *, now: Optional[datetime] = None) -> str:
    """apply_check + commit. Returns the source's new health state."""
    new_health = apply_check(src, result, now or datetime.utcnow())
    db.commit()
    return new_health


def mark_extracted(db: Session, src, result: FetchResult,
                   *, now: Optional[datetime] = None) -> None:
    """Record that the fetched content went through extraction."""
    now = now or datetime.utcnow()
    src.last_extracted_at = now
    src.extracted_hash = result.content_hash or src.content_hash
    src.extractions_total = (src.extractions_total or 0) + 1
    src.updated_at = now
    db.commit()


def mark_skipped(db: Session, src, *, now: Optional[datetime] = None) -> None:
    src.skips_total = (src.skips_total or 0) + 1
    src.updated_at = now or datetime.utcnow()
    db.commit()


def touch_source_opportunities(db: Session, src, *, now: Optional[datetime] = None) -> int:
    """Advance last_seen_at for opportunities attributed to this source's
    page(s) — the cheap observation that keeps an unchanged page's children
    from going stale while extraction is skipped (C3)."""
    from app.models.models import Scholarship

    urls = {src.url, src.last_resolved_url or src.url}
    n = (
        db.query(Scholarship)
        .filter(Scholarship.source_url.in_(urls))
        .update({Scholarship.last_seen_at: now or datetime.utcnow()},
                synchronize_session=False)
    )
    db.commit()
    return n


def registry_summary(db: Session, *, now: Optional[datetime] = None) -> dict:
    """Bounded operational summary for admin/observability."""
    now = now or datetime.utcnow()
    rows = db.execute(
        text(
            """
            SELECT health, enabled,
                   COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE next_check_at IS NOT NULL
                                    AND next_check_at <= :now) AS due
            FROM catalog_sources
            GROUP BY health, enabled
            """
        ),
        {"now": now},
    ).fetchall()
    by_health: dict = {}
    total = enabled = due = 0
    for r in rows:
        by_health[r.health] = by_health.get(r.health, 0) + r.n
        total += r.n
        if r.enabled:
            enabled += r.n
            due += r.due
    return {"total": total, "enabled": enabled, "due_now": due,
            "by_health": by_health}

"""Autonomous crawler seed queue service.

Provides functions to:
  - Fetch the next batch of seeds from Supabase (re-crawling stale seeds
    older than 7 days).
  - Enqueue newly discovered directory-hub URLs during crawler traversal.
  - Mark seeds as crawled / failed after processing.

All functions accept a SQLAlchemy ``Session`` so they can be used inside
the scraper runner, scheduled jobs, or ad-hoc scripts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Re-crawl successful seeds whose last_crawled_at is older than this threshold.
RE_CRAWL_AFTER = timedelta(days=7)

# Failed sources are retried with bounded backoff. After the final failed
# attempt they are quarantined for manual review rather than retried forever.
MAX_FAILURES_BEFORE_QUARANTINE = 5
RETRY_BACKOFF = (
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(hours=24),
    timedelta(hours=72),
)


def _retry_delay(error_count: int) -> timedelta:
    """Return the delay before the next retry for a failed attempt."""
    index = max(0, min(error_count - 1, len(RETRY_BACKOFF) - 1))
    return RETRY_BACKOFF[index]

# Domains that should never be enqueued as seeds (social media, generic
# aggregators, dead directories).  Mirrors crawler.BLOCKED_DOMAINS plus
# social platforms.
EXCLUDED_SEED_DOMAINS = {
    # Generic aggregators
    "fastweb.com",
    "scholarships.com",
    "studentaid.gov",
    "collegeboard.org",
    "bigfuture.collegeboard.org",
    "niche.com",
    "cappex.com",
    "scholarshipportal.com",
    # Social media
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "reddit.com",
    # App forms / login portals (not directory hubs)
    "login.microsoftonline.com",
    "accounts.google.com",
}

# File extensions that should never become seeds (individual documents,
# images, media).  Mirrors crawler.REJECTED_EXTENSIONS.
EXCLUDED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".zip", ".tar", ".gz", ".rar",
    ".mp4", ".avi", ".mov", ".wmv", ".mp3", ".wav",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
}

# Path patterns that indicate an individual application form rather than a
# directory hub.  These are excluded from seed enqueueing.
NON_HUB_PATH_PATTERNS = [
    "/apply/",
    "/application",
    "/login",
    "/register",
    "/signup",
    "/account",
    "/cart",
    "/checkout",
    "/donate",
    "/payment",
]

# Path patterns that indicate a high-yield directory hub worth seeding.
HUB_PATH_PATTERNS = [
    "/scholarship",
    "/scholarships",
    "/grant",
    "/grants",
    "/fellowship",
    "/fellowships",
    "/financial-aid",
    "/financial_aid",
    "/outside-scholarship",
    "/outside_scholarship",
    "/external-scholarship",
    "/external_scholarship",
    "/external-aid",
    "/external_aid",
    "/private-donor",
    "/private_donor",
    "/outside-awards",
    "/outside_awards",
    "/tuition-assistance",
    "/tuition_assistance",
    "/tuition-reimbursement",
    "/tuition_reimbursement",
    "/education-benefit",
    "/education_benefit",
    "/career-choice",
    "/career_choice",
    "/loan-repayment",
    "/loan_repayment",
    "/service-commitment",
    "/service_commitment",
    "/opportunities",
    "/awards",
    "/funding",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_next_seed_batch(db: Session, limit: int = 20) -> List[dict]:
    """Return the next batch of seeds to crawl.

    Selects queued seeds, stale successfully crawled seeds, and failed seeds
    whose retry backoff has elapsed. Quarantined and ignored seeds are never
    selected automatically.

    Args:
        db: SQLAlchemy session.
        limit: Maximum number of seeds to return.

    Returns:
        List of dicts with keys: id, url, source_name, category, priority,
        status, last_crawled_at, discovered_from_url.
    """
    cutoff = datetime.utcnow() - RE_CRAWL_AFTER
    sql = text(
        """
        SELECT id, url, source_name, category, priority, status,
               last_crawled_at, discovered_from_url, error_count,
               next_retry_at, last_error
        FROM crawler_seeds
        WHERE status = 'queued'
           OR (status = 'crawled' AND last_crawled_at IS NOT NULL
               AND last_crawled_at < :cutoff)
           OR (status = 'failed' AND next_retry_at IS NOT NULL
               AND next_retry_at <= NOW())
        ORDER BY priority DESC, last_crawled_at ASC NULLS FIRST
        LIMIT :limit
        """
    )
    rows = db.execute(sql, {"cutoff": cutoff, "limit": limit}).fetchall()
    return [
        {
            "id": str(r.id),
            "url": r.url,
            "source_name": r.source_name,
            "category": r.category,
            "priority": r.priority,
            "status": r.status,
            "last_crawled_at": r.last_crawled_at.isoformat() if r.last_crawled_at else None,
            "discovered_from_url": r.discovered_from_url,
            "error_count": r.error_count,
            "next_retry_at": r.next_retry_at.isoformat() if r.next_retry_at else None,
            "last_error": r.last_error,
        }
        for r in rows
    ]


def enqueue_discovered_seeds(
    db: Session,
    urls: List[str],
    parent_url: str,
    detected_category: str = "discovered_directory",
) -> int:
    """Insert newly discovered directory-hub URLs into the seed queue.

    Normalizes domains, filters out excluded platforms (social media,
    dead aggregators, individual application forms, static file
    downloads), and inserts novel URLs with ``status='queued'`` and
    ``priority=1`` using ``ON CONFLICT (url) DO NOTHING``.

    Args:
        db: SQLAlchemy session.
        urls: Candidate URLs discovered during crawler traversal.
        parent_url: The page on which these URLs were discovered.
        detected_category: Category tag for the discovered seeds.

    Returns:
        Number of new seeds actually inserted (0 if all were duplicates
        or filtered out).
    """
    from .crawler import ScholarshipCrawler  # avoid circular import at module load

    cleaned: List[str] = []
    for raw_url in urls:
        normalized = ScholarshipCrawler._normalize_url(raw_url)
        if not normalized:
            continue
        # Skip excluded domains
        domain = _get_domain(normalized)
        if domain in EXCLUDED_SEED_DOMAINS:
            continue
        # Skip excluded file extensions
        path = urlparse(normalized).path.lower()
        if any(path.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
            continue
        # Skip individual application forms / non-hub pages
        if any(pattern in path for pattern in NON_HUB_PATH_PATTERNS):
            continue
        # Only enqueue links that look like directory hubs
        if not any(pattern in path for pattern in HUB_PATH_PATTERNS):
            # Also accept AcademicWorks opportunity portals
            if not (domain.endswith(".academicworks.com") and "/opportunities" in path):
                continue
        cleaned.append(normalized)

    if not cleaned:
        return 0

    # Bulk insert with ON CONFLICT DO NOTHING
    values_sql = ", ".join(
        f"(:url_{i}, :parent, :cat)" for i in range(len(cleaned))
    )
    params: dict = {"parent": parent_url, "cat": detected_category}
    for i, u in enumerate(cleaned):
        params[f"url_{i}"] = u

    sql = text(
        f"""
        INSERT INTO crawler_seeds (url, discovered_from_url, category, priority, status)
        VALUES {values_sql}
        ON CONFLICT (url) DO NOTHING
        """
    )
    result = db.execute(sql, params)
    db.commit()
    inserted = result.rowcount if result.rowcount > 0 else 0
    if inserted:
        logger.info(
            "Enqueued %d new seed(s) from %s (category=%s)",
            inserted, parent_url, detected_category,
        )
    return inserted


def mark_seed_crawled(
    db: Session,
    seed_id: str,
    success: bool,
    error: Optional[str] = None,
) -> None:
    """Update a seed after processing with retry/backoff semantics.

    Success resets the failure state. A transient failure is retried after a
    bounded backoff. After ``MAX_FAILURES_BEFORE_QUARANTINE`` consecutive
    failures the seed is quarantined for manual review.
    """
    if success:
        sql = text(
            """
            UPDATE crawler_seeds
            SET status = 'crawled',
                last_crawled_at = NOW(),
                error_count = 0,
                next_retry_at = NULL,
                last_error = NULL
            WHERE id = :seed_id
            """
        )
        params = {"seed_id": seed_id}
    else:
        row = db.execute(
            text("SELECT error_count FROM crawler_seeds WHERE id = :seed_id"),
            {"seed_id": seed_id},
        ).fetchone()
        previous_count = int(row.error_count or 0) if row else 0
        new_count = previous_count + 1
        safe_error = (error or "crawl failed")[:2000]

        if new_count >= MAX_FAILURES_BEFORE_QUARANTINE:
            sql = text(
                """
                UPDATE crawler_seeds
                SET status = 'quarantined',
                    last_crawled_at = NOW(),
                    error_count = :error_count,
                    next_retry_at = NULL,
                    last_error = :last_error
                WHERE id = :seed_id
                """
            )
            params = {
                "seed_id": seed_id,
                "error_count": new_count,
                "last_error": safe_error,
            }
            logger.error(
                "Seed %s quarantined after %d consecutive failures: %s",
                seed_id, new_count, safe_error,
            )
        else:
            retry_at = datetime.utcnow() + _retry_delay(new_count)
            sql = text(
                """
                UPDATE crawler_seeds
                SET status = 'failed',
                    last_crawled_at = NOW(),
                    error_count = :error_count,
                    next_retry_at = :next_retry_at,
                    last_error = :last_error
                WHERE id = :seed_id
                """
            )
            params = {
                "seed_id": seed_id,
                "error_count": new_count,
                "next_retry_at": retry_at,
                "last_error": safe_error,
            }
            logger.warning(
                "Seed %s crawl failed (attempt %d/%d); retry after %s: %s",
                seed_id, new_count, MAX_FAILURES_BEFORE_QUARANTINE,
                retry_at.isoformat(), safe_error,
            )

    db.execute(sql, params)
    db.commit()


def mark_seed_robots_denied(
    db: Session,
    seed_id: str,
    detail: str = "robots_denied",
) -> None:
    """Record that a seed could not be crawled because robots.txt said no.

    Within the current schema this looks like a completed cycle — the seed
    re-enters the normal 7-day re-crawl rotation (robots policies do change),
    but ``error_count`` is reset and no retry backoff is scheduled, so a
    denied seed can never accrue the transient-failure streak that ends in
    quarantine (C6). ``last_error`` keeps the bounded outcome for review.
    """
    sql = text(
        """
        UPDATE crawler_seeds
        SET status = 'crawled',
            last_crawled_at = NOW(),
            error_count = 0,
            next_retry_at = NULL,
            last_error = :last_error
        WHERE id = :seed_id
        """
    )
    db.execute(sql, {"seed_id": seed_id, "last_error": detail[:2000]})
    db.commit()
    logger.warning("Seed %s not crawled: %s", seed_id, detail[:200])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_domain(url: str) -> str:
    """Extract the registered domain (netloc without www.)."""
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc

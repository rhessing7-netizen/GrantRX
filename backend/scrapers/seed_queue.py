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

# Re-crawl seeds whose last_crawled_at is older than this threshold.
RE_CRAWL_AFTER = timedelta(days=7)

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

    Selects seeds with ``status IN ('queued', 'crawled')`` ordered by
    ``priority DESC, last_crawled_at ASC NULLS FIRST``.  Seeds with
    ``status='crawled'`` are only included if ``last_crawled_at`` is older
    than :data:`RE_CRAWL_AFTER` (7 days), so stale seeds get re-crawled.

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
               last_crawled_at, discovered_from_url
        FROM crawler_seeds
        WHERE status = 'queued'
           OR (status = 'crawled' AND last_crawled_at IS NOT NULL
               AND last_crawled_at < :cutoff)
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
    """Update a seed's crawl status after processing.

    Sets ``last_crawled_at = NOW()``, increments ``error_count`` on
    failure, and marks ``status`` as ``'crawled'`` (success) or
    ``'failed'`` (failure).

    Args:
        db: SQLAlchemy session.
        seed_id: UUID of the crawler_seeds row.
        success: Whether the crawl succeeded.
        error: Optional error message (logged but not stored in the row).
    """
    if success:
        sql = text(
            """
            UPDATE crawler_seeds
            SET status = 'crawled',
                last_crawled_at = NOW(),
                error_count = 0
            WHERE id = :seed_id
            """
        )
    else:
        sql = text(
            """
            UPDATE crawler_seeds
            SET status = 'failed',
                last_crawled_at = NOW(),
                error_count = error_count + 1
            WHERE id = :seed_id
            """
        )
        if error:
            logger.warning("Seed %s crawl failed: %s", seed_id, error)
    db.execute(sql, {"seed_id": seed_id})
    db.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_domain(url: str) -> str:
    """Extract the registered domain (netloc without www.)."""
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc

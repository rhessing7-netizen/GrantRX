"""Repair dead portal URLs in existing scholarship records.

Iterates over all scholarships in the database, checks each portal_url with a
HEAD/GET request, and:
  1. If portal_url is broken, look for a scholarship-specific replacement in
     sources.json. Generic organization homepages are never treated as repairs.
  2. A replacement must be reachable AND have a path that looks specific to a
     scholarship/grant/fellowship/financial-aid/award page.
  3. If no trustworthy replacement is available, archive the scholarship so a
     misleading generic link is never shown to users.

Usage:
    python -m scripts.repair_urls          # check and repair all
    python -m scripts.repair_urls --dry-run  # report only, no changes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urljoin, urlparse

# Ensure the backend directory is on the path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("scripts.repair_urls")

TIMEOUT = 8.0
# Link checks run through the C6 FetchSession: honest EdFintiaBot identity,
# robots.txt, per-host pacing. An inconclusive check (robots denial, timeout,
# network error) is NOT a dead link — it returns -1 and leaves the record
# alone rather than archiving a URL we never actually verified.
UNCHECKABLE = -1


def _load_source_url_map() -> Dict[str, str]:
    """Load sources.json and build a provider-name -> source URL map."""
    sources_path = Path(__file__).resolve().parent.parent / "scrapers" / "sources.json"
    if not sources_path.exists():
        return {}
    with open(sources_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    url_map: Dict[str, str] = {}
    for item in data:
        name = (item.get("name") or "").strip().lower()
        url = item.get("url", "")
        if name and url:
            url_map[name] = url
    return url_map


def _find_source_url(provider: str, portal_url: str, source_map: Dict[str, str]) -> Optional[str]:
    """Find the best matching source URL for a given provider name."""
    if not provider:
        return None
    provider_lower = provider.strip().lower()

    # Exact match
    if provider_lower in source_map:
        return source_map[provider_lower]

    # Partial match — check if the provider name is a substring of a source name or vice versa
    for name, url in source_map.items():
        if provider_lower in name or name in provider_lower:
            return url

    # Try matching by domain from the portal URL
    parsed = urlparse(portal_url)
    domain = parsed.netloc.replace("www.", "").lower()
    if domain:
        for name, url in source_map.items():
            src_domain = urlparse(url).netloc.replace("www.", "").lower()
            if domain == src_domain:
                return url

    return None


async def _check_url(url: str) -> int:
    """Check a URL and return the HTTP status code.

    Returns UNCHECKABLE (-1) when no definitive response was obtained —
    robots denial, robots unavailable, timeout, or network error. Only a
    real HTTP response is allowed to decide a link is dead.
    """
    if not url or not url.strip():
        return UNCHECKABLE
    from scrapers.fetch_policy import INCONCLUSIVE_OUTCOMES, default_session

    result = await default_session().check(url, timeout=TIMEOUT)
    if result.outcome in INCONCLUSIVE_OUTCOMES or result.http_status is None:
        logger.debug("  %s -> inconclusive (%s)", url, result.outcome)
        return UNCHECKABLE
    return result.http_status


def _root_domain_url(url: str) -> Optional[str]:
    """Extract the root domain URL (scheme + host) from a full URL.

    e.g. 'https://www.example.com/scholarships/apply?x=1' -> 'https://www.example.com'
    Returns None if the URL is invalid or has no netloc.
    """
    if not url or not url.strip():
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


# Shared with the ingestion runner — one definition of "opportunity-specific".
from scrapers.utils.url_safety import (  # noqa: E402
    is_safe_replacement_url,
    is_specific_opportunity_url as _is_specific_opportunity_url,
)
from scrapers.utils.identity import compute_identity_keys  # noqa: E402


async def repair_one(s, source_map: Dict[str, str], db=None) -> str:
    """Check one active record's portal URL and apply the repair rule.

    Returns "ok", "repaired", or "archived". Mutates ``s`` in place; the
    caller commits (or discards, in dry-run mode).

    A link check is recorded as ``last_checked_at`` only — a reachable URL is
    not an observation of the opportunity itself.
    """
    from app.services import lifecycle

    portal_url = s.portal_url or ""
    status_code = await _check_url(portal_url)
    lifecycle.record_check(s)
    logger.debug("  %s -> HTTP %d", portal_url, status_code)

    if status_code == UNCHECKABLE:
        logger.info("  Check inconclusive (robots/timeout/network): %s — leaving record unchanged",
                    portal_url)
        return "unchecked"
    if status_code < 400:
        return "ok"

    # URL is dead. Never replace it with the provider's root homepage or an
    # unrelated organization's page: HTTP 200 only proves that some page
    # exists, not that this opportunity/application is available there.
    logger.warning("Dead URL (HTTP %d): %s — '%s'", status_code, portal_url, s.title)

    candidate = _find_source_url(s.provider, portal_url, source_map)
    originals = [portal_url, getattr(s, "source_url", None) or ""]
    if candidate and candidate != portal_url:
        if not is_safe_replacement_url(candidate, originals):
            logger.warning("  Rejecting generic/unrelated replacement: %s", candidate)
        else:
            candidate_status = await _check_url(candidate)
            if candidate_status != UNCHECKABLE and candidate_status < 400:
                # Repointing the portal URL changes this record's identity.
                # The new URL must not be another record's persisted identity —
                # that would fuse two rows into one opportunity.
                new_key, new_fallback = compute_identity_keys(
                    s.title, s.provider, candidate, getattr(s, "source_url", None),
                )
                if db is not None and new_key:
                    from app.models.models import Scholarship

                    owner = (
                        db.query(Scholarship)
                        .filter(Scholarship.identity_key == new_key, Scholarship.id != s.id)
                        .first()
                    )
                    if owner is not None:
                        logger.warning(
                            "  Rejecting replacement: %s is already the identity of '%s'",
                            candidate, owner.title,
                        )
                        candidate_status = 409
                if candidate_status < 400:
                    logger.info("  Repairing (verified opportunity source): %s -> %s", portal_url, candidate)
                    s.portal_url = candidate
                    s.identity_key = new_key
                    s.identity_fallback_key = new_fallback
                    return "repaired"
                logger.warning(
                    "  Replacement URL belongs to another opportunity: %s", candidate
                )
            elif candidate_status == UNCHECKABLE:
                logger.info("  Replacement check inconclusive: %s — not repointing", candidate)
            else:
                logger.warning("  Opportunity source also dead (HTTP %d): %s", candidate_status, candidate)

    logger.warning("  Archiving dead scholarship: '%s' (provider: %s)", s.title, s.provider)
    lifecycle.archive(s, lifecycle.DEAD_LINK)
    return "archived"


async def repair_urls(dry_run: bool = False) -> dict:
    """Check and repair all scholarship portal URLs.

    Returns a summary dict with counts.
    """
    from dotenv import load_dotenv

    load_dotenv()

    from app.database import SessionLocal
    from app.models.models import Scholarship
    from app.services import lifecycle

    source_map = _load_source_url_map()
    logger.info("Loaded %d source URLs from sources.json", len(source_map))

    db = SessionLocal()
    summary = {
        "total": 0,
        "ok": 0,
        "repaired": 0,
        "archived": 0,
        "already_archived": 0,
        "unchecked": 0,
        "errors": 0,
    }
    try:
        rows = db.query(Scholarship).all()
        summary["total"] = len(rows)
        logger.info("Checking %d scholarship URL(s)...", len(rows))

        for s in rows:
            if lifecycle.current_status(s) == lifecycle.ARCHIVED:
                summary["already_archived"] += 1
                continue

            action = await repair_one(s, source_map, db=db)
            summary[action] = summary.get(action, 0) + 1
            if not dry_run and action in ("ok", "repaired", "archived"):
                s.updated_at = datetime.utcnow()
                db.commit()
            elif dry_run:
                db.rollback()

    except Exception as exc:  # noqa: BLE001
        logger.error("Repair script failed: %s", exc)
        summary["errors"] += 1
    finally:
        db.close()

    return summary


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.repair_urls", description="Repair dead scholarship URLs")
    parser.add_argument("--dry-run", action="store_true", help="Report only, do not modify the database")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    summary = asyncio.run(repair_urls(dry_run=args.dry_run))

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\n{'=' * 60}")
    print(f"URL REPAIR REPORT ({mode})")
    print(f"{'=' * 60}")
    print(f"  Total scholarships checked: {summary['total']}")
    print(f"  URLs OK (HTTP < 400):        {summary['ok']}")
    print(f"  URLs repaired:               {summary['repaired']}")
    print(f"  Scholarships archived (dead): {summary['archived']}")
    print(f"  Already archived (skipped):   {summary['already_archived']}")
    print(f"  Errors:                       {summary['errors']}")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

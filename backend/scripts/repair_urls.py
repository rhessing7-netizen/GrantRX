"""Repair dead portal URLs in existing scholarship records.

Iterates over all scholarships in the database, checks each portal_url with a
HEAD/GET request, and:
  1. If the portal_url returns 404, looks up the source URL from sources.json
     by matching the provider name, and replaces the dead URL.
  2. If no source URL is found or the source URL is also dead, marks the
     scholarship as inactive (is_archived=True) so it doesn't appear in feeds.

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

import httpx

# Ensure the backend directory is on the path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("scripts.repair_urls")

TIMEOUT = 8.0
USER_AGENT = "Mozilla/5.0 (compatible; GrantRx-LinkChecker/1.0)"


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
    """Check a URL and return the HTTP status code. Returns 999 on network error."""
    if not url or not url.strip():
        return 999
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            try:
                resp = await client.head(url)
                if resp.status_code == 405:
                    resp = await client.get(url)
            except httpx.HTTPError:
                resp = await client.get(url)
            return resp.status_code
    except Exception:  # noqa: BLE001
        return 999


async def repair_urls(dry_run: bool = False) -> dict:
    """Check and repair all scholarship portal URLs.

    Returns a summary dict with counts.
    """
    from dotenv import load_dotenv

    load_dotenv()

    from app.database import SessionLocal
    from app.models.models import Scholarship

    source_map = _load_source_url_map()
    logger.info("Loaded %d source URLs from sources.json", len(source_map))

    db = SessionLocal()
    summary = {
        "total": 0,
        "ok": 0,
        "repaired": 0,
        "archived": 0,
        "already_archived": 0,
        "errors": 0,
    }
    try:
        rows = db.query(Scholarship).all()
        summary["total"] = len(rows)
        logger.info("Checking %d scholarship URL(s)...", len(rows))

        for s in rows:
            if s.is_archived:
                summary["already_archived"] += 1
                continue

            portal_url = s.portal_url or ""
            status_code = await _check_url(portal_url)
            logger.debug("  %s -> HTTP %d", portal_url, status_code)

            if status_code < 400:
                summary["ok"] += 1
                continue

            # URL is dead — try to find a replacement from sources.json
            logger.warning("Dead URL (HTTP %d): %s — '%s'", status_code, portal_url, s.title)
            source_url = _find_source_url(s.provider, portal_url, source_map)

            if source_url and source_url != portal_url:
                # Verify the source URL is alive
                source_status = await _check_url(source_url)
                if source_status < 400:
                    logger.info("  Repairing: %s -> %s", portal_url, source_url)
                    if not dry_run:
                        s.portal_url = source_url
                        s.updated_at = datetime.utcnow()
                        db.commit()
                    summary["repaired"] += 1
                    continue
                else:
                    logger.warning("  Source URL also dead (HTTP %d): %s", source_status, source_url)

            # Both portal and source URLs are dead — archive the scholarship
            logger.warning("  Archiving dead scholarship: '%s' (provider: %s)", s.title, s.provider)
            if not dry_run:
                s.is_archived = True
                s.updated_at = datetime.utcnow()
                db.commit()
            summary["archived"] += 1

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

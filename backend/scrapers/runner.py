"""CLI runner, dedup upsert, auto-archival, and daily AsyncIO scheduler.

Three-tier scraper pipeline:
  Tier 1 — Deterministic: httpx + BeautifulSoup parsers for structured pages.
  Tier 2 — Playwright: headless browser for JS-rendered SPAs.
  Tier 3 — LLM Fallback: instructor + OpenAI/LiteLLM for unstructured content.

Usage:
    python -m scrapers.runner --target=all
    python -m scrapers.runner --target=https://www.pharmacist.com/...
    python -m scrapers.runner --target=all --dry-run
    python -m scrapers.runner --category=regional_foundation
    python -m scrapers.runner --category=corporate_unrestricted --limit=3
    python -m scrapers.runner --state=CA
    python -m scrapers.runner --schedule   # run daily at 03:00 local time
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .fetcher import fetch_many
from .llm_parser import extract_with_llm
from .parsers.deterministic import parse_with_deterministic
from .schema import ScholarshipExtract
from .sources import SourceConfig, load_sources
from .utils.normalize import add_one_year, parse_date

logger = logging.getLogger("scrapers.runner")

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _resolve_portal_url(extracted_url: str, source_url: str) -> str:
    """Resolve a potentially relative portal URL to an absolute URL.

    If the extracted URL is relative (e.g. '/apply'), join it with the source URL.
    If it's already absolute, return as-is. If empty, fall back to the source URL.
    """
    if not extracted_url or not extracted_url.strip():
        return source_url
    extracted_url = extracted_url.strip()
    parsed = urlparse(extracted_url)
    if parsed.scheme in ("http", "https"):
        return extracted_url
    # Relative URL — resolve against the source URL
    return urljoin(source_url, extracted_url)


async def _verify_url(url: str, *, timeout: float = 5.0) -> bool:
    """Quick HEAD/GET request to verify a URL returns HTTP < 400.

    Follows redirects. Returns True if the URL is reachable and returns a
    non-error status code. Returns False on 4xx/5xx or network errors.
    """
    import httpx

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; GrantRx-LinkChecker/1.0)"},
        ) as client:
            # Try HEAD first (lighter), fall back to GET if HEAD not supported
            try:
                resp = await client.head(url)
                if resp.status_code == 405:
                    resp = await client.get(url)
            except httpx.HTTPError:
                resp = await client.get(url)
            return resp.status_code < 400
    except Exception:  # noqa: BLE001
        return False


async def _verify_portal_url(
    portal_url: str,
    source_url: str,
) -> Tuple[str, bool]:
    """Verify the portal URL, falling back to source URL if needed.

    Returns (final_url, is_valid). If both URLs are dead, returns (portal_url, False).
    """
    # Check the extracted portal URL first
    is_valid = await _verify_url(portal_url)
    if is_valid:
        return portal_url, True

    # Portal URL is dead — try the source URL as fallback
    logger.warning("Portal URL returned error (404?): %s — falling back to source URL", portal_url)
    source_valid = await _verify_url(source_url)
    if source_valid:
        return source_url, True

    # Both are dead
    logger.warning("Source URL also unreachable: %s — link will not be saved", source_url)
    return portal_url, False


# ---------------------------------------------------------------------------
# Result reporting
# ---------------------------------------------------------------------------


@dataclass
class ScrapeResult:
    url: str
    status: str  # "ok" | "llm_fallback" | "skipped" | "error"
    extract: Optional[ScholarshipExtract] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


async def scrape_url(
    url: str,
    provider_hint: str = "",
    scraper_type: str = "deterministic",
) -> ScrapeResult:
    """Fetch + parse a single URL using the hybrid three-tier pipeline."""
    from .fetcher import fetch_html

    try:
        html = await fetch_html(url, scraper_type=scraper_type)
    except Exception as exc:  # noqa: BLE001
        logger.error("Fetch failed for %s: %s", url, exc)
        return ScrapeResult(url=url, status="error", error=str(exc))

    if not html:
        return ScrapeResult(url=url, status="error", error="empty response")

    # Tier 1: deterministic parse
    extract = parse_with_deterministic(html, url)
    if extract:
        if not extract.provider:
            extract.provider = provider_hint
        if extract.is_critical_complete():
            return ScrapeResult(url=url, status="ok", extract=extract)
        logger.info("Tier 1 incomplete for %s; invoking Tier 3 (LLM fallback)", url)
    else:
        logger.info("No Tier 1 parser matched %s; invoking Tier 3 (LLM fallback)", url)

    # Tier 3: LLM fallback
    try:
        llm_extract = await extract_with_llm(html, url)
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM fallback raised for %s: %s", url, exc)
        llm_extract = None

    if not llm_extract:
        return ScrapeResult(
            url=url,
            status="error",
            error="deterministic incomplete and LLM fallback failed",
            extract=extract,
        )
    if not llm_extract.provider:
        llm_extract.provider = provider_hint or (extract.provider if extract else "")
    return ScrapeResult(url=url, status="llm_fallback", extract=llm_extract)


async def scrape_many(
    sources: List[SourceConfig],
    *,
    concurrency: int = 5,
) -> List[ScrapeResult]:
    """Fetch all sources concurrently, then parse sequentially (DB-safe).

    Error isolation: if one URL times out or fails parsing, the error is logged
    and the batch continues to the next source.
    """
    urls = [s.url for s in sources]
    scraper_types = {s.url: s.scraper_type for s in sources}

    # Fetch all URLs concurrently with tier-appropriate strategies
    fetched = await fetch_many(urls, concurrency=concurrency, scraper_types=scraper_types)

    # Build a url -> html map
    html_map: dict[str, Optional[str]] = {}
    for fetched_url, html in fetched:
        html_map[fetched_url] = html

    results: List[ScrapeResult] = []
    for src in sources:
        url = src.url
        html = html_map.get(url)

        if html is None:
            results.append(ScrapeResult(url=url, status="error", error="fetch failed"))
            logger.error("Fetch returned None for %s (source: %s)", url, src.name)
            continue

        if not html:
            results.append(ScrapeResult(url=url, status="error", error="empty response"))
            logger.error("Empty HTML for %s (source: %s)", url, src.name)
            continue

        # Tier 1: deterministic parse
        try:
            extract = parse_with_deterministic(html, url)
        except Exception as exc:  # noqa: BLE001
            logger.error("Tier 1 parser crashed for %s: %s — continuing", url, exc)
            extract = None

        if extract:
            if not extract.provider:
                extract.provider = src.name
            # Populate source metadata
            extract.source_name = src.name
            extract.source_category = src.category
            # Apply source-level state restriction if not already set
            if src.state_restriction and not extract.state_restrictions:
                extract.state_restrictions = [src.state_restriction]
            # Apply source-level discipline hint if not already set
            if src.primary_discipline != "any" and not extract.eligible_disciplines:
                extract.eligible_disciplines = [src.primary_discipline]
            # Apply source-level credential hints if not already set
            if src.target_credentials and not extract.eligible_credentials:
                extract.eligible_credentials = src.target_credentials
            # Resolve relative portal URLs to absolute
            extract.portal_url = _resolve_portal_url(extract.portal_url, url)

            if extract.is_critical_complete():
                results.append(ScrapeResult(url=url, status="ok", extract=extract))
                continue
            logger.info("Tier 1 incomplete for %s; invoking Tier 3 (LLM fallback)", url)
        else:
            logger.info("No Tier 1 parser matched %s; invoking Tier 3 (LLM fallback)", url)

        # Tier 3: LLM fallback
        try:
            llm_extract = await extract_with_llm(html, url)
        except Exception as exc:  # noqa: BLE001
            logger.error("Tier 3 LLM crashed for %s: %s — continuing", url, exc)
            llm_extract = None

        if not llm_extract:
            results.append(ScrapeResult(
                url=url,
                status="error",
                error="deterministic incomplete and LLM fallback failed",
                extract=extract,
            ))
            continue

        if not llm_extract.provider:
            llm_extract.provider = src.name or (extract.provider if extract else "")
        # Populate source metadata on LLM extract
        llm_extract.source_name = src.name
        llm_extract.source_category = src.category
        if src.state_restriction and not llm_extract.state_restrictions:
            llm_extract.state_restrictions = [src.state_restriction]
        if src.primary_discipline != "any" and not llm_extract.eligible_disciplines:
            llm_extract.eligible_disciplines = [src.primary_discipline]
        if src.target_credentials and not llm_extract.eligible_credentials:
            llm_extract.eligible_credentials = src.target_credentials
        # Resolve relative portal URLs to absolute
        llm_extract.portal_url = _resolve_portal_url(llm_extract.portal_url, url)

        results.append(ScrapeResult(url=url, status="llm_fallback", extract=llm_extract))

    return results


# ---------------------------------------------------------------------------
# Database upsert + auto-archival
# ---------------------------------------------------------------------------


def _coerce_deadline(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    d = parse_date(value)
    return d


def _to_db_dict(extract: ScholarshipExtract) -> dict:
    """Map a ScholarshipExtract to a dict suitable for SQLAlchemy model kwargs."""
    deadline = _coerce_deadline(extract.deadline)
    if deadline is None:
        raise ValueError(f"Cannot upsert scholarship with unparseable deadline: {extract.deadline!r}")

    today = date.today()
    is_archived = deadline < today
    estimated_next_cycle = add_one_year(deadline) if is_archived else (
        parse_date(extract.estimated_next_cycle) if extract.estimated_next_cycle else None
    )

    return {
        "title": extract.title,
        "provider": extract.provider,
        "portal_url": extract.portal_url,
        "award_amount": extract.award_amount or 0,
        "deadline": deadline,
        "eligible_disciplines": extract.eligible_disciplines or [],
        "eligible_credentials": extract.eligible_credentials or [],
        "min_gpa": extract.min_gpa if extract.min_gpa is not None else 0.0,
        "max_sai": extract.max_sai,
        "state_restrictions": extract.state_restrictions or [],
        "metro_restrictions": extract.metro_restrictions or [],
        "required_affiliations": extract.required_affiliations or [],
        "matching_tags": extract.matching_tags or [],
        "is_archived": is_archived,
        "estimated_next_cycle": estimated_next_cycle,
        "provider_type": extract.provider_type,
        "provider_mission": extract.provider_mission,
        "provider_core_values": extract.provider_core_values or [],
        "is_local": extract.is_local,
        "target_community": extract.target_community,
        "updated_at": datetime.utcnow(),
    }


def upsert_scholarship(db, extract: ScholarshipExtract) -> Tuple[object, str]:
    """Upsert a scholarship by (title + portal_url). Returns (model, action).

    Dedup key: scholarship title + source URL. This prevents duplicate records
    when the same scholarship appears on multiple listing pages.

    action is one of: "created", "updated", "unchanged".
    """
    from app.models.models import Scholarship  # local import to avoid import cycles

    existing = (
        db.query(Scholarship)
        .filter(
            Scholarship.title == extract.title,
            Scholarship.portal_url == extract.portal_url,
        )
        .first()
    )

    data = _to_db_dict(extract)

    if existing is None:
        scholarship = Scholarship(created_at=datetime.utcnow(), **data)
        db.add(scholarship)
        db.commit()
        db.refresh(scholarship)
        return scholarship, "created"

    changed = False
    for key, value in data.items():
        if getattr(existing, key) != value:
            setattr(existing, key, value)
            changed = True
    if changed:
        db.commit()
        db.refresh(existing)
        return existing, "updated"
    return existing, "unchanged"


def archive_expired(db) -> int:
    """Mark all scholarships with deadline < today as archived and set next cycle.

    Returns the number of rows updated.
    """
    from app.models.models import Scholarship  # local import

    today = date.today()
    rows = db.query(Scholarship).filter(Scholarship.deadline < today, Scholarship.is_archived == False).all()
    count = 0
    for s in rows:
        s.is_archived = True
        s.estimated_next_cycle = add_one_year(s.deadline)
        s.updated_at = datetime.utcnow()
        count += 1
    if count:
        db.commit()
    return count


# ---------------------------------------------------------------------------
# Source resolution & filtering
# ---------------------------------------------------------------------------


def _resolve_sources(
    target: str,
    *,
    category: Optional[str] = None,
    state: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[SourceConfig]:
    """Resolve sources from JSON/defaults, with optional filtering.

    Args:
        target: "all" or a specific URL.
        category: Filter by source category (e.g. "regional_foundation").
        state: Filter by 2-letter state code (regional sources only).
        limit: Max number of sources to process.
    """
    if target != "all":
        # Single URL — create a minimal SourceConfig
        host = urlparse(target).netloc
        hint = host.replace("www.", "").split(".")[0].title() if host else ""
        return [SourceConfig(name=hint, url=target, scraper_type="deterministic")]

    # Load all sources (from sources.json or Python defaults)
    all_sources = load_sources()

    # Filter by category
    if category:
        all_sources = [s for s in all_sources if s.category == category]
        logger.info("Filtered by category='%s': %d source(s)", category, len(all_sources))

    # Filter by state
    if state:
        state_upper = state.upper()
        all_sources = [s for s in all_sources if s.state_restriction == state_upper]
        logger.info("Filtered by state='%s': %d source(s)", state_upper, len(all_sources))

    # Apply limit
    if limit is not None and limit > 0:
        all_sources = all_sources[:limit]
        logger.info("Limited to %d source(s)", len(all_sources))

    return all_sources


# ---------------------------------------------------------------------------
# Crawl pipeline (focused web crawler → LLM extraction → DB upsert)
# ---------------------------------------------------------------------------


def _load_crawl_seeds(seeds_file: Optional[str]) -> List[str]:
    """Load seed URLs from a JSON file.

    The file format is a list of objects with a "url" key:
        [{"name": "...", "url": "https://...", ...}, ...]
    """
    import json
    from pathlib import Path

    if seeds_file:
        path = Path(seeds_file)
    else:
        path = Path(__file__).parent / "seeds.json"

    if not path.exists():
        logger.error("Seeds file not found: %s", path)
        return []

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    seeds = []
    for item in data:
        url = item.get("url", "").strip()
        if url:
            seeds.append(url)
    return seeds


async def run_crawl_pipeline(
    seeds: List[str],
    *,
    max_depth: int = 2,
    max_pages_per_domain: int = 15,
    dry_run: bool = False,
    persist: bool = True,
    limit_extract: Optional[int] = None,
) -> dict:
    """Run the focused crawler, extract scholarships via LLM, and persist.

    Args:
        limit_extract: If set, only extract from the top N candidates by score
                       (conserves OpenAI API usage during testing).

    Returns a summary dict with crawl stats and ingestion results.
    """
    from .crawler import ScholarshipCrawler

    logger.info("Starting crawl with %d seed URL(s) (max_depth=%d, max_pages=%d)",
                len(seeds), max_depth, max_pages_per_domain)

    crawler = ScholarshipCrawler(
        seeds=seeds,
        max_depth=max_depth,
        max_pages_per_domain=max_pages_per_domain,
    )
    candidates = await crawler.crawl()
    stats = crawler.get_stats()

    logger.info("Crawl found %d candidate page(s)", len(candidates))

    if dry_run or not persist:
        for c in candidates:
            state_str = f", state={c.state_restriction}" if c.state_restriction else ""
            logger.info(
                "[dry-run] Candidate: %s (score=%d%s, keywords=%s, regional=%s)",
                c.url, c.relevance_score, state_str, c.matched_keywords[:5],
                c.regional_keywords[:3],
            )
        return {
            **stats.summary(),
            "candidates": [
                {
                    "url": c.url,
                    "title": c.title,
                    "relevance_score": c.relevance_score,
                    "matched_keywords": c.matched_keywords,
                    "regional_keywords": c.regional_keywords,
                    "state_restriction": c.state_restriction,
                    "depth": c.depth,
                }
                for c in candidates
            ],
            "ingested": 0,
            "skipped_duplicates": 0,
            "extraction_failed": 0,
        }

    # Persist: extract via LLM and upsert
    from app.database import SessionLocal
    from app.models.models import Scholarship

    # Sort candidates by score (highest first) and apply limit_extract cap
    candidates_sorted = sorted(candidates, key=lambda c: -c.relevance_score)
    if limit_extract is not None and limit_extract > 0:
        logger.info("Limiting LLM extraction to top %d of %d candidates (by score)",
                    limit_extract, len(candidates_sorted))
        candidates_sorted = candidates_sorted[:limit_extract]

    db = SessionLocal()
    ingested = 0
    skipped_duplicates = 0
    extraction_failed = 0
    try:
        for c in candidates_sorted:
            # Check if URL already exists in the database
            existing = db.query(Scholarship).filter(Scholarship.portal_url == c.url).first()
            if existing:
                skipped_duplicates += 1
                logger.debug("Skipping duplicate URL: %s", c.url)
                continue

            # LLM extraction
            try:
                extract = await extract_with_llm(c.html, c.url)
            except Exception as exc:  # noqa: BLE001
                logger.error("LLM extraction failed for %s: %s", c.url, exc)
                extraction_failed += 1
                continue

            if not extract or not extract.is_critical_complete():
                extraction_failed += 1
                logger.warning("Extraction incomplete for %s", c.url)
                continue

            # Populate source metadata
            extract.source_name = c.title or c.url
            extract.source_category = "crawled"
            # Apply regional state restriction from crawler heuristics if not already set
            if c.state_restriction and not extract.state_restrictions:
                extract.state_restrictions = [c.state_restriction]
                logger.info("Tagged state_restriction=%s from crawler heuristics for %s",
                            c.state_restriction, c.url)
            # Apply metro restrictions from crawler heuristics if not already set
            metro_keys = [k for k in c.regional_keywords if k.startswith("metro:")]
            if metro_keys and not extract.metro_restrictions:
                extract.metro_restrictions = [k.replace("metro:", "", 1) for k in metro_keys]
                logger.info("Tagged metro_restrictions=%s from crawler heuristics for %s",
                            extract.metro_restrictions, c.url)
            # Resolve relative portal URLs
            extract.portal_url = _resolve_portal_url(extract.portal_url, c.url)

            # Pre-save link verification
            try:
                final_url, is_valid = await _verify_portal_url(extract.portal_url, c.url)
                if not is_valid:
                    logger.warning("Skipping dead link from crawl: %s", c.url)
                    extraction_failed += 1
                    continue
                extract.portal_url = final_url
            except Exception:  # noqa: BLE001
                pass

            try:
                _, action = upsert_scholarship(db, extract)
                if action == "created":
                    ingested += 1
                    logger.info("[crawl] %s -> %s (created)", c.url, extract.title)
                elif action == "updated":
                    ingested += 1
                    logger.info("[crawl] %s -> %s (updated)", c.url, extract.title)
                else:
                    skipped_duplicates += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                extraction_failed += 1
                logger.error("Upsert failed for %s: %s", c.url, exc)

        archived = archive_expired(db)
    finally:
        db.close()

    summary = {
        **stats.summary(),
        "ingested": ingested,
        "skipped_duplicates": skipped_duplicates,
        "extraction_failed": extraction_failed,
        "archived": archived,
    }
    logger.info(
        "Crawl pipeline summary: pages=%d, candidates=%d, ingested=%d, duplicates=%d, failed=%d",
        stats.pages_crawled, stats.candidates_found, ingested, skipped_duplicates, extraction_failed,
    )
    return summary


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


async def run_pipeline(
    target: str = "all",
    *,
    dry_run: bool = False,
    persist: bool = True,
    category: Optional[str] = None,
    state: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[ScrapeResult]:
    """Run the full three-tier pipeline for the given target and filters."""
    sources = _resolve_sources(target, category=category, state=state, limit=limit)
    logger.info(
        "Scraping %d source(s) (target=%s, category=%s, state=%s, limit=%s, dry_run=%s)",
        len(sources), target, category, state, limit, dry_run,
    )

    if not sources:
        logger.warning("No sources matched the given filters. Nothing to do.")
        return []

    results = await scrape_many(sources)

    if dry_run or not persist:
        for r in results:
            logger.info("[%s] %s -> %s", r.status, r.url,
                        r.extract.title if r.extract else r.error)
        return results

    # Persist to DB
    from app.database import SessionLocal

    db = SessionLocal()
    created = updated = unchanged = errors = dead_links = 0
    try:
        for r in results:
            if not r.extract or not r.extract.is_critical_complete():
                errors += 1
                logger.warning("Skipping upsert for %s: incomplete extract (%s)",
                               r.url, r.error or "missing critical fields")
                continue
            # Pre-save link verification: check portal_url returns HTTP < 400
            try:
                final_url, is_valid = await _verify_portal_url(r.extract.portal_url, r.url)
                if not is_valid:
                    dead_links += 1
                    logger.warning(
                        "Skipping upsert for %s: both portal_url and source URL are dead (404)",
                        r.url,
                    )
                    continue
                # Update the extract with the verified URL (may have fallen back to source URL)
                r.extract.portal_url = final_url
            except Exception as exc:  # noqa: BLE001
                logger.debug("Link verification failed for %s: %s — proceeding with save", r.url, exc)

            try:
                _, action = upsert_scholarship(db, r.extract)
                if action == "created":
                    created += 1
                elif action == "updated":
                    updated += 1
                else:
                    unchanged += 1
                logger.info("[%s] %s -> %s (%s)", r.status, r.url, r.extract.title, action)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                errors += 1
                logger.error("Upsert failed for %s: %s", r.url, exc)

        archived = archive_expired(db)
        logger.info("Auto-archival: %d expired scholarship(s) archived", archived)
    finally:
        db.close()

    logger.info("Summary: created=%d updated=%d unchanged=%d errors=%d dead_links=%d archived=%d",
                created, updated, unchanged, errors, dead_links, archived)
    return results


# ---------------------------------------------------------------------------
# Daily scheduler
# ---------------------------------------------------------------------------


async def run_daily(at_hour: int = 3, at_minute: int = 0) -> None:
    """Run the pipeline once per day at the given local time."""
    logger.info("Daily scheduler started; will run at %02d:%02d local time", at_hour, at_minute)
    while True:
        now = datetime.now()
        next_run = now.replace(hour=at_hour, minute=at_minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        sleep_seconds = (next_run - now).total_seconds()
        logger.info("Next run at %s (in %.0f seconds)", next_run.isoformat(), sleep_seconds)
        await asyncio.sleep(sleep_seconds)
        try:
            await run_pipeline("all")
        except Exception as exc:  # noqa: BLE001
            logger.error("Daily run failed: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: Optional[List[str]] = None) -> int:
    # Load .env from the backend directory so DATABASE_URL, OPENAI_API_KEY, etc.
    # are available when running the scraper as a standalone CLI.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        prog="scrapers.runner",
        description="GrantRx three-tier scraper runner",
    )
    parser.add_argument("--target", default="all", help="'all' or a specific URL")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to the database")
    parser.add_argument("--schedule", action="store_true", help="Run as a daily scheduler (blocks)")
    parser.add_argument("--hour", type=int, default=3, help="Daily run hour (default 03)")
    parser.add_argument("--minute", type=int, default=0, help="Daily run minute (default 00)")
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help=(
            "Filter sources by category. One of: national_association, "
            "federal_program, hospital_system, diversity_affinity, "
            "corporate_unrestricted, regional_foundation, honor_society"
        ),
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="Filter regional sources by 2-letter state code (e.g. CA, NY, TX)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of sources processed in this run",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--crawl",
        action="store_true",
        help="Run the focused web crawler to discover new scholarship sources",
    )
    parser.add_argument(
        "--seeds-file",
        type=str,
        default=None,
        help="Path to a JSON file with seed URLs for crawling (default: scrapers/seeds.json)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="Maximum crawl depth from each seed (default 2)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=15,
        help="Maximum pages to crawl per domain (default 15)",
    )
    parser.add_argument(
        "--limit-extract",
        type=int,
        default=None,
        help="Cap LLM extraction to top N candidates by score (conserves API usage)",
    )
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    if args.schedule:
        asyncio.run(run_daily(at_hour=args.hour, at_minute=args.minute))
        return 0

    if args.crawl:
        seeds = _load_crawl_seeds(args.seeds_file)
        if not seeds:
            logger.error("No seeds loaded — nothing to crawl.")
            return 1
        summary = asyncio.run(
            run_crawl_pipeline(
                seeds,
                max_depth=args.max_depth,
                max_pages_per_domain=args.max_pages,
                dry_run=args.dry_run,
                limit_extract=args.limit_extract,
            )
        )
        print(json.dumps(summary, indent=2, default=str))
        return 0

    results = asyncio.run(
        run_pipeline(
            args.target,
            dry_run=args.dry_run,
            category=args.category,
            state=args.state,
            limit=args.limit,
        )
    )
    # Print a JSON summary to stdout for CLI consumers
    summary = [
        {
            "url": r.url,
            "status": r.status,
            "title": r.extract.title if r.extract else None,
            "provider": r.extract.provider if r.extract else None,
            "award_amount": r.extract.award_amount if r.extract else None,
            "deadline": r.extract.deadline if r.extract else None,
            "source": r.extract.source if r.extract else None,
            "source_category": r.extract.source_category if r.extract else None,
            "error": r.error,
        }
        for r in results
    ]
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

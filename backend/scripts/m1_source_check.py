"""M1 maintenance: re-check catalog source health through the compliant path.

Selects catalog_sources rows by health state or explicit source_key, fetches
each URL through the C6 FetchSession (honest EdFintiaBot identity, robots.txt,
per-host pacing, bounded retry — same code path the C7 due-source pipeline
uses), and either reports the outcome or persists it via
``source_registry.record_check``.

This tool NEVER extracts and NEVER touches scholarship records — it exists to
re-establish honest source health after URL maintenance. ``--dry-run``
(default) performs the live fetch but writes nothing.

Usage:
    python -m scripts.m1_source_check --health permanent_not_found
    python -m scripts.m1_source_check --key aacn-student-scholarship-directory
    python -m scripts.m1_source_check --all-unhealthy --write
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("scripts.m1_source_check")

# Health states that mean "not currently serving cleanly". Everything except
# healthy — includes transient/robots states so one invocation can sweep the
# whole non-healthy registry.
NON_HEALTHY = (
    "unknown",
    "permanent_not_found",
    "needs_url_review",
    "access_denied",
    "redirected_or_moved",
    "robots_denied",
    "robots_unavailable",
    "transient_failure",
)


def _select(db, healths: List[str], keys: List[str]):
    from app.models.models import CatalogSource

    q = db.query(CatalogSource)
    if keys:
        q = q.filter(CatalogSource.source_key.in_(keys))
    elif healths:
        q = q.filter(CatalogSource.health.in_(healths))
    else:
        q = q.filter(CatalogSource.health.in_(NON_HEALTHY))
    return q.order_by(CatalogSource.health, CatalogSource.source_key).all()


async def run(healths: List[str], keys: List[str], write: bool) -> dict:
    from dotenv import load_dotenv

    load_dotenv()

    from app.database import SessionLocal
    from scrapers.fetch_policy import FetchResult, OUTCOME_NETWORK_ERROR, default_session
    from scrapers.fetcher import fetch_result
    from scrapers.source_registry import classify_health, record_check

    db = SessionLocal()
    session = default_session()
    results = []
    try:
        sources = _select(db, healths, keys)
        logger.info("Checking %d source(s)", len(sources))
        for src in sources:
            session.prime_validators(src.url, src.etag, src.last_modified)

        sem = asyncio.Semaphore(6)

        async def _one(src):
            async with sem:
                try:
                    res = await fetch_result(
                        src.url, scraper_type=src.scraper_type or "deterministic",
                        session=session)
                except Exception as exc:  # noqa: BLE001
                    res = FetchResult(url=src.url, outcome=OUTCOME_NETWORK_ERROR,
                                      error=type(exc).__name__)
                return src, res

        pairs = await asyncio.gather(*(_one(s) for s in sources)) if sources else []
        for src, res in pairs:
            would = classify_health(src.health, res)
            results.append({
                "source_key": src.source_key,
                "url": src.url,
                "old_health": src.health,
                "outcome": res.outcome,
                "http_status": res.http_status,
                "final_url": res.final_url,
                "permanent_redirect": res.permanent_redirect,
                "new_health_if_persisted": would,
            })
            if write:
                record_check(db, src, res)
    finally:
        db.close()
        await session.aclose()
    return {"checked": len(results), "results": results}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.m1_source_check")
    parser.add_argument("--health", action="append", default=[],
                        help="Health state to select (repeatable)")
    parser.add_argument("--key", action="append", default=[],
                        help="Explicit source_key to check (repeatable)")
    parser.add_argument("--all-unhealthy", action="store_true",
                        help="Check every source not currently 'healthy'")
    parser.add_argument("--write", action="store_true",
                        help="Persist each result via record_check")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    summary = asyncio.run(run(args.health, args.key, write=args.write))

    mode = "WRITE" if args.write else "DRY-RUN"
    print(f"\n{'=' * 78}\nM1 SOURCE CHECK ({mode}) — {summary['checked']} source(s)\n{'=' * 78}")
    for r in summary["results"]:
        print(f"{r['old_health']:>22} -> {r['new_health_if_persisted']:<22} "
              f"{r['outcome']:<18} HTTP {r['http_status']} "
              f"{'301/308 ' if r['permanent_redirect'] else ''}"
              f"{r['source_key']}")
        if r["final_url"]:
            print(f"{'':>26} resolved: {r['final_url']}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())

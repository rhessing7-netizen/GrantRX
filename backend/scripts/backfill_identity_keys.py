"""Backfill persisted opportunity identity (migration 024 / Catalog Batch C4).

Run AFTER migrations/024_persisted_opportunity_identity.sql:

    python -m scripts.backfill_identity_keys            # live
    python -m scripts.backfill_identity_keys --dry-run  # report only

What it does:
  1. Computes identity_key / identity_fallback_key for every scholarship row
     using scrapers.utils.identity — the same implementation the upsert path
     queries, so stored keys can never diverge from lookup keys.
  2. Detects collisions: two rows that compute the same identity_key. They
     are REPORTED, never merged or deleted — user tracking rows are never
     touched. A collision means the identity rules would treat those rows as
     the same opportunity; that requires human review (E6 owns duplicate
     review), not an automated migration-time merge.
  3. When the catalog is collision-free, creates the unique indexes that make
     identity a database boundary (concurrent-ingestion safety).

Exit codes: 0 = clean (keys written, unique indexes ensured);
            2 = collisions found (keys still written, unique indexes SKIPPED —
                re-run after the colliding rows are resolved).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("scripts.backfill_identity_keys")

UNIQUE_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_scholarships_identity_key "
    "ON scholarships (identity_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_scholarships_identity_fallback_key "
    "ON scholarships (identity_fallback_key)",
)


def compute_rows(db) -> List[dict]:
    """Return [{row, identity_key, identity_fallback_key}] for every row."""
    from app.models.models import Scholarship
    from scrapers.utils.identity import compute_identity_keys

    results = []
    for s in db.query(Scholarship).all():
        key, fallback = compute_identity_keys(
            s.title, s.provider, s.portal_url, s.source_url,
        )
        results.append({"row": s, "identity_key": key, "identity_fallback_key": fallback})
    return results


def find_collisions(results: List[dict]) -> Dict[str, List]:
    """Group rows that claim the same identity value in EITHER column.

    A tp: value stored as one row's identity_key and another row's
    identity_fallback_key is still one identity claimed by two rows — the
    union of both columns is the collision domain.
    """
    by_key: Dict[str, List] = defaultdict(list)
    for r in results:
        s = r["row"]
        for key in (r["identity_key"], r["identity_fallback_key"]):
            if key and all(s.id is not o.id for o in by_key[key]):
                by_key[key].append(s)
    return {k: rows for k, rows in by_key.items() if len(rows) > 1}


def backfill(dry_run: bool = False) -> int:
    from dotenv import load_dotenv

    load_dotenv()

    from sqlalchemy import text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        results = compute_rows(db)
        collisions = find_collisions(results)

        print(f"Rows examined: {len(results)}")
        if collisions:
            print("\nIDENTITY COLLISIONS (NOT merged, NOT deleted — review required):")
            for key, rows in collisions.items():
                print(f"  {key!r}:")
                for s in rows:
                    print(f"    {s.id}  {s.title!r} / {s.provider!r} / {s.portal_url!r}")

        written = 0
        for r in results:
            s = r["row"]
            if s.identity_key != r["identity_key"] or s.identity_fallback_key != r["identity_fallback_key"]:
                written += 1
                if not dry_run:
                    s.identity_key = r["identity_key"]
                    s.identity_fallback_key = r["identity_fallback_key"]
        print(f"Keys written: {0 if dry_run else written} (dry-run would write {written})")

        if collisions:
            print("\nUnique indexes NOT created — resolve the collisions above first.")
            if not dry_run:
                db.commit()
            return 2

        if not dry_run:
            db.commit()
            for stmt in UNIQUE_INDEXES:
                db.execute(text(stmt))
            db.commit()
            print("Unique indexes ensured: uq_scholarships_identity_key, "
                  "uq_scholarships_identity_fallback_key")
        else:
            print("Dry run: unique index creation skipped.")
        return 0
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backfill scholarship identity keys (migration 024)")
    parser.add_argument("--dry-run", action="store_true", help="Report collisions/writes without changing data")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

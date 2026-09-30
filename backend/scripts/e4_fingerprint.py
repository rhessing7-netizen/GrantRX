"""E4 catalog fingerprint + coverage snapshot (read-only).

Captures the authoritative before/after picture for the E4 systematic
catalog-growth phase:

  * scholarships: total, lifecycle, verification, discoverable
  * catalog_sources: total, health distribution
  * scholarship_tracks: total
  * coverage: funding_type, provider_type, scope, academic_levels,
    eligible_disciplines, state_restrictions

Usage:
    DATABASE_URL=postgresql://grantrx:grantrx@127.0.0.1:5433/grantrx \
        python -m scripts.e4_fingerprint [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def fingerprint(db) -> dict:
    from app.models.models import CatalogSource, Scholarship, ScholarshipTrack

    rows = db.query(
        Scholarship.verification_status,
        Scholarship.lifecycle_status,
    ).all()
    ver = Counter(v or "null" for v, _ in rows)
    life = Counter(l or "null" for _, l in rows)

    sources = db.query(CatalogSource.health, CatalogSource.enabled).all()
    health = Counter(h or "null" for h, _ in sources)

    tracks = db.query(ScholarshipTrack).count()

    return {
        "opportunities": {
            "total": len(rows),
            "verification": dict(ver),
            "lifecycle": dict(life),
            "discoverable": sum(
                1 for v, l in rows
                if l == "published" and v != "needs_review"),
        },
        "tracks": tracks,
        "catalog_sources": {
            "total": len(sources),
            "health": dict(health),
            "enabled": sum(1 for _, e in sources if e),
        },
    }


def coverage(db) -> dict:
    from sqlalchemy import func

    from app.models.models import Scholarship

    base = db.query(Scholarship)

    def _col_counts(col):
        return {
            (k if k is not None else "null"): v
            for k, v in db.query(col, func.count())
            .group_by(col).all()
        }

    funding = _col_counts(Scholarship.funding_type)
    provider = _col_counts(Scholarship.provider_type)
    scope = _col_counts(Scholarship.scope)

    disc: Counter = Counter()
    creds: Counter = Counter()
    levels: Counter = Counter()
    states: Counter = Counter()
    for (arr,) in db.query(Scholarship.eligible_disciplines).all():
        for d in (arr or ["<empty>"]):
            disc[d] += 1
    for (arr,) in db.query(Scholarship.eligible_credentials).all():
        for c in (arr or ["<empty>"]):
            creds[c] += 1
    for (arr,) in db.query(Scholarship.academic_levels).all():
        for a in (arr or ["<empty>"]):
            levels[a] += 1
    for (arr,) in db.query(Scholarship.state_restrictions).all():
        for s in (arr or []):
            states[s] += 1

    published = db.query(Scholarship).filter(
        Scholarship.lifecycle_status == "published").count()

    return {
        "rows_examined": base.count(),
        "published": published,
        "funding_type": funding,
        "provider_type": provider,
        "scope": scope,
        "disciplines": dict(disc.most_common()),
        "credentials": dict(creds.most_common()),
        "academic_levels": dict(levels.most_common()),
        "states_restricted_to": dict(states.most_common()),
        "unrestricted_state_rows": db.query(Scholarship).filter(
            Scholarship.state_restrictions.is_(None)).count(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="scripts.e4_fingerprint")
    parser.add_argument("--json", action="store_true",
                        help="emit raw JSON only")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()
    from app.database import SessionLocal, DATABASE_URL
    print(f"# DB: {DATABASE_URL.split('@')[-1]}", file=sys.stderr)

    db = SessionLocal()
    try:
        out = {
            "fingerprint": fingerprint(db),
            "coverage": coverage(db),
        }
    finally:
        db.close()

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

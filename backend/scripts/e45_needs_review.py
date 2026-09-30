"""E4.5 read-only needs_review classification for E4-sourced records.

Joins the Q1 engine's own reason taxonomy (scrapers.review.classify_backlog)
with E4 debt dimensions: funding_type null/other, source category (employer,
state agency, association), and lifecycle. No writes.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
assert "5433" in os.environ.get("DATABASE_URL", ""), "pin DATABASE_URL to :5433"

from app.database import SessionLocal  # noqa: E402
from app.models.models import CatalogSource, Scholarship  # noqa: E402
from scrapers.review import classify_backlog  # noqa: E402

HERE = os.path.dirname(__file__)


def e4_urls(db):
    keys = set(json.load(open(os.path.join(HERE, "e4_new_source_keys.json"))))
    return {s.url: s.category for s in db.query(CatalogSource).filter(CatalogSource.source_key.in_(keys))} | {
        "https://ccpe.nebraska.gov/financial-aid": "state_agency"}


def main(dump=None):
    db = SessionLocal()
    urls = e4_urls(db)
    rows = {str(r.id): r for r in db.query(Scholarship).filter(Scholarship.verification_status == "needs_review")}
    cls = [c for c in classify_backlog(db) if c["source_url"] in urls]
    print("E4 needs_review records:", len(cls), "(of", len(rows), "total needs_review)")
    print("lifecycle:", dict(Counter(c["lifecycle_status"] for c in cls)))
    print("queue:", dict(Counter(c["queue"] for c in cls)))
    rc = Counter(r for c in cls for r in c["reasons"] + c["evidence_checks"])
    print("reasons (multi-count):", dict(rc.most_common()))
    print("no Q1 blocker at all:", sum(1 for c in cls if not c["reasons"] and not c["evidence_checks"]))
    print("funding_type:", dict(Counter(rows[c["id"]].funding_type or "null" for c in cls)))
    print("source category:", dict(Counter(urls[c["source_url"]] for c in cls)))
    print("provider_type null:", sum(1 for c in cls if not rows[c["id"]].provider_type))
    print("published+discoverable-if-cleared:", sum(1 for c in cls if c["lifecycle_status"] == "published"))
    if dump:
        out = []
        for c in cls:
            r = rows[c["id"]]
            out.append(dict(c, funding_type=r.funding_type, category=urls[c["source_url"]],
                            provider_type=r.provider_type, disciplines=r.eligible_disciplines,
                            employment_required=r.employment_required))
        json.dump(out, open(dump, "w", encoding="utf-8"), indent=1, default=str)
    db.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)

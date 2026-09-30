"""E4.5 Part C: run the established Q1 clearance engine (scrapers.review.run_clearance)
and persist per-record outcomes + field before/after to the E4.5 mutation log."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
assert "5433" in os.environ.get("DATABASE_URL", ""), "pin DATABASE_URL to :5433"

from app.database import SessionLocal  # noqa: E402
from app.models.models import Scholarship  # noqa: E402
from scrapers.review import run_clearance  # noqa: E402

HERE = os.path.dirname(__file__)
FIELDS = ("verification_status", "award_amount", "deadline", "min_gpa", "eligible_disciplines",
          "is_general_major", "lifecycle_status")


def snap(db):
    return {str(r.id): {f: getattr(r, f) for f in FIELDS}
            for r in db.query(Scholarship).filter(Scholarship.verification_status == "needs_review")}


async def main(dry):
    db = SessionLocal()
    before = snap(db)
    res = await run_clearance(db, dry_run=dry)
    db.expire_all()
    after = {i: {f: getattr(db.get(Scholarship, i), f) for f in FIELDS} for i in before}
    json.dump(res, open(os.path.join(HERE, "e45_q1_result.json"), "w"), indent=1, default=str)
    if not dry:
        ts = datetime.now(timezone.utc).isoformat()
        with open(os.path.join(HERE, "e45_mutation_log.jsonl"), "a", encoding="utf-8") as fh:
            for i, o in res["outcomes"].items():
                changed = {f: [before[i][f], after[i][f]] for f in FIELDS if before[i][f] != after[i][f]}
                if changed:
                    fh.write(json.dumps(dict(op="q1_clearance", id=i, action=o["action"], degraded=o["degraded"],
                                             changed=changed, ts=ts, plan="part_c_q1"), default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "outcomes"}, indent=1, default=str))
    db.close()


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))

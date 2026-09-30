"""E4.5 logged catalog mutations (local :5433 only).

Every mutation appends a JSON line (before/after) to scripts/e45_mutation_log.jsonl.
Archives go through app.services.lifecycle; identity keys are recomputed with
the production compute_identity_keys whenever title/provider/URLs change.

Usage: python scripts/e45_mutate.py plan.json
plan.json: [{"op": "archive", "id": ..., "reason": "duplicate", "note": ...},
            {"op": "set", "id": ..., "fields": {...}, "note": ...},
            {"op": "source", "source_key": ..., "fields": {...}, "note": ...}]
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
assert "5433" in os.environ.get("DATABASE_URL", ""), "pin DATABASE_URL to :5433"

from app.database import SessionLocal  # noqa: E402
from app.models.models import CatalogSource, Scholarship  # noqa: E402
from app.services import lifecycle  # noqa: E402
from scrapers.utils.identity import compute_identity_keys  # noqa: E402

LOG = os.path.join(os.path.dirname(__file__), "e45_mutation_log.jsonl")
IDENTITY_INPUTS = {"title", "provider", "portal_url", "source_url"}
SNAP = ("title", "provider", "provider_type", "funding_type", "portal_url", "lifecycle_status",
        "archive_reason", "verification_status", "employment_required", "identity_key",
        "identity_fallback_key")


def _snap(obj, fields):
    return {f: getattr(obj, f, None) for f in fields}


def run(plan_path):
    plan = json.load(open(plan_path, encoding="utf-8"))
    db = SessionLocal()
    entries = []
    for step in plan:
        op = step["op"]
        if op == "source":
            src = db.query(CatalogSource).filter(CatalogSource.source_key == step["source_key"]).one()
            fields = list(step["fields"])
            before = _snap(src, fields)
            for k, v in step["fields"].items():
                setattr(src, k, v)
            entries.append(dict(op=op, source_key=step["source_key"], before=before,
                                after=_snap(src, fields), note=step.get("note")))
            continue
        row = db.get(Scholarship, step["id"])
        if row is None:
            raise SystemExit(f"missing scholarship {step['id']}")
        before = _snap(row, SNAP + tuple(step.get("fields", {})))
        if op == "archive":
            if row.lifecycle_status == "archived":
                print("skip (already archived):", row.title)
                continue
            lifecycle.archive(row, step["reason"])
        elif op == "set":
            for k, v in step["fields"].items():
                if k == "deadline" and isinstance(v, str):
                    from datetime import date
                    v = date.fromisoformat(v)
                setattr(row, k, v)
            if IDENTITY_INPUTS & set(step["fields"]):
                ik, fk = compute_identity_keys(row.title, row.provider, row.portal_url, row.source_url)
                clash = db.query(Scholarship).filter(
                    Scholarship.id != row.id,
                    (Scholarship.identity_key.in_([k for k in (ik, fk) if k]))
                    | (Scholarship.identity_fallback_key.in_([k for k in (ik, fk) if k])),
                ).first()
                if clash is not None:
                    raise SystemExit(f"identity clash for {row.title!r} with {clash.id}")
                row.identity_key, row.identity_fallback_key = ik, fk
        else:
            raise SystemExit(f"unknown op {op}")
        entries.append(dict(op=op, id=str(row.id), title=row.title, reason=step.get("reason"),
                            before=before, after=_snap(row, SNAP + tuple(step.get("fields", {}))),
                            note=step.get("note")))
    db.commit()
    db.close()
    ts = datetime.now(timezone.utc).isoformat()
    with open(LOG, "a", encoding="utf-8") as fh:
        for e in entries:
            e["ts"] = ts
            e["plan"] = os.path.basename(plan_path)
            fh.write(json.dumps(e, default=str) + "\n")
    print(f"applied {len(entries)} mutation(s) from {os.path.basename(plan_path)}")
    for e in entries:
        print(" ", e["op"], e.get("reason") or "", "|", e.get("title") or e.get("source_key"))


if __name__ == "__main__":
    run(sys.argv[1])

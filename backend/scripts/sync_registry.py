"""Import configured sources into the C7 registry, idempotently.

    python -m scripts.sync_registry [--dry-run]

Imports scrapers/sources.json -> catalog_sources and scrapers/seeds.json ->
crawler_seeds. Safe to re-run: matched rows are updated, never duplicated,
and operational state (health, scheduling, validators) is preserved.
"""

from __future__ import annotations

import json
import sys

from app.database import SessionLocal
from scrapers.source_registry import registry_summary, sync_seeds, sync_sources


def sync_all(dry_run: bool = False) -> dict:
    db = SessionLocal()
    try:
        if dry_run:
            return {"dry_run": True, "registry": registry_summary(db)}
        out = {
            "sources": sync_sources(db),
            "seeds": sync_seeds(db),
            "registry": registry_summary(db),
        }
        return out
    finally:
        db.close()


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dry_run = "--dry-run" in argv
    print(json.dumps(sync_all(dry_run=dry_run), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

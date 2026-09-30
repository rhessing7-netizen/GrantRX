"""Copy the frozen catalog tables from the local E2E database to a staging DB.

Copies ONLY catalog-owned tables (scholarships, scholarship_tracks,
catalog_sources, crawler_seeds). User-owned tables (profiles, tracking,
waitlist, etc.) are intentionally NOT copied — staging starts with no user data.

Source is always the local frozen catalog on 127.0.0.1:5433/grantrx
(override with SOURCE_DATABASE_URL for future use). The target is
TARGET_DATABASE_URL and must not be localhost or port 5432.

Usage:
    TARGET_DATABASE_URL=postgresql://... python scripts/sync_catalog_to_staging.py
    TARGET_DATABASE_URL=... python scripts/sync_catalog_to_staging.py --dry-run
"""

from __future__ import annotations

import os
import sys

import psycopg

CATALOG_TABLES = [
    "catalog_sources",
    "crawler_seeds",
    "scholarship_tracks",
    "scholarships",
]

DEFAULT_SOURCE = "postgresql://grantrx:grantrx@127.0.0.1:5433/grantrx"


def _target(required: bool = True) -> str:
    url = (os.getenv("TARGET_DATABASE_URL") or "").strip()
    if not url:
        if required:
            sys.exit("TARGET_DATABASE_URL is required.")
        return ""
    lowered = url.lower()
    if "localhost" in lowered or "127.0.0.1" in lowered or ":5432/" in lowered:
        sys.exit("Refusing to target localhost / port 5432.")
    return url


def main() -> int:
    source_url = os.getenv("SOURCE_DATABASE_URL", DEFAULT_SOURCE)
    dry_run = "--dry-run" in sys.argv
    target_url = _target(required=not dry_run)

    with psycopg.connect(source_url) as src:
        counts = {
            t: src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in CATALOG_TABLES
        }
        if counts.get("scholarships") != 830:
            sys.exit(
                f"Source fingerprint mismatch: scholarships={counts.get('scholarships')} "
                "(expected 830 frozen rows). Aborting."
            )
        data = {
            t: src.execute(f"SELECT * FROM {t}").fetchall()
            for t in CATALOG_TABLES
        }
        cols = {
            t: [d.name for d in src.execute(f"SELECT * FROM {t} LIMIT 0").description]
            for t in CATALOG_TABLES
        }

    print("source counts:", counts)
    if dry_run:
        print("dry-run — no writes.")
        return 0

    with psycopg.connect(target_url, autocommit=True) as tgt:
        for t in CATALOG_TABLES:
            # Catalog tables are replaced wholesale — staging mirrors the frozen
            # local catalog exactly. User tables are never touched.
            tgt.execute(f"TRUNCATE {t} RESTART IDENTITY CASCADE")
            if not data[t]:
                print(f"{t}: empty, truncated only")
                continue
            placeholders = ", ".join(["%s"] * len(cols[t]))
            with tgt.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {t} ({', '.join(cols[t])}) VALUES ({placeholders})",
                    data[t],
                )
            print(f"{t}: copied {len(data[t])} rows")
    print("Catalog sync complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

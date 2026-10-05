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
from psycopg.types.json import Jsonb

CATALOG_TABLES = [
    "catalog_sources",
    "crawler_seeds",
    "scholarship_tracks",
    "scholarships",
]

# Dependency order for inserts inside the single sync transaction:
# scholarship_tracks.scholarship_id -> scholarships.id is an immediate FK, so
# parents must land before tracks. catalog_sources/crawler_seeds have no FKs.
INSERT_ORDER = [
    "catalog_sources",
    "crawler_seeds",
    "scholarships",
    "scholarship_tracks",
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


def _jsonb_columns(src, table: str) -> set:
    """Public-schema json/jsonb columns for *table* (source introspection).

    The source and destination share the same migration-built schema, so the
    source's catalog is authoritative for column types. Genuine PostgreSQL
    ARRAY columns are deliberately excluded — psycopg already adapts Python
    lists to arrays correctly; only JSON/JSONB needs explicit Jsonb wrapping.
    """
    return {
        r[0]
        for r in src.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "AND data_type IN ('json', 'jsonb')",
            (table,),
        ).fetchall()
    }


def _adapt_row(row, cols, jsonb_cols):
    """Wrap JSON/JSONB-bound values in Jsonb(); leave everything else alone.

    psycopg decodes jsonb to Python dict/list and would otherwise re-encode a
    bare list as a PostgreSQL array literal ({PharmD,...}), which the
    destination jsonb column rejects. None stays None (SQL NULL, not 'null').
    """
    if not jsonb_cols:
        return row
    return tuple(
        Jsonb(v) if c in jsonb_cols and v is not None else v
        for c, v in zip(cols, row)
    )


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
        jsonb_cols = {t: _jsonb_columns(src, t) for t in CATALOG_TABLES}

    print("source counts:", counts)
    if dry_run:
        print("dry-run — no writes.")
        return 0

    with psycopg.connect(target_url) as conn:
        with conn.transaction():
            # Catalog tables are replaced wholesale — staging mirrors the frozen
            # local catalog exactly. User tables are never touched. TRUNCATE ...
            # CASCADE covers scholarship_tracks (FK child of scholarships); all
            # truncates and inserts run in ONE transaction so a failure rolls
            # the whole sync back instead of leaving a half-replaced catalog.
            for t in CATALOG_TABLES:
                conn.execute(f"TRUNCATE {t} RESTART IDENTITY CASCADE")
            for t in INSERT_ORDER:
                if not data[t]:
                    print(f"{t}: empty, truncated only")
                    continue
                placeholders = ", ".join(["%s"] * len(cols[t]))
                with conn.cursor() as cur:
                    cur.executemany(
                        f"INSERT INTO {t} ({', '.join(cols[t])}) VALUES ({placeholders})",
                        (_adapt_row(r, cols[t], jsonb_cols[t]) for r in data[t]),
                    )
                print(f"{t}: copied {len(data[t])} rows")
    print("Catalog sync complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

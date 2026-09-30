"""Apply backend/migrations/*.sql to DATABASE_URL, in filename order.

Idempotent: applied filenames are recorded in a `schema_migrations` table and
skipped on re-run. Each migration runs in its own transaction so a failure
stops at the offending file without half-applying it.

Usage:
    DATABASE_URL=postgresql://... python scripts/apply_migrations.py
    DATABASE_URL=... python scripts/apply_migrations.py --status

Safety: refuses to run when DATABASE_URL is unset, points at port 5432, or
points at the local E2E catalog (127.0.0.1:5433/grantrx) which already has
the full schema.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _target() -> str:
    url = (os.getenv("TARGET_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        sys.exit("DATABASE_URL (or TARGET_DATABASE_URL) is required.")
    if ":5432/" in url or "@localhost/" in url.replace("127.0.0.1", "localhost"):
        sys.exit("Refusing to run against localhost / port 5432.")
    if "127.0.0.1:5433/grantrx" in url or "localhost:5433/grantrx" in url:
        sys.exit("Refusing to run against the frozen local E2E catalog.")
    return url


def main() -> int:
    url = _target()
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        sys.exit(f"No migration files in {MIGRATIONS_DIR}")

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(filename text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
        )
        applied = {
            r[0]
            for r in conn.execute("SELECT filename FROM schema_migrations").fetchall()
        }

    if "--status" in sys.argv:
        print(f"{len(applied)}/{len(files)} migrations applied")
        for f in files:
            print(("applied " if f.name in applied else "pending ") + f.name)
        return 0

    pending = [f for f in files if f.name not in applied]
    if not pending:
        print("All migrations already applied.")
        return 0

    for f in pending:
        sql = f.read_text(encoding="utf-8")
        with psycopg.connect(url) as conn:
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (f.name,),
                )
        print(f"applied {f.name}")

    print(f"Done: {len(pending)} migration(s) applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

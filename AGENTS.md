# GrantRx / EdFintia — agent notes

## WARNING — ENVIRONMENT DEBT (pre-production): local catalog DB lives under %TEMP%

The authoritative local development catalog database (127.0.0.1:5433 / grantrx,
embedded PostgreSQL 18, WIN1252 encoding) is stored at:

    %TEMP%\grantrx-e2e\pgdata     (C:\Users\rhess\AppData\Local\Temp\grantrx-e2e\pgdata)

OS temp cleanup (Storage Sense, Disk Cleanup, profile resets) can DELETE it and
destroy the curated catalog. It has not been migrated yet (to be addressed
separately — do not move it ad hoc).

- Start (non-destructive): `node restart-pg.mjs` from `%TEMP%\grantrx-e2e`
  (only `pg.start()` on the existing data dir).
- NEVER run `start-pg.mjs` against existing data — it calls `initialise()` and
  `createDatabase()`.
- localhost:5432 is a separate Postgres 17 service — never use it for catalog work.
- Never connect to production / Supabase from local catalog tooling.

## Backend verification

- Full suite (no DB needed): `cd backend && python -m pytest tests/ -q -p no:warnings`
- Catalog fingerprint: `DATABASE_URL=postgresql://grantrx:grantrx@127.0.0.1:5433/grantrx python scripts/e4_fingerprint.py`
- Duplicate candidates (read-only): `scrapers/utils/dup_audit.py::find_candidates`
- Review engine: `python -m scrapers.review --classify|--queue|--run [--dry-run]`
  (`--include-archived` = explicit current-cycle review of deadline_passed only;
  duplicate/manual/discontinued/source_removed archives are never worked)
- Catalog mutations: `scripts/e45_mutate.py <plan.json>` (logs to `scripts/e45_mutation_log.jsonl`)

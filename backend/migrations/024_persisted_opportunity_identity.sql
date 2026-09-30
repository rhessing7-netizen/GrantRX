-- Catalog Batch C4 - persisted opportunity identity.
--
-- Additive and non-destructive. Adds the persisted, indexed identity columns
-- that replace the per-upsert full-table identity scan.
--
-- IMPORTANT: this migration deliberately does NOT create the unique index.
-- Identity values are computed by scrapers/utils/identity.py; the backfill
-- must run through that Python implementation so the stored keys exactly
-- match the keys the upsert path will query. Run, in order:
--   1. this migration (columns + non-unique indexes)
--   2. python -m scripts.backfill_identity_keys
-- The backfill script populates keys, reports collisions WITHOUT merging or
-- deleting anything, and creates the unique indexes only when the catalog is
-- collision-free.
--
-- Prerequisite: migrations 020-023 applied. Idempotent (safe to re-run).

ALTER TABLE scholarships
  ADD COLUMN IF NOT EXISTS identity_key          TEXT,
  ADD COLUMN IF NOT EXISTS identity_fallback_key TEXT;

CREATE INDEX IF NOT EXISTS idx_scholarships_identity_key
  ON scholarships (identity_key);
CREATE INDEX IF NOT EXISTS idx_scholarships_identity_fallback_key
  ON scholarships (identity_fallback_key);

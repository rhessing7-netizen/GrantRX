-- Catalog Batch C3 - opportunity lifecycle foundation.
--
-- Additive and non-destructive. lifecycle_status becomes the authoritative
-- publication state; is_archived is retained as a compatibility mirror and is
-- derived from lifecycle_status by trigger so the two cannot drift.
--
-- Prerequisite: migrations 020-022 applied. Idempotent (safe to re-run).

-- 1. Columns ---------------------------------------------------------------
ALTER TABLE scholarships
  ADD COLUMN IF NOT EXISTS lifecycle_status   TEXT        NOT NULL DEFAULT 'published',
  ADD COLUMN IF NOT EXISTS archive_reason     TEXT,
  ADD COLUMN IF NOT EXISTS last_seen_at       TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS last_checked_at    TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS consecutive_misses INTEGER     NOT NULL DEFAULT 0;

-- 2. Conservative backfill -----------------------------------------------------
-- Before C3 the only writers of is_archived = TRUE were:
--   * the deadline archiver / ingestion (requires deadline < today), and
--   * scripts/repair_urls.py (dead portal URL with no safe replacement).
-- So an archived row whose deadline has passed is recorded as
-- 'deadline_passed' (a factual statement regardless of how it was archived),
-- and an archived row with a NULL or future deadline can only have come from
-- the dead-link repair job -> 'dead_link'. dead_link is also the conservative
-- choice: it cannot be auto-resurrected without destination evidence.
UPDATE scholarships
   SET lifecycle_status = 'archived',
       archive_reason = CASE
         WHEN deadline IS NOT NULL AND deadline < CURRENT_DATE THEN 'deadline_passed'
         ELSE 'dead_link'
       END
 WHERE is_archived IS TRUE
   AND lifecycle_status <> 'archived';

-- Active rows keep the column default 'published' (they are discoverable
-- today; pending-verification rows stay publishable by owner policy).
-- last_seen_at / last_checked_at are intentionally left NULL: no observation
-- occurred under C3 semantics, and updated_at is NOT equivalent to an
-- observation, so it is not copied in.

-- 3. Constraints (added after backfill) ------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'scholarships_lifecycle_status_check') THEN
    ALTER TABLE scholarships ADD CONSTRAINT scholarships_lifecycle_status_check
      CHECK (lifecycle_status IN ('draft', 'published', 'stale', 'archived'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'scholarships_archive_reason_check') THEN
    ALTER TABLE scholarships ADD CONSTRAINT scholarships_archive_reason_check
      CHECK (archive_reason IS NULL OR archive_reason IN
        ('deadline_passed', 'dead_link', 'discontinued', 'source_removed', 'duplicate', 'manual'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'scholarships_archive_reason_iff_archived') THEN
    ALTER TABLE scholarships ADD CONSTRAINT scholarships_archive_reason_iff_archived
      CHECK ((lifecycle_status = 'archived') = (archive_reason IS NOT NULL));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'scholarships_consecutive_misses_nonneg') THEN
    ALTER TABLE scholarships ADD CONSTRAINT scholarships_consecutive_misses_nonneg
      CHECK (consecutive_misses >= 0);
  END IF;
END $$;

-- 4. Legacy mirror: is_archived is derived from lifecycle_status -------------
CREATE OR REPLACE FUNCTION scholarships_sync_is_archived() RETURNS trigger AS $$
BEGIN
  NEW.is_archived := (NEW.lifecycle_status = 'archived');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_scholarships_sync_is_archived ON scholarships;
CREATE TRIGGER trg_scholarships_sync_is_archived
  BEFORE INSERT OR UPDATE ON scholarships
  FOR EACH ROW EXECUTE FUNCTION scholarships_sync_is_archived();

-- 5. Indexes for discovery and freshness queries ---------------------------
CREATE INDEX IF NOT EXISTS idx_scholarships_lifecycle_status
  ON scholarships (lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_scholarships_lifecycle_last_seen
  ON scholarships (lifecycle_status, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_scholarships_lifecycle_deadline
  ON scholarships (lifecycle_status, deadline);

-- source_id is intentionally deferred to C7: there is no authoritative source
-- registry yet (sources live in sources.json/seeds.json keyed by mutable
-- names/URLs), so a foreign key today would have unstable semantics.

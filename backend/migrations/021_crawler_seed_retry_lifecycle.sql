-- Migration 021: Add controlled retry/backoff metadata to autonomous crawler seeds.
--
-- A transient crawl failure should not permanently strand a source. Failed
-- seeds become eligible again after next_retry_at. Repeated failures are
-- quarantined for manual review instead of being retried forever.

ALTER TABLE crawler_seeds
  ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMP WITH TIME ZONE NULL,
  ADD COLUMN IF NOT EXISTS last_error TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_crawler_seeds_retry
  ON crawler_seeds (status, next_retry_at, priority DESC);

-- Seeds failed under the old lifecycle had no retry timestamp. Make them
-- eligible immediately so the new retry policy can recover them.
UPDATE crawler_seeds
SET next_retry_at = NOW()
WHERE status = 'failed' AND next_retry_at IS NULL;

-- Record how scholarship facts entered GrantRx and whether important asserted
-- values were independently found in the fetched source page.
ALTER TABLE scholarships
  ADD COLUMN IF NOT EXISTS source_url TEXT,
  ADD COLUMN IF NOT EXISTS extraction_method TEXT,
  ADD COLUMN IF NOT EXISTS verification_status TEXT NOT NULL DEFAULT 'legacy_unverified',
  ADD COLUMN IF NOT EXISTS verified_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_scholarships_verification_status
  ON scholarships (verification_status);

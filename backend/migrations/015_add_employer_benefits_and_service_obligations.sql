-- Migration 015: Add employer tuition assistance, service-obligation, and
-- vendor-platform fields to the scholarships table.
--
-- All new columns have safe defaults so existing records, serializers, and
-- test suites continue to function without modification.

ALTER TABLE scholarships
  ADD COLUMN IF NOT EXISTS funding_type TEXT DEFAULT 'scholarship',
  ADD COLUMN IF NOT EXISTS employment_required BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS min_employment_tenure_months INTEGER DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS annual_benefit_cap INTEGER DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS benefit_coverage_model TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS partner_network TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS has_service_commitment BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS service_commitment_duration_months INTEGER DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS vendor_platform TEXT DEFAULT NULL;

-- B-tree indexes for scalar filtering on the new funding/employment/service flags
CREATE INDEX IF NOT EXISTS idx_scholarships_funding_type ON scholarships (funding_type);
CREATE INDEX IF NOT EXISTS idx_scholarships_employment_required ON scholarships (employment_required) WHERE employment_required = TRUE;
CREATE INDEX IF NOT EXISTS idx_scholarships_has_service_commitment ON scholarships (has_service_commitment) WHERE has_service_commitment = TRUE;

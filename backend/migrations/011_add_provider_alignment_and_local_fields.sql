-- Migration 011: Add provider alignment & local discovery fields to scholarships

ALTER TABLE scholarships
    ADD COLUMN IF NOT EXISTS provider_type VARCHAR,
    ADD COLUMN IF NOT EXISTS provider_mission TEXT,
    ADD COLUMN IF NOT EXISTS provider_core_values TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS is_local BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS target_community VARCHAR;

-- Index for filtering local scholarships
CREATE INDEX IF NOT EXISTS idx_scholarships_is_local ON scholarships (is_local) WHERE is_local = TRUE;

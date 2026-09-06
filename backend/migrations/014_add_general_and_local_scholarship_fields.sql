-- Migration 014: Add general major, academic levels, geographic scope, and
-- low-competition fields to the scholarships table.

ALTER TABLE scholarships
  ADD COLUMN IF NOT EXISTS is_general_major BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS academic_levels TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS scope TEXT DEFAULT 'national',
  ADD COLUMN IF NOT EXISTS county_restrictions TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS city_restrictions TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS competition_level TEXT DEFAULT 'medium';

-- B-tree indexes for scalar filtering
CREATE INDEX IF NOT EXISTS idx_scholarships_is_general_major ON scholarships (is_general_major) WHERE is_general_major = TRUE;
CREATE INDEX IF NOT EXISTS idx_scholarships_scope ON scholarships (scope);
CREATE INDEX IF NOT EXISTS idx_scholarships_competition_level ON scholarships (competition_level);

-- GIN indexes for array containment queries
CREATE INDEX IF NOT EXISTS idx_scholarships_academic_levels_gin ON scholarships USING GIN (academic_levels);
CREATE INDEX IF NOT EXISTS idx_scholarships_county_restrictions_gin ON scholarships USING GIN (county_restrictions);
CREATE INDEX IF NOT EXISTS idx_scholarships_state_restrictions_gin ON scholarships USING GIN (state_restrictions);

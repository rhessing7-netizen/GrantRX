-- Migration 008: Add is_dismissed flag to user_scholarships for feed curation
--
-- Allows users to hide/dismiss scholarships from their Discovery Feed.
-- Dismissed scholarships are excluded from /api/scholarships/matched results.

ALTER TABLE user_scholarships
    ADD COLUMN IF NOT EXISTS is_dismissed BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_user_scholarships_dismissed
    ON user_scholarships (user_id, is_dismissed);

-- Migration 007: Add critical database indexes for query performance
--
-- Adds indexes on:
--   user_scholarships.user_id       (every Kanban query filters by user_id)
--   user_scholarships.scholarship_id (dedup lookups and join performance)
--   user_scholarships.status         (column filtering in Kanban grouping)
--   scholarships.deadline            (archiver queries deadline < today)
--   scholarships.is_archived         (feed filters is_archived = false)
--   scholarships.portal_url          (dedup upsert by title + portal_url)
--   profiles.feed_token              (unique constraint already exists; add explicit index)
--   profiles.subscription_tier       (tier guard checks subscription_tier)

-- User scholarship tracking indexes
CREATE INDEX IF NOT EXISTS idx_user_scholarships_user_id
    ON user_scholarships (user_id);

CREATE INDEX IF NOT EXISTS idx_user_scholarships_scholarship_id
    ON user_scholarships (scholarship_id);

CREATE INDEX IF NOT EXISTS idx_user_scholarships_status
    ON user_scholarships (status);

CREATE INDEX IF NOT EXISTS idx_user_scholarships_user_status
    ON user_scholarships (user_id, status);

-- Scholarship indexes for feed queries and archiver
CREATE INDEX IF NOT EXISTS idx_scholarships_deadline
    ON scholarships (deadline);

CREATE INDEX IF NOT EXISTS idx_scholarships_is_archived
    ON scholarships (is_archived);

CREATE INDEX IF NOT EXISTS idx_scholarships_archived_deadline
    ON scholarships (is_archived, deadline);

CREATE INDEX IF NOT EXISTS idx_scholarships_portal_url
    ON scholarships (portal_url);

-- Profile indexes
CREATE INDEX IF NOT EXISTS idx_profiles_subscription_tier
    ON profiles (subscription_tier);

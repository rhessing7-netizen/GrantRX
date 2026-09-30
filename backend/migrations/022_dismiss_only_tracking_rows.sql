-- Distinguish user_scholarships rows that exist solely to record a discovery
-- dismissal from rows that represent real tracking/application state.
-- dismiss_only=TRUE rows are hidden from GET /user-scholarships (Kanban) and
-- are deleted on undismiss instead of becoming phantom "saved" records.
ALTER TABLE user_scholarships
  ADD COLUMN IF NOT EXISTS dismiss_only BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_user_scholarships_dismiss_only
  ON user_scholarships (user_id, dismiss_only);

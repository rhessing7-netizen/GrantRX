-- 013_add_cancellation_feedback.sql
-- Exit survey feedback collected when users cancel their Premium subscription.

CREATE TABLE IF NOT EXISTS cancellation_feedback (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES profiles(id) ON DELETE SET NULL,
    reason          TEXT NOT NULL CHECK (reason IN ('won_scholarship', 'too_expensive', 'not_enough_opportunities', 'finished_cycle', 'other')),
    award_amount    INTEGER,
    comments        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cancellation_feedback_reason ON cancellation_feedback(reason);
CREATE INDEX IF NOT EXISTS idx_cancellation_feedback_created_at ON cancellation_feedback(created_at);

ALTER TABLE cancellation_feedback ENABLE ROW LEVEL SECURITY;

CREATE POLICY cancellation_feedback_select_own
    ON cancellation_feedback
    FOR SELECT
    USING (user_id = auth.uid());

CREATE POLICY cancellation_feedback_insert_own
    ON cancellation_feedback
    FOR INSERT
    WITH CHECK (user_id = auth.uid());

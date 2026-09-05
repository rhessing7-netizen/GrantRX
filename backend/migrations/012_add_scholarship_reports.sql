-- 012_add_scholarship_reports.sql
-- Crowdsourced scholarship issue reporting (broken links, inaccurate deadlines, expired awards).

CREATE TABLE IF NOT EXISTS scholarship_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scholarship_id  UUID NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
    reported_by     UUID REFERENCES profiles(id) ON DELETE SET NULL,
    reason          TEXT NOT NULL CHECK (reason IN ('broken_link', 'inaccurate_deadline', 'expired')),
    notes           TEXT,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewed', 'resolved')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for filtering open reports in admin review queue
CREATE INDEX IF NOT EXISTS idx_scholarship_reports_status ON scholarship_reports(status);
CREATE INDEX IF NOT EXISTS idx_scholarship_reports_scholarship_id ON scholarship_reports(scholarship_id);

-- Enable RLS so users can only see their own reports (admins use service role)
ALTER TABLE scholarship_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY scholarship_reports_select_own
    ON scholarship_reports
    FOR SELECT
    USING (reported_by = auth.uid());

CREATE POLICY scholarship_reports_insert_own
    ON scholarship_reports
    FOR INSERT
    WITH CHECK (reported_by = auth.uid());

-- Preserve source uncertainty instead of inventing $0 awards or deadlines.
ALTER TABLE scholarships ALTER COLUMN award_amount DROP NOT NULL;
ALTER TABLE scholarships ALTER COLUMN deadline DROP NOT NULL;

COMMENT ON COLUMN scholarships.award_amount IS 'NULL means unknown, variable, or not stated by the source; never coerce unknown to $0.';
COMMENT ON COLUMN scholarships.deadline IS 'NULL means rolling, unknown, or not yet announced; never invent a date.';

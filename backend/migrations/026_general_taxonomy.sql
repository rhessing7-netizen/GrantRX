-- Catalog Batch C8 - general field-of-study taxonomy.
--
-- Additive and non-destructive:
--   * scholarships.eligible_disciplines: clinical_discipline[] -> text[]
--     (canonical field-of-study codes; healthcare is a subtree, not the
--     persisted boundary). Existing values are preserved verbatim — the six
--     legacy enum values remain valid canonical codes.
--   * profiles.primary_discipline: clinical_discipline -> text (same codes).
--   * scholarships.scope / funding_type: drop unsafe defaults. NULL is the
--     "never established" marker; 'national'/'scholarship' now mean
--     *explicitly* unrestricted/stated only.
--   * Backfill: rows that hold scope='national' purely because the old
--     schema defaulted it (i.e. no geographic restriction of any kind was
--     ever extracted) become NULL. Rows with any geographic restriction
--     keep their scope value.
--   * New record-only eligibility dimensions (citizenship, enrollment,
--     institution, military affiliation) and the scholarship_tracks table
--     for parent-program/track modeling (Minnesota decision: tracks are
--     variants of one program, never independent opportunities).
--
-- Idempotent: safe to apply more than once.

-- 1. Discipline columns become free canonical codes.
ALTER TABLE scholarships
    ALTER COLUMN eligible_disciplines TYPE text[] USING eligible_disciplines::text[];
ALTER TABLE profiles
    ALTER COLUMN primary_discipline TYPE text USING primary_discipline::text;

-- 2. Remove unsafe defaults: unknown must not persist as unrestricted.
ALTER TABLE scholarships ALTER COLUMN scope DROP DEFAULT;
ALTER TABLE scholarships ALTER COLUMN funding_type DROP DEFAULT;

-- 3. Backfill: 'national' asserted by default (never established) -> NULL.
--    Rows carrying any geographic restriction keep whatever scope they had.
UPDATE scholarships SET scope = NULL
WHERE scope = 'national'
  AND COALESCE(array_length(state_restrictions, 1), 0) = 0
  AND COALESCE(array_length(metro_restrictions, 1), 0) = 0
  AND COALESCE(array_length(county_restrictions, 1), 0) = 0
  AND COALESCE(array_length(city_restrictions, 1), 0) = 0;

-- 4. C8 record-only eligibility dimensions.
ALTER TABLE scholarships ADD COLUMN IF NOT EXISTS citizenship_requirement text;
ALTER TABLE scholarships ADD COLUMN IF NOT EXISTS enrollment_statuses text[] NOT NULL DEFAULT '{}';
ALTER TABLE scholarships ADD COLUMN IF NOT EXISTS institution_restrictions text[] NOT NULL DEFAULT '{}';
ALTER TABLE scholarships ADD COLUMN IF NOT EXISTS military_affiliation_requirement text;

-- 5. Parent-program tracks. A track shares the parent's administration and
--    application; it carries only the fields that legitimately differ.
CREATE TABLE IF NOT EXISTS scholarship_tracks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scholarship_id uuid NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
    title text NOT NULL,
    detail_url text,
    award_amount integer,
    deadline date,
    eligible_disciplines text[],
    eligible_credentials text[],
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_track_parent_title
    ON scholarship_tracks (scholarship_id, title);
CREATE INDEX IF NOT EXISTS idx_track_scholarship
    ON scholarship_tracks (scholarship_id);

-- Migration 029: public scholarship description.
--
-- Adds scholarships.public_description — EdFintia's consumer-facing
-- narrative summary of an opportunity ("What is this scholarship?").
-- It is produced by grounded extraction against real source material and
-- persisted so detail pages never generate text at request time.
--
-- Semantics:
--   * NULL is a normal, valid state — rows whose source material could not
--     support a faithful summary simply have no narrative. Nothing is
--     backfilled or fabricated by this migration.
--   * Write path: scrapers (ScholarshipExtract → _to_db_dict). The
--     verification layer drops any generated description whose factual
--     claims cannot be located in the source text.
--   * Read paths: PublicOpportunityOut (anonymous detail), ScholarshipOut /
--     MatchedScholarshipOut (authenticated detail) — one persisted field is
--     the single source of truth for both surfaces.
--
-- Additive and non-destructive. Idempotent (safe to re-run).
--
-- Prerequisite: migrations 001-028 applied.
-- NOTE: essay workspace tables are intentionally NOT here — they are
-- planned for migration 030.

ALTER TABLE scholarships
    ADD COLUMN IF NOT EXISTS public_description TEXT;

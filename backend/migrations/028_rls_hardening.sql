-- Migration 028: Row-Level Security hardening.
--
-- Enables RLS on the six tables that migrations 010/016/017/025/026 left
-- unprotected. Under Supabase default grants, a public-schema table without
-- RLS is reachable via the Data API with the anon key — these tables must
-- not be.
--
-- Posture per table:
--   * student_college_budgets — user-owned financial data. Users may read
--     and manage only rows where user_id = auth.uid() (the profile id is the
--     auth user id). All current access flows through the backend API, which
--     connects as the postgres role and bypasses RLS; the policies exist so
--     the documented posture in DATA_PROTECTION_POLICY.md is real and any
--     future direct access is already scoped.
--   * support_conversations / support_tickets — sensitive support data
--     (user email, summaries, full transcripts). No anon/authenticated
--     policies: deny-all. Backend/service-role only.
--   * crawler_seeds / catalog_sources — scraper/registry operational state.
--     No anon/authenticated policies: deny-all. Backend/admin only.
--   * scholarship_tracks — catalog display data, but delivered exclusively
--     through backend APIs today. No anon/authenticated policies: deny-all.
--
-- Additive and non-destructive. Idempotent (safe to re-run). FORCE ROW
-- LEVEL SECURITY is intentionally not used — the backend connects as the
-- table-owning postgres role and must keep working.
--
-- Prerequisite: migrations 001-027 applied.

-- 1. Enable RLS on all six tables (enabling an already-RLS table is a no-op).
ALTER TABLE student_college_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE support_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE support_tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE crawler_seeds ENABLE ROW LEVEL SECURITY;
ALTER TABLE catalog_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE scholarship_tracks ENABLE ROW LEVEL SECURITY;

-- 2. User-owned policies on student_college_budgets only.
--    The five operational tables intentionally get NO policies: with RLS
--    enabled and no policy, anon/authenticated are denied by default.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'student_college_budgets'
      AND policyname = 'student_college_budgets_select_own'
  ) THEN
    CREATE POLICY student_college_budgets_select_own
      ON student_college_budgets
      FOR SELECT
      TO authenticated
      USING (user_id = auth.uid());
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'student_college_budgets'
      AND policyname = 'student_college_budgets_insert_own'
  ) THEN
    CREATE POLICY student_college_budgets_insert_own
      ON student_college_budgets
      FOR INSERT
      TO authenticated
      WITH CHECK (user_id = auth.uid());
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'student_college_budgets'
      AND policyname = 'student_college_budgets_update_own'
  ) THEN
    CREATE POLICY student_college_budgets_update_own
      ON student_college_budgets
      FOR UPDATE
      TO authenticated
      USING (user_id = auth.uid())
      WITH CHECK (user_id = auth.uid());
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'student_college_budgets'
      AND policyname = 'student_college_budgets_delete_own'
  ) THEN
    CREATE POLICY student_college_budgets_delete_own
      ON student_college_budgets
      FOR DELETE
      TO authenticated
      USING (user_id = auth.uid());
  END IF;
END $$;

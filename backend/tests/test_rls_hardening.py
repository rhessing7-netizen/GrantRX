"""Regression coverage for migrations/028_rls_hardening.sql.

These tests parse the migration semantically (whitespace/case normalized,
line comments stripped) rather than snapshotting the file, so formatting
tweaks don't produce false failures while the security posture stays pinned.

Verifies:
  * 028 exists and is the latest migration in filename ordering
  * migrations 001-027 are all still present (not renamed/deleted)
  * RLS is enabled on exactly the six intended tables
  * student_college_budgets gets exactly the four user-owned CRUD policies
  * the five operational tables get no policies (default deny)
  * no destructive statements (DML, drops, grants, ownership, FORCE RLS)
"""

import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

RLS_TABLES = (
    "student_college_budgets",
    "support_conversations",
    "support_tickets",
    "crawler_seeds",
    "catalog_sources",
    "scholarship_tracks",
)

DENY_ALL_TABLES = tuple(t for t in RLS_TABLES if t != "student_college_budgets")

EXPECTED_PRIOR_MIGRATIONS = [
    "001_initial_schema",
    "002_stripe_and_feed_token",
    "003_add_user_identity_and_consent",
    "004_multi_select_disciplines_credentials",
    "005_add_metro_restrictions",
    "006_add_metro_area_to_profiles",
    "007_add_database_indexes",
    "008_add_is_dismissed_to_user_scholarships",
    "009_add_documents_and_checklist_to_user_scholarships",
    "010_add_financial_planner",
    "011_add_provider_alignment_and_local_fields",
    "012_add_scholarship_reports",
    "013_add_cancellation_feedback",
    "014_add_general_and_local_scholarship_fields",
    "015_add_employer_benefits_and_service_obligations",
    "016_create_crawler_seeds_queue",
    "017_create_support_tickets",
    "018_add_has_completed_tour",
    "019_allow_unknown_award_and_deadline",
    "020_add_scholarship_provenance",
    "021_crawler_seed_retry_lifecycle",
    "022_dismiss_only_tracking_rows",
    "023_catalog_lifecycle_foundation",
    "024_persisted_opportunity_identity",
    "025_source_registry",
    "026_general_taxonomy",
    "027_early_access_waitlist",
]


@pytest.fixture(scope="module")
def migration_028() -> str:
    """Normalized 028 SQL: comments stripped, whitespace collapsed, lowercase."""
    path = MIGRATIONS_DIR / "028_rls_hardening.sql"
    assert path.is_file(), "migrations/028_rls_hardening.sql not found"
    sql = path.read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", " ", sql)  # strip line comments
    sql = re.sub(r"\s+", " ", sql).strip().lower()
    return sql


def _policy_blocks(sql: str) -> list[str]:
    """Return the 'name on table for ...' portion of every CREATE POLICY."""
    return re.findall(
        r"create policy\s+([a-z_][a-z0-9_]*)\s+on\s+([a-z_][a-z0-9_]*)"
        r"(.*?)(?=create policy|end \$\$|;)\s*",
        sql,
    )


def test_028_exists_and_is_latest_in_ordering():
    files = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    assert files, "no migration files found"
    assert files[-1].startswith("028_"), (
        f"expected 028 to sort last, found {files[-1]!r}"
    )
    assert "028_rls_hardening.sql" in files


def test_migrations_001_through_027_still_present():
    """Prior migrations must not be renamed or deleted by this workstream."""
    files = {p.name for p in MIGRATIONS_DIR.glob("*.sql")}
    for name in EXPECTED_PRIOR_MIGRATIONS:
        assert f"{name}.sql" in files, f"{name}.sql missing or renamed"


def test_rls_enabled_on_all_six_tables(migration_028):
    for table in RLS_TABLES:
        assert f"alter table {table} enable row level security" in migration_028, (
            f"028 does not enable RLS on {table}"
        )


def test_student_college_budgets_policies(migration_028):
    policies = [
        (name, cmd, body)
        for name, table, body in _policy_blocks(migration_028)
        for cmd in re.findall(r"for\s+(select|insert|update|delete)", body)
        if table == "student_college_budgets"
    ]
    commands = sorted(cmd for _, cmd, _ in policies)
    assert commands == ["delete", "insert", "select", "update"], (
        f"budgets policies should cover exactly CRUD, got {commands}"
    )

    for name, cmd, body in policies:
        assert "to authenticated" in body, f"policy {name} not scoped to authenticated"
        assert "auth.uid()" in body, f"policy {name} missing auth.uid() ownership check"

    blocks = {
        name: body for name, table, body in _policy_blocks(migration_028)
        if table == "student_college_budgets"
    }
    # SELECT/UPDATE/DELETE filter rows; INSERT/UPDATE constrain written rows.
    for name, body in blocks.items():
        if "for update" in body:
            assert "using (user_id = auth.uid())" in body
            assert "with check (user_id = auth.uid())" in body
        elif "for insert" in body:
            assert "with check (user_id = auth.uid())" in body
        else:
            assert "using (user_id = auth.uid())" in body


@pytest.mark.parametrize("table", DENY_ALL_TABLES)
def test_operational_table_has_no_policy(migration_028, table):
    """The five operational tables must rely on default deny (no policies)."""
    for _, on_table, _ in _policy_blocks(migration_028):
        assert on_table != table, f"unexpected CREATE POLICY on {table}"


def test_policies_are_guarded_for_idempotency(migration_028):
    assert "pg_policies" in migration_028
    assert "if not exists" in migration_028


def test_no_destructive_or_privilege_statements(migration_028):
    for fragment in (
        "insert into",
        "delete from",
        "truncate",
        "drop table",
        "drop column",
        "alter column",
        "force row level security",
        " grant ",
        " revoke ",
        " owner to",
    ):
        assert fragment not in migration_028, f"forbidden statement: {fragment!r}"
    # UPDATE only allowed inside 'FOR UPDATE' policy clauses — never as DML.
    assert not re.search(r"\bupdate\s+[a-z_][a-z0-9_.]*\s+set\b", migration_028)

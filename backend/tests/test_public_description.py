"""Public scholarship description (migration 029) coverage.

The description is EdFintia's persisted consumer-facing narrative. These
tests prove:

- migration 029 is additive/idempotent and touches nothing else
- the field exists on the model and flows through extract → DB dict → API
- LLM extraction produces the field from supplied source context
- the deterministic grounding check drops narratives whose numeric claims
  cannot be found in the source text (never published ungrounded)
- a NULL extraction result never overwrites a stored description on refresh
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scrapers.extraction import attach_verification
from scrapers.llm_parser import (
    LLMScholarship,
    _sanitize_description,
    llm_item_to_extract,
)
from scrapers.runner import _to_db_dict
from scrapers.schema import ScholarshipExtract
from scrapers.verification import _description_grounded

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(scope="module")
def migration_029() -> str:
    path = MIGRATIONS_DIR / "029_public_description.sql"
    assert path.is_file(), "migrations/029_public_description.sql not found"
    sql = path.read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"\s+", " ", sql).strip().lower()


class TestMigration029:
    def test_file_exists_and_sorts_last(self):
        files = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
        assert files[-1] == "029_public_description.sql"

    def test_adds_column_to_scholarships(self, migration_029):
        assert (
            "alter table scholarships" in migration_029
            and "add column if not exists public_description" in migration_029
        )

    def test_additive_only_no_destructive_statements(self, migration_029):
        for fragment in (
            "drop ", "delete ", "truncate ", "update scholarships set",
            "create table", "essay", "workspace",
        ):
            assert fragment not in migration_029, f"forbidden: {fragment!r}"

    def test_idempotent(self, migration_029):
        assert "if not exists" in migration_029

    def test_model_column_present(self):
        from app.models.models import Scholarship

        assert "public_description" in Scholarship.__table__.columns


class TestExtractionContract:
    def test_llm_field_maps_to_extract(self):
        """The LLM contract carries the description through to the extract."""
        item = LLMScholarship(
            title="Rural Health Scholarship",
            provider="Health Foundation",
            public_description=(
                "The Rural Health Scholarship provides $5,000 to nursing "
                "students committed to underserved communities."
            ),
        )
        ex = llm_item_to_extract(item, "https://src.example/page")
        assert ex.public_description == item.public_description

    def test_null_description_stays_null(self):
        item = LLMScholarship(title="T", provider="P")
        ex = llm_item_to_extract(item, "https://src.example/page")
        assert ex.public_description is None

    def test_sanitizer_drops_urls_and_short_text(self):
        assert _sanitize_description("Apply now at https://x.example/apply today ok") is None
        assert _sanitize_description("too short") is None
        assert _sanitize_description(None) is None
        long_text = "A faithful summary of the opportunity from the page."
        assert _sanitize_description("  " + long_text + "  ") == long_text


class TestGrounding:
    SOURCE = (
        "The Rural Health Scholarship awards $5,000 annually to nursing "
        "students. Applications close May 1, 2030. A minimum 3.0 GPA is "
        "required. Recipients commit to 24 months of clinical service."
    )

    def _extract(self, desc=None):
        return ScholarshipExtract(
            title="Rural Health Scholarship",
            provider="Health Foundation",
            public_description=desc,
        )

    def test_grounded_description_kept(self):
        ex = self._extract(
            "This scholarship provides $5,000 to nursing students who "
            "commit to 24 months of clinical service."
        )
        out = attach_verification(ex, text=self.SOURCE, source_url="u")
        assert out.public_description is not None
        assert out.verified_fields["public_description"] == "verified"

    def test_invented_numbers_drop_description(self):
        """A narrative asserting facts absent from the source is destroyed
        before persistence — it can never be published."""
        ex = self._extract(
            "This scholarship provides $10,000 to nursing students."
        )
        out = attach_verification(ex, text=self.SOURCE, source_url="u")
        assert out.public_description is None
        assert out.verified_fields["public_description"] == "unverified"

    def test_ungrounded_description_does_not_bury_record(self):
        """Dropping bad prose must not flip an otherwise sound record into
        needs_review — the consequence is losing prose, not the record."""
        ex = self._extract(
            "This scholarship provides $10,000 to nursing students."
        )
        out = attach_verification(ex, text=self.SOURCE, source_url="u")
        # Title still verifies against source → record stays verified.
        assert out.verification_status == "verified"

    def test_absent_description_marks_not_asserted(self):
        ex = self._extract(None)
        out = attach_verification(ex, text=self.SOURCE, source_url="u")
        assert out.verified_fields["public_description"] == "not_asserted"

    def test_number_free_description_is_vacuously_grounded(self):
        assert _description_grounded(
            "A need-based award supporting rural nursing students.", self.SOURCE
        ) is True

    def test_empty_description_is_not_asserted(self):
        assert _description_grounded(None, self.SOURCE) is None
        assert _description_grounded("   ", self.SOURCE) is None


class TestPersistenceMapping:
    def test_to_db_dict_carries_description(self):
        ex = ScholarshipExtract(
            title="T", provider="P",
            public_description="A faithful grounded summary of the award.",
        )
        data = _to_db_dict(ex)
        assert data["public_description"] == ex.public_description

    def test_null_description_key_omitted_for_refresh(self):
        """On upsert the dict feeds a setattr loop — omitting the key when
        this extraction produced nothing preserves a previously stored
        description instead of destroying it with NULL."""
        ex = ScholarshipExtract(title="T", provider="P", public_description=None)
        assert "public_description" not in _to_db_dict(ex)


class TestApiContracts:
    def test_public_detail_schema_has_field(self):
        from app.schemas.schemas import PublicOpportunityOut

        assert "public_description" in PublicOpportunityOut.model_fields

    def test_authenticated_contracts_have_field(self):
        """One persisted description serves both surfaces — no separate
        public vs authenticated narrative."""
        from app.schemas.schemas import MatchedScholarshipOut, ScholarshipOut

        assert "public_description" in ScholarshipOut.model_fields
        assert "public_description" in MatchedScholarshipOut.model_fields

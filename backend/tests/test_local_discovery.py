"""Unit tests for Phase 8: Local Discovery Pipeline & Provider Alignment.

Tests verify:
- ScholarshipExtract schema includes provider alignment & local fields
- LLMScholarship schema includes the new fields with correct defaults
- _to_db_dict maps all new fields correctly from ScholarshipExtract
- Sources CATEGORIES set includes the 4 new local categories
- seeds.json contains the community foundation locator entry
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrapers.schema import ScholarshipExtract
from scrapers.llm_parser import LLMScholarship
from scrapers.sources import CATEGORIES


# ---------------------------------------------------------------------------
# Tests: ScholarshipExtract schema
# ---------------------------------------------------------------------------


class TestScholarshipExtractFields:
    def test_provider_type_default_none(self):
        extract = ScholarshipExtract(title="Test Scholarship")
        assert extract.provider_type is None

    def test_provider_mission_default_none(self):
        extract = ScholarshipExtract(title="Test Scholarship")
        assert extract.provider_mission is None

    def test_provider_core_values_default_empty(self):
        extract = ScholarshipExtract(title="Test Scholarship")
        assert extract.provider_core_values == []

    def test_is_local_default_false(self):
        extract = ScholarshipExtract(title="Test Scholarship")
        assert extract.is_local is False

    def test_target_community_default_none(self):
        extract = ScholarshipExtract(title="Test Scholarship")
        assert extract.target_community is None

    def test_all_new_fields_settable(self):
        extract = ScholarshipExtract(
            title="Cleveland Foundation Award",
            provider_type="community_foundation",
            provider_mission="Supporting Northeast Ohio students",
            provider_core_values=["equity", "service", "compassion"],
            is_local=True,
            target_community="Cleveland, OH",
        )
        assert extract.provider_type == "community_foundation"
        assert extract.provider_mission == "Supporting Northeast Ohio students"
        assert extract.provider_core_values == ["equity", "service", "compassion"]
        assert extract.is_local is True
        assert extract.target_community == "Cleveland, OH"


# ---------------------------------------------------------------------------
# Tests: LLMScholarship schema
# ---------------------------------------------------------------------------


class TestLLMScholarshipFields:
    def test_provider_type_field_exists(self):
        fields = LLMScholarship.model_fields
        assert "provider_type" in fields

    def test_provider_mission_field_exists(self):
        fields = LLMScholarship.model_fields
        assert "provider_mission" in fields

    def test_provider_core_values_field_exists(self):
        fields = LLMScholarship.model_fields
        assert "provider_core_values" in fields

    def test_is_local_field_exists(self):
        fields = LLMScholarship.model_fields
        assert "is_local" in fields

    def test_target_community_field_exists(self):
        fields = LLMScholarship.model_fields
        assert "target_community" in fields

    def test_is_local_defaults_false(self):
        # Create with minimal required fields
        obj = LLMScholarship(
            title="Test",
            provider="Provider",
            award_amount=1000,
            deadline="2026-03-15",
        )
        assert obj.is_local is False

    def test_provider_core_values_defaults_empty(self):
        obj = LLMScholarship(
            title="Test",
            provider="Provider",
            award_amount=1000,
            deadline="2026-03-15",
        )
        assert obj.provider_core_values == []


# ---------------------------------------------------------------------------
# Tests: Sources CATEGORIES
# ---------------------------------------------------------------------------


class TestSourceCategories:
    def test_chamber_of_commerce_in_categories(self):
        assert "chamber_of_commerce" in CATEGORIES

    def test_faith_based_community_in_categories(self):
        assert "faith_based_community" in CATEGORIES

    def test_local_business_in_categories(self):
        assert "local_business" in CATEGORIES

    def test_institutional_department_in_categories(self):
        assert "institutional_department" in CATEGORIES

    def test_existing_categories_preserved(self):
        assert "national_association" in CATEGORIES
        assert "regional_foundation" in CATEGORIES
        assert "state_agency" in CATEGORIES


# ---------------------------------------------------------------------------
# Tests: seeds.json
# ---------------------------------------------------------------------------


class TestSeedsJson:
    def _seeds_path(self) -> Path:
        return Path(__file__).parent.parent / "scrapers" / "seeds.json"

    def test_community_foundation_locator_present(self):
        seeds = json.loads(self._seeds_path().read_text(encoding="utf-8"))
        urls = [s["url"] for s in seeds]
        assert "https://cof.org/page/community-foundation-locator" in urls

    def test_community_foundation_locator_category(self):
        seeds = json.loads(self._seeds_path().read_text(encoding="utf-8"))
        entry = next(
            (s for s in seeds if "cof.org" in s.get("url", "")),
            None,
        )
        assert entry is not None
        assert entry["category"] == "regional_foundation"

    def test_community_foundation_locator_scraper_type(self):
        seeds = json.loads(self._seeds_path().read_text(encoding="utf-8"))
        entry = next(
            (s for s in seeds if "cof.org" in s.get("url", "")),
            None,
        )
        assert entry is not None
        assert entry.get("scraper_type") == "playwright"


# ---------------------------------------------------------------------------
# Tests: _to_db_dict mapping (runner)
# ---------------------------------------------------------------------------


class TestRunnerDbDictMapping:
    def test_to_db_dict_includes_provider_fields(self):
        from scrapers.runner import _to_db_dict

        extract = ScholarshipExtract(
            title="Test Award",
            provider="Cleveland Foundation",
            portal_url="https://example.com",
            award_amount=5000,
            deadline="2026-03-15",
            provider_type="community_foundation",
            provider_mission="Supporting local students",
            provider_core_values=["equity", "service"],
            is_local=True,
            target_community="Cleveland, OH",
        )
        data = _to_db_dict(extract)
        assert data["provider_type"] == "community_foundation"
        assert data["provider_mission"] == "Supporting local students"
        assert data["provider_core_values"] == ["equity", "service"]
        assert data["is_local"] is True
        assert data["target_community"] == "Cleveland, OH"

    def test_to_db_dict_defaults_for_missing_provider_fields(self):
        from scrapers.runner import _to_db_dict

        extract = ScholarshipExtract(
            title="National Award",
            provider="National Org",
            portal_url="https://example.com",
            award_amount=10000,
            deadline="2026-06-01",
        )
        data = _to_db_dict(extract)
        assert data["provider_type"] is None
        assert data["provider_mission"] is None
        assert data["provider_core_values"] == []
        assert data["is_local"] is False
        assert data["target_community"] is None

"""Unit tests for the scholarship matching algorithm.

Tests cover:
  - 100% match scoring (all criteria met)
  - Partial match scoring (some criteria met)
  - Empty criteria edge cases (no disciplines, no GPA, no restrictions)
  - Discipline normalization for undergraduate science majors
  - Metro matching precedence over state matching
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List
from unittest.mock import MagicMock

import pytest

from app.services.matcher import (
    MatchResult,
    _metro_match,
    _normalize_metro_value,
    match_scholarships,
    score_scholarship,
)


# ---------------------------------------------------------------------------
# Test fixtures — lightweight mock objects that quack like Profile/Scholarship
# ---------------------------------------------------------------------------

def _make_profile(**kwargs):
    """Create a mock Profile with sensible defaults."""
    defaults = {
        "id": "00000000-0000-0000-0000-000000000001",
        "disciplines": [],
        "target_credentials": [],
        "primary_discipline": None,
        "target_credential": None,
        "clinical_phase": None,
        "gpa": None,
        "state_residence": None,
        "metro_area": None,
        "sai_score": None,
        "first_gen": False,
        "minority_flag": False,
        "professional_affiliations": [],
        "hobbies": [],
        "subscription_tier": "free",
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_scholarship(**kwargs):
    """Create a mock Scholarship with sensible defaults."""
    defaults = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Test Scholarship",
        "provider": "Test Provider",
        "portal_url": "https://example.com/apply",
        "award_amount": 5000,
        "deadline": date.today() + timedelta(days=90),
        "eligible_disciplines": [],
        "eligible_credentials": [],
        "min_gpa": 0.0,
        "max_sai": None,
        "state_restrictions": [],
        "metro_restrictions": [],
        "required_affiliations": [],
        "matching_tags": [],
        "is_archived": False,
        "estimated_next_cycle": None,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# Tests: score_scholarship
# ---------------------------------------------------------------------------

class TestScoreScholarship:
    def test_perfect_match_all_criteria_met(self):
        """A scholarship where the user meets every criterion should score high."""
        profile = _make_profile(
            disciplines=["pharmacy"],
            primary_discipline="pharmacy",
            gpa=3.9,
            state_residence="CA",
            first_gen=True,
            minority_flag=True,
        )
        scholarship = _make_scholarship(
            eligible_disciplines=["pharmacy"],
            min_gpa=3.0,
            state_restrictions=["CA"],
        )
        score, missing = score_scholarship(profile, scholarship)
        assert score >= 80, f"Expected score >= 80 for perfect match, got {score}"
        assert len(missing) == 0, f"Expected no missing criteria, got {missing}"

    def test_partial_match_some_criteria_met(self):
        """A scholarship where the user meets some criteria should score moderately."""
        profile = _make_profile(
            disciplines=["nursing"],
            primary_discipline="nursing",
            gpa=3.5,
            state_residence="NY",
        )
        scholarship = _make_scholarship(
            eligible_disciplines=["nursing"],
            min_gpa=3.0,
            state_restrictions=["CA"],  # User is in NY, not CA
        )
        score, missing = score_scholarship(profile, scholarship)
        assert 40 <= score < 100, f"Expected moderate score, got {score}"
        # State restriction should be in missing criteria
        assert any("state" in m.lower() or "CA" in m or "residence" in m.lower() for m in missing)

    def test_empty_criteria_unrestricted_scholarship(self):
        """A scholarship with no restrictions should still score (unrestricted)."""
        profile = _make_profile(
            disciplines=["pharmacy"],
            gpa=3.5,
        )
        scholarship = _make_scholarship(
            eligible_disciplines=[],  # Any discipline
            min_gpa=0.0,
            state_restrictions=[],  # Any state
        )
        score, missing = score_scholarship(profile, scholarship)
        assert score >= 0, f"Score should be non-negative, got {score}"
        assert "discipline" not in " ".join(missing).lower()

    def test_empty_profile_unrestricted_match(self):
        """A profile with no disciplines should match unrestricted scholarships."""
        profile = _make_profile()  # All defaults = empty
        scholarship = _make_scholarship(
            eligible_disciplines=[],
            min_gpa=0.0,
        )
        score, missing = score_scholarship(profile, scholarship)
        assert score >= 0, f"Score should be non-negative, got {score}"

    def test_gpa_below_minimum(self):
        """A user with GPA below the minimum should have it in missing criteria."""
        profile = _make_profile(gpa=2.5)
        scholarship = _make_scholarship(min_gpa=3.5)
        score, missing = score_scholarship(profile, scholarship)
        assert any("gpa" in m.lower() for m in missing), f"Expected GPA in missing, got {missing}"


# ---------------------------------------------------------------------------
# Tests: match_scholarships (full pipeline)
# ---------------------------------------------------------------------------

class TestMatchScholarships:
    def test_archived_scholarships_excluded(self):
        """Archived scholarships should not appear in results."""
        profile = _make_profile(disciplines=["pharmacy"])
        active = _make_scholarship(title="Active", eligible_disciplines=["pharmacy"])
        archived = _make_scholarship(
            title="Archived",
            eligible_disciplines=["pharmacy"],
            is_archived=True,
        )
        results = match_scholarships(profile, [active, archived])
        titles = [r.title for r in results]
        assert "Active" in titles
        assert "Archived" not in titles

    def test_results_sorted_by_score_descending(self):
        """Results should be sorted by score descending."""
        profile = _make_profile(
            disciplines=["pharmacy"],
            gpa=3.9,
            state_residence="CA",
        )
        high_score = _make_scholarship(
            title="High Match",
            eligible_disciplines=["pharmacy"],
            min_gpa=3.0,
            state_restrictions=["CA"],
        )
        low_score = _make_scholarship(
            title="Low Match",
            eligible_disciplines=["pharmacy"],
            min_gpa=3.0,
            state_restrictions=["NY"],  # Different state
        )
        results = match_scholarships(profile, [low_score, high_score])
        assert len(results) == 2
        assert results[0].score >= results[1].score
        assert results[0].title == "High Match"

    def test_empty_scholarship_list(self):
        """An empty scholarship list should return empty results."""
        profile = _make_profile()
        results = match_scholarships(profile, [])
        assert results == []

    def test_discipline_normalization_for_science_majors(self):
        """User majors like 'Geology' should match scholarships with 'medicine'."""
        from scrapers.sources import normalize_discipline
        assert normalize_discipline("Geology") == "medicine"
        assert normalize_discipline("Exercise Science") == "therapeutics_rehab"
        assert normalize_discipline("Public Health") == "public_health_emergency"

    def test_award_amount_defaults_to_zero(self):
        """Scholarships with None award_amount should default to 0 in results."""
        profile = _make_profile()
        scholarship = _make_scholarship(award_amount=None)
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 1
        assert results[0].award_amount == 0

    def test_deadline_iso_format(self):
        """Deadline should be returned as an ISO format string."""
        profile = _make_profile()
        test_date = date(2025, 12, 15)
        scholarship = _make_scholarship(deadline=test_date)
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 1
        assert results[0].deadline == "2025-12-15"


# ---------------------------------------------------------------------------
# Tests: Metro matching
# ---------------------------------------------------------------------------

class TestMetroMatching:
    def test_normalize_metro_handles_msa_names(self):
        """MSA names should be normalized for comparison."""
        result = _normalize_metro_value("Philadelphia-Camden-Wilmington")
        assert result is not None
        assert "philadelphia" in result.lower()

    def test_normalize_metro_handles_none(self):
        """None metro should return empty string."""
        result = _normalize_metro_value(None)
        assert result == ""

    def test_metro_match_profile_with_metro_matches_scholarship(self):
        """A profile with a metro_area should match a scholarship with the same metro restriction."""
        profile = _make_profile(metro_area="Philadelphia-Camden-Wilmington")
        scholarship = _make_scholarship(metro_restrictions=["Philadelphia-Camden-Wilmington"])
        assert _metro_match(profile, scholarship) is True

    def test_metro_match_scholarship_no_restrictions(self):
        """A scholarship with no metro restrictions should match any user metro."""
        profile = _make_profile(metro_area="Philadelphia-Camden-Wilmington")
        scholarship = _make_scholarship(metro_restrictions=[])
        assert _metro_match(profile, scholarship) is True

    def test_metro_match_different_metro(self):
        """A profile with a different metro should not match a metro-restricted scholarship."""
        profile = _make_profile(metro_area="Philadelphia-Camden-Wilmington")
        scholarship = _make_scholarship(metro_restrictions=["New York-Newark-Jersey City"])
        assert _metro_match(profile, scholarship) is False

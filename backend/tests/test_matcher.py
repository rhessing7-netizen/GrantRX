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
    is_discipline_eligible,
    match_scholarships,
    score_breakdown,
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
        "is_general_major": False,
        "academic_levels": [],
        "scope": "national",
        "county_restrictions": [],
        "city_restrictions": [],
        "is_local": False,
        "competition_level": "medium",
        "target_community": None,
        # Employer / service-obligation defaults
        "funding_type": "scholarship",
        "employment_required": False,
        "min_employment_tenure_months": None,
        "annual_benefit_cap": None,
        "benefit_coverage_model": None,
        "partner_network": None,
        "has_service_commitment": False,
        "service_commitment_duration_months": None,
        "vendor_platform": None,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# Tests: score_breakdown
# ---------------------------------------------------------------------------

class TestScoreBreakdown:
    def test_breakdown_sums_to_score(self):
        """Per-bucket breakdown must always reconcile with the headline score."""
        profile = _make_profile(gpa=3.5, state_residence="NY", first_gen=True)
        scholarship = _make_scholarship(
            min_gpa=3.0, state_restrictions=["CA"], matching_tags=["first_gen"],
        )
        score, _ = score_scholarship(profile, scholarship)
        breakdown = score_breakdown(profile, scholarship)
        assert min(100, sum(breakdown.values())) == score
        assert set(breakdown) == {"gpa", "geo", "sai", "affiliations", "local_boost"}
        assert breakdown["gpa"] == 25
        assert breakdown["geo"] == 0  # NY student, CA-only award
        assert breakdown["sai"] == 25  # no max_sai restriction
        assert breakdown["affiliations"] == 25

    def test_local_boost_only_with_geo_match(self):
        """The +10 local boost requires competition_level='low' AND geo match."""
        profile = _make_profile(state_residence="OH")
        matched = _make_scholarship(state_restrictions=["OH"], competition_level="low")
        unmatched = _make_scholarship(state_restrictions=["PA"], competition_level="low")
        assert score_breakdown(profile, matched)["local_boost"] == 10
        assert score_breakdown(profile, unmatched)["local_boost"] == 0

    def test_match_results_carry_breakdown(self):
        """match_scholarships() attaches the breakdown to every MatchResult."""
        profile = _make_profile(disciplines=["pharmacy"], gpa=3.9)
        scholarship = _make_scholarship(eligible_disciplines=["pharmacy"], min_gpa=3.0)
        [result] = match_scholarships(profile, [scholarship])
        assert result.score_breakdown["gpa"] == 25
        assert min(100, sum(result.score_breakdown.values())) == result.score


# ---------------------------------------------------------------------------
# Tests: score_scholarship
# ---------------------------------------------------------------------------

class TestScoreScholarship:
    def test_perfect_match_all_criteria_met(self):
        """A scholarship where the user meets every criterion should score 100."""
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
            matching_tags=["first_gen", "minority"],
        )
        score, missing = score_scholarship(profile, scholarship)
        assert score == 100, f"Expected score 100 for perfect match, got {score}"
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
        # GPA(25) + geo(0) + SAI(25) + affil(0) = 50
        assert 25 <= score < 100, f"Expected moderate score, got {score}"
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
# Tests: is_discipline_eligible (hard gate)
# ---------------------------------------------------------------------------

class TestIsDisciplineEligible:
    def test_empty_disciplines_passes_all(self):
        """Scholarships with empty eligible_disciplines pass everyone."""
        profile = _make_profile(disciplines=["pharmacy"])
        scholarship = _make_scholarship(eligible_disciplines=[])
        assert is_discipline_eligible(profile, scholarship) is True

    def test_any_in_disciplines_passes_all(self):
        """Scholarships with 'any' in eligible_disciplines pass everyone."""
        profile = _make_profile(disciplines=["pharmacy"])
        scholarship = _make_scholarship(eligible_disciplines=["any"])
        assert is_discipline_eligible(profile, scholarship) is True

    def test_matching_discipline_passes(self):
        """User discipline matching scholarship discipline passes."""
        profile = _make_profile(disciplines=["pharmacy"])
        scholarship = _make_scholarship(eligible_disciplines=["pharmacy"])
        assert is_discipline_eligible(profile, scholarship) is True

    def test_non_matching_discipline_fails(self):
        """User discipline not matching scholarship discipline fails hard."""
        profile = _make_profile(disciplines=["nursing"])
        scholarship = _make_scholarship(eligible_disciplines=["pharmacy"])
        assert is_discipline_eligible(profile, scholarship) is False

    def test_no_user_disciplines_passes(self):
        """User with no disciplines passes (unrestricted fallback)."""
        profile = _make_profile(disciplines=[])
        scholarship = _make_scholarship(eligible_disciplines=["pharmacy"])
        assert is_discipline_eligible(profile, scholarship) is True

    def test_matching_credential_passes(self):
        """User credential matching scholarship credential passes."""
        profile = _make_profile(target_credentials=["PharmD"])
        scholarship = _make_scholarship(eligible_credentials=["PharmD"])
        assert is_discipline_eligible(profile, scholarship) is True

    def test_non_matching_credential_fails(self):
        """User credential not matching scholarship credential fails hard."""
        profile = _make_profile(target_credentials=["BSN"])
        scholarship = _make_scholarship(eligible_credentials=["PharmD"])
        assert is_discipline_eligible(profile, scholarship) is False

    def test_no_user_credentials_passes(self):
        """User with no credentials passes credential gate."""
        profile = _make_profile(target_credentials=[])
        scholarship = _make_scholarship(eligible_credentials=["PharmD"])
        assert is_discipline_eligible(profile, scholarship) is True

    def test_empty_scholarship_credentials_passes(self):
        """Scholarship with no credential restriction passes everyone."""
        profile = _make_profile(target_credentials=["PharmD"])
        scholarship = _make_scholarship(eligible_credentials=[])
        assert is_discipline_eligible(profile, scholarship) is True

    def test_discipline_match_credential_mismatch_fails(self):
        """Discipline matches but credential doesn't -> fails hard."""
        profile = _make_profile(disciplines=["pharmacy"], target_credentials=["BSN"])
        scholarship = _make_scholarship(
            eligible_disciplines=["pharmacy"],
            eligible_credentials=["PharmD"],
        )
        assert is_discipline_eligible(profile, scholarship) is False


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

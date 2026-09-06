"""Unit tests for general-major and local low-competition scholarship matching.

Tests cover:
  - General major scholarships match profiles regardless of discipline.
  - High school, undergraduate, and graduate levels are categorized properly.
  - Low-competition / county-restricted awards get the local relevance boost.
  - Low-competition awards that don't match the student's geography are filtered
    or scored lower, with missing_criteria populated.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from app.services.matcher import (
    _academic_level_match,
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
        "county_restrictions": [],
        "city_restrictions": [],
        "required_affiliations": [],
        "matching_tags": [],
        "is_archived": False,
        "estimated_next_cycle": None,
        "is_general_major": False,
        "academic_levels": [],
        "scope": "national",
        "is_local": False,
        "competition_level": "medium",
        "target_community": None,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# Tests: General major scholarships
# ---------------------------------------------------------------------------

class TestGeneralMajorMatching:
    """General-major scholarships should match all students regardless of discipline."""

    def test_general_major_matches_pharmacy_student(self):
        """A scholarship with is_general_major=True matches a pharmacy student."""
        profile = _make_profile(disciplines=["pharmacy"], primary_discipline="pharmacy")
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
            state_restrictions=[],
        )
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 1, "General major scholarship should match pharmacy student"

    def test_general_major_matches_nursing_student(self):
        """A scholarship with is_general_major=True matches a nursing student."""
        profile = _make_profile(disciplines=["nursing"], primary_discipline="nursing")
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
        )
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 1, "General major scholarship should match nursing student"

    def test_general_major_matches_medicine_student(self):
        """A scholarship with is_general_major=True matches a medicine student."""
        profile = _make_profile(disciplines=["medicine"], primary_discipline="medicine")
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
        )
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 1, "General major scholarship should match medicine student"

    def test_general_major_matches_student_with_no_disciplines(self):
        """A general-major scholarship matches even when the student has no disciplines."""
        profile = _make_profile(disciplines=[])
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
        )
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 1

    def test_any_in_disciplines_matches_all(self):
        """Scholarships with 'any' in eligible_disciplines match all students."""
        profile = _make_profile(disciplines=["pharmacy"])
        scholarship = _make_scholarship(
            is_general_major=False,
            eligible_disciplines=["any"],
        )
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 1

    def test_empty_disciplines_matches_all(self):
        """Scholarships with empty eligible_disciplines match all students (legacy behavior)."""
        profile = _make_profile(disciplines=["pharmacy"])
        scholarship = _make_scholarship(
            is_general_major=False,
            eligible_disciplines=[],
        )
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 1

    def test_specific_discipline_filters_non_matching(self):
        """A pharmacy-only scholarship should NOT match a nursing-only student."""
        profile = _make_profile(disciplines=["nursing"], primary_discipline="nursing")
        scholarship = _make_scholarship(
            is_general_major=False,
            eligible_disciplines=["pharmacy"],
        )
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 0, "Pharmacy-only scholarship should not match nursing student"


# ---------------------------------------------------------------------------
# Tests: Academic level categorization
# ---------------------------------------------------------------------------

class TestAcademicLevelMatching:
    """Academic level filtering should correctly categorize HS, undergrad, and grad."""

    def test_high_school_senior_matches_hs_scholarship(self):
        """A high school senior profile matches a high_school_senior scholarship."""
        profile = _make_profile(clinical_phase="High School Senior")
        scholarship = _make_scholarship(academic_levels=["high_school_senior"])
        assert _academic_level_match(profile, scholarship) is True

    def test_undergraduate_matches_undergrad_scholarship(self):
        """An undergraduate profile matches an undergraduate scholarship."""
        profile = _make_profile(clinical_phase="Undergraduate")
        scholarship = _make_scholarship(academic_levels=["undergraduate"])
        assert _academic_level_match(profile, scholarship) is True

    def test_graduate_matches_graduate_scholarship(self):
        """A graduate profile matches a graduate scholarship."""
        profile = _make_profile(clinical_phase="Graduate")
        scholarship = _make_scholarship(academic_levels=["graduate"])
        assert _academic_level_match(profile, scholarship) is True

    def test_doctoral_matches_doctoral_scholarship(self):
        """A doctoral profile matches a doctoral scholarship."""
        profile = _make_profile(clinical_phase="Doctoral")
        scholarship = _make_scholarship(academic_levels=["doctoral"])
        assert _academic_level_match(profile, scholarship) is True

    def test_high_school_does_not_match_graduate_only(self):
        """A high school senior should NOT match a graduate-only scholarship."""
        profile = _make_profile(clinical_phase="High School Senior")
        scholarship = _make_scholarship(academic_levels=["graduate", "doctoral"])
        assert _academic_level_match(profile, scholarship) is False

    def test_empty_academic_levels_passes_all(self):
        """Scholarships with no academic_levels restriction pass all students."""
        profile = _make_profile(clinical_phase="Undergraduate")
        scholarship = _make_scholarship(academic_levels=[])
        assert _academic_level_match(profile, scholarship) is True

    def test_no_clinical_phase_passes_all(self):
        """A student with no clinical_phase on file passes the academic level filter."""
        profile = _make_profile(clinical_phase=None)
        scholarship = _make_scholarship(academic_levels=["graduate"])
        assert _academic_level_match(profile, scholarship) is True

    def test_academic_level_filters_in_match_pipeline(self):
        """The match pipeline should filter out non-matching academic levels."""
        profile = _make_profile(
            disciplines=["pharmacy"],
            clinical_phase="Undergraduate",
        )
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
            academic_levels=["graduate", "doctoral"],
        )
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 0, "Undergraduate should not match graduate-only scholarship"


# ---------------------------------------------------------------------------
# Tests: Low-competition / local relevance boost
# ---------------------------------------------------------------------------

class TestLowCompetitionBoost:
    """Low-competition awards should get a +10% boost when geo matches."""

    def test_low_competition_geo_match_gets_boost(self):
        """A low-competition, state-restricted award gets +10 when state matches."""
        profile = _make_profile(
            disciplines=["pharmacy"],
            state_residence="OH",
            gpa=3.5,
        )
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
            state_restrictions=["OH"],
            competition_level="low",
            is_local=True,
        )
        score, missing = score_scholarship(profile, scholarship)
        # Base: credential(25) + gpa(20) + sai(20) + geo(15) + affiliations(0) = 80
        # + local boost(10) = 90
        assert score >= 90, f"Expected score >= 90 with local boost, got {score}"

    def test_low_competition_no_geo_match_no_boost(self):
        """A low-competition award without geo match does NOT get the boost."""
        profile = _make_profile(
            disciplines=["pharmacy"],
            state_residence="CA",
            gpa=3.5,
        )
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
            state_restrictions=["OH"],
            competition_level="low",
            is_local=True,
        )
        score, missing = score_scholarship(profile, scholarship)
        # Base: credential(25) + gpa(20) + sai(20) + geo(0) + affiliations(0) = 65
        # No local boost because geo doesn't match
        assert score < 90, f"Expected score < 90 without geo match, got {score}"
        # Should have missing criteria about state restriction
        assert any("OH" in m for m in missing), f"Expected OH restriction in missing, got {missing}"

    def test_medium_competition_no_boost_even_with_geo_match(self):
        """A medium-competition award does NOT get the local boost."""
        profile = _make_profile(
            disciplines=["pharmacy"],
            state_residence="OH",
            gpa=3.5,
        )
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
            state_restrictions=["OH"],
            competition_level="medium",
        )
        score, missing = score_scholarship(profile, scholarship)
        # Base: credential(25) + gpa(20) + sai(20) + geo(15) = 80
        # No local boost because competition_level is medium
        assert score == 80, f"Expected score 80 for medium competition, got {score}"

    def test_high_competition_national_no_boost(self):
        """A high-competition national award does NOT get the local boost."""
        profile = _make_profile(
            disciplines=["pharmacy"],
            state_residence="OH",
            gpa=3.5,
        )
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
            state_restrictions=[],
            competition_level="high",
        )
        score, missing = score_scholarship(profile, scholarship)
        # Base: credential(25) + gpa(20) + sai(20) + geo(15) = 80
        assert score == 80, f"Expected score 80 for high competition, got {score}"

    def test_county_restricted_low_competition_in_feed(self):
        """A county-restricted low-competition award appears in the feed for
        matching-state students and populates missing_criteria tags when
        locations don't match."""
        profile_in_state = _make_profile(
            disciplines=["pharmacy"],
            state_residence="OH",
            gpa=3.5,
        )
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
            state_restrictions=["OH"],
            county_restrictions=["Wayne County"],
            competition_level="low",
            is_local=True,
            scope="county",
        )
        results = match_scholarships(profile_in_state, [scholarship])
        assert len(results) == 1, "OH student should see OH-restricted scholarship"
        assert results[0].score >= 90, f"Expected boosted score, got {results[0].score}"

    def test_county_restricted_does_not_match_out_of_state(self):
        """A county-restricted low-competition award should not match an
        out-of-state student (state restriction gate)."""
        profile_out = _make_profile(
            disciplines=["pharmacy"],
            state_residence="CA",
            gpa=3.5,
        )
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
            state_restrictions=["OH"],
            county_restrictions=["Wayne County"],
            competition_level="low",
            is_local=True,
        )
        score, missing = score_scholarship(profile_out, scholarship)
        # Should have missing criteria about state restriction
        assert any("OH" in m for m in missing), f"Expected OH in missing criteria, got {missing}"
        assert score < 90, f"Out-of-state student should not get local boost, got {score}"


# ---------------------------------------------------------------------------
# Tests: Pipeline integration
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    """End-to-end match_scholarships pipeline tests with new fields."""

    def test_general_major_with_academic_level_filter(self):
        """A general-major scholarship with academic level filtering works."""
        profile = _make_profile(
            disciplines=["nursing"],
            clinical_phase="Undergraduate",
            state_residence="OH",
            gpa=3.5,
        )
        scholarship = _make_scholarship(
            is_general_major=True,
            eligible_disciplines=["any"],
            academic_levels=["undergraduate", "graduate"],
            state_restrictions=["OH"],
            competition_level="low",
        )
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 1
        assert results[0].score >= 90

    def test_mixed_feed_general_and_specific(self):
        """A feed with both general and specific scholarships filters correctly."""
        profile = _make_profile(
            disciplines=["pharmacy"],
            clinical_phase="Undergraduate",
            state_residence="OH",
        )
        general_sch = _make_scholarship(
            title="General Community Award",
            is_general_major=True,
            eligible_disciplines=["any"],
            state_restrictions=["OH"],
            competition_level="low",
        )
        specific_sch = _make_scholarship(
            title="Pharmacy Excellence Award",
            is_general_major=False,
            eligible_disciplines=["pharmacy"],
            state_restrictions=["OH"],
            competition_level="medium",
        )
        nursing_only = _make_scholarship(
            title="Nursing Leadership Award",
            is_general_major=False,
            eligible_disciplines=["nursing"],
        )
        results = match_scholarships(profile, [general_sch, specific_sch, nursing_only])
        titles = [r.title for r in results]
        assert "General Community Award" in titles
        assert "Pharmacy Excellence Award" in titles
        assert "Nursing Leadership Award" not in titles

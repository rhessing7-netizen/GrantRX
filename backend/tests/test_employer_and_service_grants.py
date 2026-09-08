"""Unit tests for employer tuition assistance, service-obligation grants,
and AcademicWorks / .edu outside scholarship portal support.

Covers:
  - Pydantic schema serialization with populated and default values.
  - SQLAlchemy model attribute defaults.
  - Runner `_to_db_dict()` mapping for the new fields.
  - Matcher informational notices for service commitments and employment
    requirements (without penalizing the matching score).
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from app.schemas.schemas import MatchedScholarshipOut, ScholarshipBase, ScholarshipOut
from app.services.matcher import MatchResult, match_scholarships, score_scholarship
from scrapers.schema import ScholarshipExtract


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_profile(**kwargs):
    defaults = {
        "id": "00000000-0000-0000-0000-000000000001",
        "disciplines": ["pharmacy"],
        "target_credentials": ["PharmD"],
        "primary_discipline": "pharmacy",
        "target_credential": "PharmD",
        "clinical_phase": "graduate",
        "gpa": 3.5,
        "state_residence": "OH",
        "metro_area": None,
        "sai_score": -1500,
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
    defaults = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Cleveland Clinic Tuition Assistance",
        "provider": "Cleveland Clinic",
        "portal_url": "https://example.com/apply",
        "award_amount": 5250,
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
        "is_general_major": True,
        "academic_levels": [],
        "scope": "national",
        "county_restrictions": [],
        "city_restrictions": [],
        "is_local": False,
        "competition_level": "medium",
        "target_community": None,
        # New employer / service-obligation fields
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
# Schema serialization
# ---------------------------------------------------------------------------


class TestSchemaSerialization:
    def test_scholarship_base_defaults(self):
        """ScholarshipBase should populate new fields with safe defaults."""
        s = ScholarshipBase(
            title="Test",
            provider="Test Provider",
            portal_url="https://example.com",
            award_amount=1000,
            deadline=date.today() + timedelta(days=30),
        )
        assert s.funding_type == "scholarship"
        assert s.employment_required is False
        assert s.min_employment_tenure_months is None
        assert s.annual_benefit_cap is None
        assert s.benefit_coverage_model is None
        assert s.partner_network is None
        assert s.has_service_commitment is False
        assert s.service_commitment_duration_months is None
        assert s.vendor_platform is None

    def test_scholarship_base_with_populated_values(self):
        """ScholarshipBase should accept populated employer-benefit values."""
        s = ScholarshipBase(
            title="Cleveland Clinic ASPIRE",
            provider="Cleveland Clinic",
            portal_url="https://example.com/aspire",
            award_amount=5250,
            deadline=date.today() + timedelta(days=30),
            funding_type="tuition_reimbursement",
            employment_required=True,
            min_employment_tenure_months=6,
            annual_benefit_cap=5250,
            benefit_coverage_model="reimbursement",
            partner_network="internal",
            has_service_commitment=False,
            vendor_platform="academicworks",
        )
        assert s.funding_type == "tuition_reimbursement"
        assert s.employment_required is True
        assert s.min_employment_tenure_months == 6
        assert s.annual_benefit_cap == 5250
        assert s.benefit_coverage_model == "reimbursement"
        assert s.partner_network == "internal"
        assert s.vendor_platform == "academicworks"

    def test_matched_scholarship_out_defaults(self):
        """MatchedScholarshipOut should serialize a MatchResult with defaults."""
        result = MatchResult(
            scholarship_id="11111111-1111-1111-1111-111111111111",
            title="Test",
            provider="Test Provider",
            portal_url="https://example.com",
            award_amount=1000,
            deadline="2026-12-31",
            score=75,
        )
        out = MatchedScholarshipOut(**result.__dict__)
        assert out.funding_type == "scholarship"
        assert out.employment_required is False
        assert out.has_service_commitment is False
        assert out.annual_benefit_cap is None
        assert out.vendor_platform is None

    def test_matched_scholarship_out_with_employer_fields(self):
        """MatchedScholarshipOut should serialize employer-benefit fields."""
        result = MatchResult(
            scholarship_id="11111111-1111-1111-1111-111111111111",
            title="Kaiser Permanente Pipeline",
            provider="Kaiser Permanente",
            portal_url="https://example.com/kaiser",
            award_amount=10000,
            deadline="2026-12-31",
            score=100,
            funding_type="employer_sponsorship",
            employment_required=True,
            has_service_commitment=True,
            annual_benefit_cap=10000,
            vendor_platform="kaleidoscope",
        )
        out = MatchedScholarshipOut(**result.__dict__)
        assert out.funding_type == "employer_sponsorship"
        assert out.employment_required is True
        assert out.has_service_commitment is True
        assert out.annual_benefit_cap == 10000
        assert out.vendor_platform == "kaleidoscope"


# ---------------------------------------------------------------------------
# Runner _to_db_dict mapping
# ---------------------------------------------------------------------------


class TestRunnerDbDict:
    def test_to_db_dict_includes_employer_defaults(self):
        """_to_db_dict should map new fields with safe defaults."""
        from scrapers.runner import _to_db_dict

        extract = ScholarshipExtract(
            title="Test Scholarship",
            provider="Test Provider",
            portal_url="https://example.com",
            award_amount=5000,
            deadline="2026-12-31",
        )
        data = _to_db_dict(extract)
        assert data["funding_type"] == "scholarship"
        assert data["employment_required"] is False
        assert data["min_employment_tenure_months"] is None
        assert data["annual_benefit_cap"] is None
        assert data["benefit_coverage_model"] is None
        assert data["partner_network"] is None
        assert data["has_service_commitment"] is False
        assert data["service_commitment_duration_months"] is None
        assert data["vendor_platform"] is None

    def test_to_db_dict_includes_populated_employer_fields(self):
        """_to_db_dict should map populated employer-benefit fields."""
        from scrapers.runner import _to_db_dict

        extract = ScholarshipExtract(
            title="Cleveland Clinic ASPIRE",
            provider="Cleveland Clinic",
            portal_url="https://example.com/aspire",
            award_amount=5250,
            deadline="2026-12-31",
            funding_type="tuition_reimbursement",
            employment_required=True,
            min_employment_tenure_months=6,
            annual_benefit_cap=5250,
            benefit_coverage_model="reimbursement",
            partner_network="internal",
            has_service_commitment=False,
            vendor_platform="academicworks",
        )
        data = _to_db_dict(extract)
        assert data["funding_type"] == "tuition_reimbursement"
        assert data["employment_required"] is True
        assert data["min_employment_tenure_months"] == 6
        assert data["annual_benefit_cap"] == 5250
        assert data["benefit_coverage_model"] == "reimbursement"
        assert data["partner_network"] == "internal"
        assert data["vendor_platform"] == "academicworks"


# ---------------------------------------------------------------------------
# Matcher informational notices
# ---------------------------------------------------------------------------


class TestMatcherInformationalNotices:
    def test_service_commitment_adds_notice_without_score_penalty(self):
        """A service-commitment scholarship should surface an informational
        notice without reducing the matching score.
        """
        profile = _make_profile()
        scholarship = _make_scholarship(
            has_service_commitment=True,
            service_commitment_duration_months=24,
        )
        score, missing = score_scholarship(profile, scholarship)
        # Score should be the same as a non-service-commitment scholarship
        baseline = _make_scholarship()
        baseline_score, _ = score_scholarship(profile, baseline)
        assert score == baseline_score, (
            f"Service commitment should not penalize score: {score} vs {baseline_score}"
        )
        assert "Includes post-graduation service commitment" in missing

    def test_employment_required_adds_notice_without_score_penalty(self):
        """An employment-required scholarship should surface an informational
        notice without reducing the matching score.
        """
        profile = _make_profile()
        scholarship = _make_scholarship(
            employment_required=True,
            funding_type="employer_sponsorship",
        )
        score, missing = score_scholarship(profile, scholarship)
        baseline = _make_scholarship()
        baseline_score, _ = score_scholarship(profile, baseline)
        assert score == baseline_score
        assert "Requires employment or clinical apprenticeship" in missing

    def test_both_notices_appear_when_both_flags_set(self):
        """When both service_commitment and employment_required are true,
        both notices should appear.
        """
        profile = _make_profile()
        scholarship = _make_scholarship(
            has_service_commitment=True,
            employment_required=True,
            funding_type="service_contingent",
        )
        _, missing = score_scholarship(profile, scholarship)
        assert "Includes post-graduation service commitment" in missing
        assert "Requires employment or clinical apprenticeship" in missing

    def test_no_notices_for_standard_scholarship(self):
        """A standard scholarship with no employer/service flags should not
        surface either notice.
        """
        profile = _make_profile()
        scholarship = _make_scholarship()
        _, missing = score_scholarship(profile, scholarship)
        assert "Includes post-graduation service commitment" not in missing
        assert "Requires employment or clinical apprenticeship" not in missing

    def test_service_commitment_notice_on_perfect_match(self):
        """The service-commitment notice should appear even on a 100% match."""
        profile = _make_profile(
            gpa=4.0,
            sai_score=-2000,
            first_gen=True,
            minority_flag=True,
        )
        scholarship = _make_scholarship(
            has_service_commitment=True,
            min_gpa=3.0,
            state_restrictions=["OH"],
            matching_tags=["first_gen", "minority"],
        )
        score, missing = score_scholarship(profile, scholarship)
        assert score == 100, f"Expected perfect match, got {score}"
        assert "Includes post-graduation service commitment" in missing

    def test_match_scholarships_passes_employer_fields_to_result(self):
        """match_scholarships should populate the new fields on MatchResult."""
        profile = _make_profile()
        scholarship = _make_scholarship(
            funding_type="tuition_reimbursement",
            employment_required=True,
            has_service_commitment=True,
            annual_benefit_cap=5250,
            vendor_platform="academicworks",
        )
        results = match_scholarships(profile, [scholarship])
        assert len(results) == 1
        r = results[0]
        assert r.funding_type == "tuition_reimbursement"
        assert r.employment_required is True
        assert r.has_service_commitment is True
        assert r.annual_benefit_cap == 5250
        assert r.vendor_platform == "academicworks"

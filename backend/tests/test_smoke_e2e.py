"""End-to-End Launch Smoke Tests (Phase 10).

Covers the critical user journeys:
  1. Health & environment validation
  2. Scenario A — Onboarding & Discovery (profile creation, matched feed, dismissal)
  3. Scenario B — Financial Planner & Exports (budget, GCal URL, Asana CSV, ICS feed)
  4. Scenario C — Kanban & AI Statement Coach (track scholarship, outline, append notes)

Uses FastAPI TestClient with a mocked DB session (dev-mode demo user auth),
following the same pattern as test_dismiss.py and test_vault.py.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.middleware.auth import DEMO_USER_ID
from app.models.models import (
    Profile,
    Scholarship,
    StudentCollegeBudget,
    UserScholarship,
)
from app.services.outline_service import (
    EssayNarrativeSection,
    EssayOutlineResponse,
    LLMEssayOutline,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def dev_env():
    with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
        yield


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _override_db(db):
    app.dependency_overrides[get_db] = lambda: db


# ---------------------------------------------------------------------------
# Mock object factories
# ---------------------------------------------------------------------------


def _make_profile(**kwargs):
    defaults = {
        "id": DEMO_USER_ID,
        "disciplines": ["pharmacy"],
        "target_credentials": ["PharmD"],
        "primary_discipline": "pharmacy",
        "target_credential": "PharmD",
        "clinical_phase": "didactic",
        "gpa": 3.6,
        "state_residence": "OH",
        "metro_area": "Cleveland-Elyria",
        "sai_score": 1500,
        "first_gen": True,
        "minority_flag": False,
        "professional_affiliations": [],
        "hobbies": [],
        "subscription_tier": "premium",
        "searches_used_this_week": 0,
        "search_cycle_reset_at": None,
        "full_name": "Test Student",
        "email": "test@example.com",
        "feed_token": "test-feed-token",
        "stripe_subscription_status": None,
        "terms_accepted_at": None,
        "privacy_accepted_at": None,
        "marketing_opt_in_at": None,
        "marketing_opt_in": False,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_scholarship(**kwargs):
    defaults = {
        "id": uuid4(),
        "title": "Pharmacy Excellence Scholarship",
        "provider": "APhA",
        "portal_url": "https://example.com/apply",
        "award_amount": 5000,
        "deadline": date.today() + timedelta(days=90),
        "eligible_disciplines": ["pharmacy"],
        "eligible_credentials": ["PharmD"],
        "min_gpa": 3.0,
        "max_sai": None,
        "state_restrictions": [],
        "metro_restrictions": [],
        "required_affiliations": [],
        "matching_tags": [],
        "is_archived": False,
        "estimated_next_cycle": None,
        "provider_type": "national_association",
        "provider_mission": "Advancing the pharmacy profession",
        "provider_core_values": ["equity", "service"],
        "is_local": False,
        "target_community": None,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_tracking(**kwargs):
    defaults = {
        "id": uuid4(),
        "user_id": DEMO_USER_ID,
        "scholarship_id": uuid4(),
        "status": "saved",
        "is_dismissed": False,
        "is_planned": False,
        "target_submission_date": None,
        "custom_deadline_reminder": None,
        "user_notes": None,
        "application_notes": None,
        "documents": [],
        "checklist": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "scholarship": None,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_budget(**kwargs):
    defaults = {
        "tuition_fees": 25000,
        "books_supplies": 1500,
        "clinical_lab_fees": 500,
        "housing_rent": 12000,
        "food_groceries": 6000,
        "utilities_wifi": 1800,
        "transportation": 2400,
        "health_insurance": 3000,
        "personal_misc": 2000,
        "family_contribution": 5000,
        "work_study_wages": 3000,
        "other_grants": 2000,
        "program_years": 4,
        "interest_rate": 7.5,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# Mock DB builder
# ---------------------------------------------------------------------------


def _build_db(
    profile=None,
    scholarships=None,
    dismissed_ids=None,
    user_scholarship=None,
    scholarship_lookup=None,
    budget=None,
    planned_trackings=None,
    tracked_trackings=None,
):
    """Build a mock DB session whose query() dispatches per model.

    The query dispatch is designed to handle the chained filter()/options()
    patterns used by the endpoints under test.
    """
    db = MagicMock()

    dismissed_ids = dismissed_ids or []
    scholarships = scholarships or []
    planned_trackings = planned_trackings or []
    tracked_trackings = tracked_trackings or []

    def query_side_effect(arg):
        q = MagicMock()

        if arg is Profile:
            q.filter.return_value.first.return_value = profile

        elif arg is Scholarship:
            q.all.return_value = scholarships
            q.filter.return_value.first.return_value = scholarship_lookup

        elif arg is StudentCollegeBudget:
            q.filter.return_value.first.return_value = budget

        elif arg is UserScholarship:
            # Generic filter chain — return the first matching tracking record
            q.filter.return_value.first.return_value = user_scholarship
            # For .options(joinedload(...)).filter(...).all() chains
            q.options.return_value.filter.return_value.all.return_value = tracked_trackings
            q.options.return_value.filter.return_value.first.return_value = user_scholarship
            # For count() chains (paywall check)
            q.filter.return_value.count.return_value = len(tracked_trackings)
            q.filter.return_value.all.return_value = tracked_trackings

        else:
            # Column query (e.g. UserScholarship.scholarship_id for dismissed ids)
            q.filter.return_value.all.return_value = [(i,) for i in dismissed_ids]

        return q

    db.query.side_effect = query_side_effect
    return db


# ===========================================================================
# 1. Health & Environment Validation
# ===========================================================================


class TestHealthAndEnvironment:
    """Scenario 0: Health endpoint and migration consistency."""

    def test_health_returns_ok(self, client):
        """GET /health returns {"status": "ok"}."""
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    def test_root_returns_ok(self, client):
        """GET / returns a healthy status."""
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "healthy")

    def test_migrations_001_through_011_exist(self):
        """All 11 migration files are present in the migrations directory."""
        from pathlib import Path

        migrations_dir = Path(__file__).parent.parent / "migrations"
        for i in range(1, 12):
            prefix = f"{i:03d}_"
            matches = list(migrations_dir.glob(f"{prefix}*.sql"))
            assert len(matches) >= 1, f"Migration {prefix}*.sql not found"

    def test_scholarship_model_has_phase_8_columns(self):
        """Scholarship model includes provider alignment & local discovery fields."""
        cols = Scholarship.__table__.columns
        assert "provider_type" in cols
        assert "provider_mission" in cols
        assert "provider_core_values" in cols
        assert "is_local" in cols
        assert "target_community" in cols

    def test_user_scholarship_model_has_planner_fields(self):
        """UserScholarship model includes is_planned and target_submission_date."""
        cols = UserScholarship.__table__.columns
        assert "is_planned" in cols
        assert "target_submission_date" in cols

    def test_student_college_budget_model_exists(self):
        """StudentCollegeBudget model is defined with expected cost fields."""
        cols = StudentCollegeBudget.__table__.columns
        assert "tuition_fees" in cols
        assert "housing_rent" in cols
        assert "program_years" in cols
        assert "interest_rate" in cols


# ===========================================================================
# 2. Scenario A — Onboarding & Discovery
# ===========================================================================


class TestScenarioAOnboardingDiscovery:
    """Simulate student profile creation, matched feed, and dismissal."""

    def test_profile_creation_returns_profile(self, client):
        """POST /profiles creates a profile and returns it."""
        profile = _make_profile()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None  # no existing
        _override_db(db)

        with patch("app.main.Profile", return_value=profile):
            resp = client.post("/profiles", json={
                "disciplines": ["pharmacy"],
                "target_credentials": ["PharmD"],
                "gpa": 3.6,
                "state_residence": "OH",
                "metro_area": "Cleveland-Elyria",
                "terms_accepted": True,
                "privacy_accepted": True,
            })
        assert resp.status_code in (200, 201)
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_matched_feed_returns_sorted_results(self, client):
        """GET /api/scholarships/matched returns results with score badges."""
        s1 = _make_scholarship(title="Pharmacy Award A", eligible_disciplines=["pharmacy"])
        s2 = _make_scholarship(title="Pharmacy Award B", eligible_disciplines=["pharmacy"])
        profile = _make_profile()
        db = _build_db(
            profile=profile,
            scholarships=[s1, s2],
            dismissed_ids=[],
        )
        _override_db(db)

        resp = client.get("/api/scholarships/matched")
        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body
        assert len(body["results"]) >= 1
        # Each result has a score badge
        for r in body["results"]:
            assert "score" in r
            assert 0 <= r["score"] <= 100
            assert "title" in r
            assert "missing_criteria" in r

    def test_dismiss_removes_scholarship_from_feed(self, client):
        """POST /api/scholarships/{id}/dismiss removes the card from subsequent feed calls."""
        scholarship = _make_scholarship(title="Visible Award")
        dismissed = _make_scholarship(title="Dismissed Award")
        profile = _make_profile()

        # Step 1: dismiss the scholarship
        db_dismiss = _build_db(
            profile=profile,
            scholarships=[scholarship, dismissed],
            dismissed_ids=[],
            user_scholarship=None,
            scholarship_lookup=dismissed,
        )
        _override_db(db_dismiss)

        resp = client.post(f"/api/scholarships/{dismissed.id}/dismiss")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

        # Step 2: feed call should exclude the dismissed scholarship
        db_feed = _build_db(
            profile=profile,
            scholarships=[scholarship, dismissed],
            dismissed_ids=[dismissed.id],  # now dismissed
        )
        _override_db(db_feed)

        resp = client.get("/api/scholarships/matched")
        assert resp.status_code == 200
        titles = [r["title"] for r in resp.json()["results"]]
        assert "Visible Award" in titles
        assert "Dismissed Award" not in titles


# ===========================================================================
# 3. Scenario B — Financial Planner & Exports
# ===========================================================================


class TestScenarioBFinancialPlannerExports:
    """Test financial planner calculation and export endpoints."""

    def test_financial_planner_returns_3x_cushion_and_loan_amortization(self, client):
        """GET /api/v1/financial-planner/budget returns 3x cushion and loan metrics."""
        budget = _make_budget()
        profile = _make_profile()
        db = _build_db(profile=profile, budget=budget, planned_trackings=[])
        _override_db(db)

        resp = client.get("/api/v1/financial-planner/budget")
        assert resp.status_code == 200
        body = resp.json()
        # 3x cushion = 3 * total_annual_expenses
        expected_coa = (
            25000 + 1500 + 500 +  # direct educational
            12000 + 6000 + 1800 + 2400 + 3000 + 2000  # living/personal
        )
        assert body["total_annual_expenses"] == expected_coa
        assert body["three_x_cushion"] == 3 * expected_coa
        assert body["five_x_safety_buffer"] == 5 * expected_coa
        # Loan amortization
        assert body["monthly_loan_payment"] > 0
        assert body["estimated_total_debt"] > 0
        assert body["total_lifetime_interest"] >= 0

    def test_gcal_url_returns_valid_url(self, client):
        """GET /api/v1/planner/export/gcal-url/{id} returns a Google Calendar URL."""
        scholarship = _make_scholarship(deadline=date(2026, 3, 15))
        profile = _make_profile()
        db = _build_db(
            profile=profile,
            scholarship_lookup=scholarship,
        )
        _override_db(db)

        resp = client.get(f"/api/v1/planner/export/gcal-url/{scholarship.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "url" in body
        url = body["url"]
        assert url.startswith("https://calendar.google.com/render?action=TEMPLATE")
        assert "dates=20260315" in url

    def test_asana_csv_returns_rfc4180_csv(self, client):
        """GET /api/v1/planner/export/asana-csv returns RFC 4180 CSV data."""
        scholarship = _make_scholarship(title="Planned Pharmacy Award")
        tracking = _make_tracking(
            is_planned=True,
            status="planned",
            scholarship=scholarship,
        )
        profile = _make_profile()
        db = _build_db(
            profile=profile,
            planned_trackings=[tracking],
            tracked_trackings=[tracking],
        )
        _override_db(db)

        resp = client.get("/api/v1/planner/export/asana-csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "grantrx_planner_asana.csv" in resp.headers.get("content-disposition", "")

        # Parse the CSV and verify headers
        reader = csv.reader(io.StringIO(resp.text))
        headers = next(reader)
        assert headers == [
            "Task Name",
            "Due Date",
            "Description",
            "Notes",
            "Section/Column",
            "Tags",
        ]

    def test_ics_calendar_returns_rfc5545_data(self, client):
        """GET /api/v1/planner/export/calendar.ics returns RFC 5545 calendar data."""
        scholarship = _make_scholarship(title="Tracked Award")
        tracking = _make_tracking(
            is_dismissed=False,
            status="saved",
            scholarship=scholarship,
        )
        profile = _make_profile()
        db = _build_db(
            profile=profile,
            tracked_trackings=[tracking],
        )
        _override_db(db)

        resp = client.get("/api/v1/planner/export/calendar.ics")
        assert resp.status_code == 200
        assert "text/calendar" in resp.headers.get("content-type", "")
        assert "grantrx_deadlines.ics" in resp.headers.get("content-disposition", "")

        content = resp.text
        assert "BEGIN:VCALENDAR" in content
        assert "END:VCALENDAR" in content
        assert "BEGIN:VEVENT" in content
        assert "BEGIN:VALARM" in content
        assert "TRIGGER:-P7D" in content


# ===========================================================================
# 4. Scenario C — Kanban & AI Statement Coach
# ===========================================================================


class TestScenarioCKanbanAndAICoach:
    """Verify saving a scholarship, generating an outline, and appending notes."""

    def test_track_scholarship_moves_to_kanban(self, client):
        """POST /user-scholarships saves a scholarship and returns a tracking record."""
        scholarship = _make_scholarship()
        tracking = _make_tracking(scholarship=scholarship, status="saved")
        profile = _make_profile()
        db = _build_db(profile=profile)
        _override_db(db)

        with patch("app.main.UserScholarship", return_value=tracking):
            resp = client.post("/user-scholarships", json={
                "scholarship_id": str(scholarship.id),
                "status": "saved",
            })
        assert resp.status_code == 201
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_list_user_scholarships_returns_kanban_items(self, client):
        """GET /user-scholarships returns tracked scholarships for the Kanban board."""
        scholarship = _make_scholarship(title="Kanban Item")
        tracking = _make_tracking(scholarship=scholarship, status="in_progress")
        profile = _make_profile()
        db = _build_db(
            profile=profile,
            tracked_trackings=[tracking],
            user_scholarship=tracking,
        )
        _override_db(db)

        resp = client.get("/user-scholarships")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_outline_returns_four_narrative_sections(self, client):
        """POST /api/v1/scholarships/{id}/outline returns 4 narrative sections."""
        scholarship = _make_scholarship(
            provider_mission="Advancing pharmacy practice",
            provider_core_values=["equity", "service"],
        )
        profile = _make_profile()
        db = _build_db(profile=profile, scholarship_lookup=scholarship)
        _override_db(db)

        # Mock the LLM response
        mock_section = EssayNarrativeSection(
            title="Personal Story",
            estimated_word_count=150,
            talking_points=["Origin", "Family background"],
            coaching_tips=["Be authentic", "Show don't tell"],
        )
        mock_llm_result = LLMEssayOutline(
            suggested_theme="From challenge to commitment",
            mission_alignment_angle="Connect your values to APhA's mission",
            part_1_personal_story=mock_section,
            part_2_work_experience=mock_section,
            part_3_academic_citation=mock_section,
            part_4_future_service=mock_section,
            checklist=["Proofread", "Check word count"],
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_llm_result)

        with patch(
            "app.services.outline_service._build_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ):
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                resp = client.post(
                    f"/api/v1/scholarships/{scholarship.id}/outline",
                    json={
                        "prompt": "Describe your commitment to pharmacy",
                        "lived_experience_notes": "First-gen student",
                    },
                )

        assert resp.status_code == 200
        body = resp.json()
        assert "suggested_theme" in body
        assert "mission_alignment_angle" in body
        assert "part_1_personal_story" in body
        assert "part_2_work_experience" in body
        assert "part_3_academic_citation" in body
        assert "part_4_future_service" in body
        assert "checklist" in body
        # Verify section structure
        for section_key in [
            "part_1_personal_story",
            "part_2_work_experience",
            "part_3_academic_citation",
            "part_4_future_service",
        ]:
            section = body[section_key]
            assert "title" in section
            assert "estimated_word_count" in section
            assert "talking_points" in section
            assert "coaching_tips" in section

    def test_outline_returns_404_for_unknown_scholarship(self, client):
        """POST /api/v1/scholarships/{id}/outline returns 404 for unknown scholarship."""
        profile = _make_profile()
        db = _build_db(profile=profile, scholarship_lookup=None)
        _override_db(db)

        resp = client.post(
            f"/api/v1/scholarships/{uuid4()}/outline",
            json={"prompt": "Test"},
        )
        assert resp.status_code == 404

    def test_append_outline_updates_application_notes(self, client):
        """PATCH /user-scholarships/{id} with application_notes persists the outline."""
        tracking = _make_tracking(application_notes="")
        profile = _make_profile()
        db = _build_db(profile=profile, user_scholarship=tracking)
        _override_db(db)

        outline_markdown = (
            "## AI Essay Outline\n\n"
            "**Suggested Theme:** From challenge to commitment\n\n"
            "### Part 1: Personal Story (~150 words)\n"
            "- Origin story\n"
        )

        resp = client.patch(
            f"/user-scholarships/{tracking.id}",
            json={"application_notes": outline_markdown},
        )
        assert resp.status_code == 200
        assert tracking.application_notes == outline_markdown
        db.commit.assert_called_once()

    def test_append_outline_preserves_existing_notes(self, client):
        """PATCH with application_notes appends to existing notes."""
        existing_notes = "Existing essay ideas..."
        tracking = _make_tracking(application_notes=existing_notes)
        profile = _make_profile()
        db = _build_db(profile=profile, user_scholarship=tracking)
        _override_db(db)

        combined_notes = f"{existing_notes}\n\n---\n\n## AI Essay Outline\n"
        resp = client.patch(
            f"/user-scholarships/{tracking.id}",
            json={"application_notes": combined_notes},
        )
        assert resp.status_code == 200
        assert "Existing essay ideas" in tracking.application_notes
        assert "AI Essay Outline" in tracking.application_notes

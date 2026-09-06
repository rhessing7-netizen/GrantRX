"""Tests for Discovery Feed curation: dismiss/undismiss endpoints and
feed filtering of dismissed scholarships.

Uses FastAPI TestClient with a mocked DB session (dev-mode demo user auth).
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.middleware.auth import DEMO_USER_ID
from app.models.models import Profile, Scholarship, UserScholarship


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_profile(**kwargs):
    defaults = {
        "id": DEMO_USER_ID,
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
        "subscription_tier": "premium",  # premium avoids masking in feed tests
        "searches_used_this_week": 0,
        "search_cycle_reset_at": None,
    }
    defaults.update(kwargs)
    obj = MagicMock(spec_set=None)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_scholarship(**kwargs):
    defaults = {
        "id": uuid4(),
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
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_db(profile, scholarships, dismissed_ids, user_scholarship=None, scholarship_lookup=None):
    """Build a mock DB session whose query() dispatches per model/column."""
    db = MagicMock()

    def query_side_effect(arg):
        q = MagicMock()
        if arg is Profile:
            q.filter.return_value.first.return_value = profile
        elif arg is Scholarship:
            q.all.return_value = scholarships
            q.filter.return_value.first.return_value = scholarship_lookup
            q.filter.return_value.all.return_value = [
                s for s in scholarships if not s.is_archived
            ]
        elif arg is UserScholarship:
            q.filter.return_value.first.return_value = user_scholarship
        else:
            # Column query: UserScholarship.scholarship_id for dismissed ids
            q.filter.return_value.all.return_value = [(i,) for i in dismissed_ids]
        return q

    db.query.side_effect = query_side_effect
    return db


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
# Tests: POST /api/scholarships/{id}/dismiss
# ---------------------------------------------------------------------------

class TestDismiss:
    def test_dismiss_creates_new_record(self, client):
        """Dismissing an untracked scholarship creates a new UserScholarship."""
        scholarship = _make_scholarship()
        db = _make_db(
            profile=_make_profile(),
            scholarships=[scholarship],
            dismissed_ids=[],
            user_scholarship=None,  # no existing tracking record
            scholarship_lookup=scholarship,
        )
        _override_db(db)

        resp = client.post(f"/api/scholarships/{scholarship.id}/dismiss")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "dismissed"
        assert body["scholarship_id"] == str(scholarship.id)
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_dismiss_updates_existing_record(self, client):
        """Dismissing an already-tracked scholarship flips is_dismissed."""
        scholarship = _make_scholarship()
        existing = MagicMock()
        existing.is_dismissed = False
        db = _make_db(
            profile=_make_profile(),
            scholarships=[scholarship],
            dismissed_ids=[],
            user_scholarship=existing,
            scholarship_lookup=scholarship,
        )
        _override_db(db)

        resp = client.post(f"/api/scholarships/{scholarship.id}/dismiss")
        assert resp.status_code == 200
        assert existing.is_dismissed is True
        db.add.assert_not_called()
        db.commit.assert_called_once()

    def test_dismiss_unknown_scholarship_404(self, client):
        """Dismissing a nonexistent scholarship returns 404."""
        db = _make_db(
            profile=_make_profile(),
            scholarships=[],
            dismissed_ids=[],
            scholarship_lookup=None,  # not found
        )
        _override_db(db)

        resp = client.post(f"/api/scholarships/{uuid4()}/dismiss")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: POST /api/scholarships/{id}/undismiss
# ---------------------------------------------------------------------------

class TestUndismiss:
    def test_undismiss_restores(self, client):
        """Undismissing a dismissed scholarship clears the flag."""
        existing = MagicMock()
        existing.is_dismissed = True
        db = _make_db(
            profile=_make_profile(),
            scholarships=[],
            dismissed_ids=[],
            user_scholarship=existing,
        )
        _override_db(db)

        sid = uuid4()
        resp = client.post(f"/api/scholarships/{sid}/undismiss")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "restored"
        assert body["scholarship_id"] == str(sid)
        assert existing.is_dismissed is False
        db.commit.assert_called_once()

    def test_undismiss_without_dismissal_404(self, client):
        """Undismissing when no dismissal exists returns 404."""
        db = _make_db(
            profile=_make_profile(),
            scholarships=[],
            dismissed_ids=[],
            user_scholarship=None,
        )
        _override_db(db)

        resp = client.post(f"/api/scholarships/{uuid4()}/undismiss")
        assert resp.status_code == 404

    def test_undismiss_not_dismissed_record_404(self, client):
        """Undismissing a tracked-but-not-dismissed record returns 404."""
        existing = MagicMock()
        existing.is_dismissed = False
        db = _make_db(
            profile=_make_profile(),
            scholarships=[],
            dismissed_ids=[],
            user_scholarship=existing,
        )
        _override_db(db)

        resp = client.post(f"/api/scholarships/{uuid4()}/undismiss")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: feed filtering of dismissed scholarships
# ---------------------------------------------------------------------------

class TestFeedFiltering:
    def test_matched_feed_excludes_dismissed(self, client):
        """Dismissed scholarships must not appear in /api/scholarships/matched."""
        kept = _make_scholarship(title="Visible Scholarship")
        dismissed = _make_scholarship(title="Hidden Scholarship")
        db = _make_db(
            profile=_make_profile(),
            scholarships=[kept, dismissed],
            dismissed_ids=[dismissed.id],
        )
        _override_db(db)

        resp = client.get("/api/scholarships/matched")
        assert resp.status_code == 200
        titles = [r["title"] for r in resp.json()["results"]]
        assert "Visible Scholarship" in titles
        assert "Hidden Scholarship" not in titles

    def test_matched_feed_all_visible_without_dismissals(self, client):
        """With no dismissals, all scholarships appear."""
        s1 = _make_scholarship(title="First")
        s2 = _make_scholarship(title="Second")
        db = _make_db(
            profile=_make_profile(),
            scholarships=[s1, s2],
            dismissed_ids=[],
        )
        _override_db(db)

        resp = client.get("/api/scholarships/matched")
        assert resp.status_code == 200
        titles = [r["title"] for r in resp.json()["results"]]
        assert set(titles) == {"First", "Second"}

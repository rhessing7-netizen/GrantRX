"""Tests for the onboarding live-matching projection endpoint.

POST /api/scholarships/match-preview accepts a partial (unsaved) profile and
returns how many grants would pass the hard gates plus the summed award pool.
It must be reachable without a session so the wizard can call it before a
profile exists.
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
from app.models.models import Scholarship


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
        "provider_mission": None,
        "provider_core_values": [],
        "funding_type": "scholarship",
        "employment_required": False,
        "has_service_commitment": False,
        "annual_benefit_cap": None,
        "vendor_platform": None,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_db(scholarships):
    db = MagicMock()

    def query_side_effect(arg):
        q = MagicMock()
        if arg is Scholarship:
            q.filter.return_value.all.return_value = scholarships
        return q

    db.query.side_effect = query_side_effect
    return db


@pytest.fixture(autouse=True)
def prod_env():
    """Run as production so the demo-user shortcut cannot mask a missing
    public-path entry — the endpoint must work with no Authorization header."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
        yield


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestMatchPreview:
    def test_counts_and_sums_matching_grants(self, client):
        """Unrestricted grants count for everyone; funding is summed."""
        db = _make_db([
            _make_scholarship(award_amount=1000),
            _make_scholarship(award_amount=2500),
        ])
        app.dependency_overrides[get_db] = lambda: db

        resp = client.post("/api/scholarships/match-preview", json={})
        assert resp.status_code == 200
        assert resp.json() == {"projected_count": 2, "projected_funding_total": 3500}

    def test_discipline_hard_gate_applies(self, client):
        """A nursing student should not see pharmacy-only awards in the projection."""
        db = _make_db([
            _make_scholarship(eligible_disciplines=["pharmacy"], award_amount=9000),
            _make_scholarship(eligible_disciplines=["nursing"], award_amount=1500),
            _make_scholarship(eligible_disciplines=[], award_amount=500),
        ])
        app.dependency_overrides[get_db] = lambda: db

        resp = client.post(
            "/api/scholarships/match-preview",
            json={"disciplines": ["nursing"], "primary_discipline": "nursing"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"projected_count": 2, "projected_funding_total": 2000}

    def test_public_without_auth(self, client):
        """No Authorization header must not yield 401 — the wizard is pre-login."""
        app.dependency_overrides[get_db] = lambda: _make_db([])
        resp = client.post("/api/scholarships/match-preview", json={"gpa": 3.2})
        assert resp.status_code == 200
        assert resp.json()["projected_count"] == 0

    def test_never_persists(self, client):
        """The transient profile must never be added or committed."""
        db = _make_db([_make_scholarship()])
        app.dependency_overrides[get_db] = lambda: db
        client.post("/api/scholarships/match-preview", json={"state_residence": "OH"})
        db.add.assert_not_called()
        db.commit.assert_not_called()

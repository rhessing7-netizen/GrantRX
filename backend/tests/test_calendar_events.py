"""Calendar events endpoint tests — including the null-deadline regression.

A tracked scholarship may legitimately have no provider-listed deadline.
calendar_service emits deadline=None; CalendarEventOut must accept it and
return `deadline: null` (never fabricate a date, never 500).

Uses FastAPI TestClient with a mocked DB session (dev-mode demo user auth),
following the same harness as test_dismiss.py.
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
from app.models.models import UserScholarship


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_scholarship(**kwargs):
    defaults = {
        "id": uuid4(),
        "title": "No Deadline Award",
        "provider": "Test Provider",
        "deadline": date.today() + timedelta(days=60),
        "award_amount": 2500,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_tracking_row(scholarship, **kwargs):
    defaults = {
        "id": uuid4(),
        "status": "saved",
        "custom_deadline_reminder": None,
        "user_notes": None,
        "scholarship": scholarship,
    }
    defaults.update(kwargs)
    row = MagicMock()
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


def _make_db(rows):
    """Mock DB whose UserScholarship query chain returns `rows`.

    get_calendar_events calls .options(joinedload(...)) before .filter(),
    so .options() must return the same query mock.
    """
    db = MagicMock()

    q = MagicMock()
    q.options.return_value = q
    q.filter.return_value.all.return_value = rows

    db.query.side_effect = lambda model: q if model is UserScholarship else MagicMock()
    return db


@pytest.fixture(autouse=True)
def dev_env():
    with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
        yield


@pytest.fixture
def client(authenticated_client_factory):
    yield authenticated_client_factory(app)
    app.dependency_overrides.clear()


def _override_db(db):
    app.dependency_overrides[get_db] = lambda: db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCalendarEvents:
    def test_null_deadline_preserved_no_500(self, client):
        """Tracked scholarship without a deadline → 200 with deadline: null."""
        s = _make_scholarship(deadline=None)
        row = _make_tracking_row(s)
        _override_db(_make_db([row]))

        resp = client.get("/api/calendar/events")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["deadline"] is None
        assert body[0]["title"] == "No Deadline Award"

    def test_dated_deadline_unaffected(self, client):
        """A normal dated deadline still serializes as ISO string."""
        s = _make_scholarship(deadline=date(2030, 5, 1))
        row = _make_tracking_row(s)
        _override_db(_make_db([row]))

        resp = client.get("/api/calendar/events")
        assert resp.status_code == 200
        assert resp.json()[0]["deadline"] == "2030-05-01"

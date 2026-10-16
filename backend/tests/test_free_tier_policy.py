"""V1 free-tier entitlement regression tests.

Approved product policy:
  - Every tier sees ALL legitimately matched results — no subscription-based
    masking, blurring, locking, or top-N truncation. ``is_locked`` must always
    be False and ``masked_*`` must always be None in feed payloads.
  - Free tier: 3 explicit non-empty keyword searches per rolling 7 days.
    The 4th attempt returns HTTP 402 via the existing paywall payload.
    Filter changes, refreshes, sorting, pagination, detail views, and all
    other non-keyword interactions never consume quota.
  - Application tracking limits are covered separately (unchanged).

Uses FastAPI TestClient with a mocked DB session, following the same
harness as test_dismiss.py — no real DB or network required.
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
from app.middleware.tier_guard import FREE_SEARCH_LIMIT
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
        "subscription_tier": "free",
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
        "funding_type": "scholarship",
        "employment_required": False,
        "min_employment_tenure_months": None,
        "annual_benefit_cap": None,
        "benefit_coverage_model": None,
        "partner_network": None,
        "has_service_commitment": False,
        "service_commitment_duration_months": None,
        "vendor_platform": None,
        "source_url": None,
        "extraction_method": None,
        "verified_fields": {},
        "verified_at": None,
        "verification_status": "verified_current",
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_db(profile, scholarships, dismissed_ids=None):
    """Mock DB session dispatching per model/column (same shape as
    test_dismiss._make_db)."""
    dismissed_ids = dismissed_ids or []
    db = MagicMock()

    def query_side_effect(arg):
        q = MagicMock()
        if arg is Profile:
            q.filter.return_value.first.return_value = profile
        elif arg is Scholarship:
            q.all.return_value = scholarships
            q.filter.return_value.all.return_value = [
                s for s in scholarships if not s.is_archived
            ]
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
def client(authenticated_client_factory):
    yield authenticated_client_factory(app)
    app.dependency_overrides.clear()


def _override_db(db):
    app.dependency_overrides[get_db] = lambda: db


# ---------------------------------------------------------------------------
# A. All results visible — no tier masking, no top-N truncation
# ---------------------------------------------------------------------------

class TestAllResultsVisible:
    def test_free_user_sees_all_matches_no_locking(self, client):
        """Free user with >3 matches: every result is returned, readable,
        and never subscription-locked."""
        scholarships = [
            _make_scholarship(title=f"Scholarship {i:02d}") for i in range(10)
        ]
        profile = _make_profile(subscription_tier="free")
        _override_db(_make_db(profile, scholarships))

        resp = client.get("/api/scholarships/matched")
        assert resp.status_code == 200
        body = resp.json()

        # Not truncated to 3 — every legitimate match is present.
        assert len(body["results"]) == 10
        assert body["visible"] == 10
        assert body["tier"] == "free"

        for r in body["results"]:
            assert r["is_locked"] is False
            assert r["masked_title"] is None
            assert r["masked_provider"] is None
            # Real title/provider/apply link are fully readable.
            assert r["title"].startswith("Scholarship")
            assert r["provider"] == "Test Provider"
            assert r["portal_url"] == "https://example.com/apply"

    def test_free_user_sees_all_keyword_search_results(self, client):
        """Result visibility is identical on a quota-consuming keyword search."""
        scholarships = [
            _make_scholarship(title=f"Nursing Award {i:02d}") for i in range(10)
        ]
        _override_db(_make_db(_make_profile(), scholarships))

        resp = client.get("/api/scholarships/matched", params={"query": "nursing"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) == 10
        assert body["visible"] == 10
        assert all(r["is_locked"] is False for r in body["results"])
        assert all(r["portal_url"] for r in body["results"])


# ---------------------------------------------------------------------------
# B. Search quota — 3 free keyword searches per rolling 7 days
# ---------------------------------------------------------------------------

class TestSearchQuota:
    def test_first_three_searches_succeed_fourth_blocked(self, client):
        """Searches #1-#3 allowed; #4 within the window hits the 402 paywall."""
        scholarships = [_make_scholarship(title="Nursing Award")]
        profile = _make_profile(subscription_tier="free")
        _override_db(_make_db(profile, scholarships))

        for expected_used in (1, 2, 3):
            resp = client.get("/api/scholarships/matched", params={"query": "nursing"})
            assert resp.status_code == 200
            assert profile.searches_used_this_week == expected_used
            assert resp.json()["searches_used_this_week"] == expected_used

        resp = client.get("/api/scholarships/matched", params={"query": "nursing"})
        assert resp.status_code == 402
        detail = resp.json()["detail"]
        assert detail["detail"] == "PAYWALL_SEARCH_LIMIT_REACHED"
        assert detail["feature"] == "keyword_search"
        assert detail["limit"] == FREE_SEARCH_LIMIT == 3
        # The blocked attempt must not inflate the counter.
        assert profile.searches_used_this_week == 3


# ---------------------------------------------------------------------------
# C. Non-search actions do not consume quota
# ---------------------------------------------------------------------------

class TestNonSearchActionsFree:
    def test_refresh_without_query_is_free(self, client):
        """Loading the matched feed (no keyword) never consumes a search."""
        profile = _make_profile(subscription_tier="free")
        _override_db(_make_db(profile, [_make_scholarship()]))

        for _ in range(5):
            resp = client.get("/api/scholarships/matched")
            assert resp.status_code == 200
        assert profile.searches_used_this_week == 0

    def test_whitespace_query_is_free(self, client):
        """Empty/whitespace queries are refreshes, not searches."""
        profile = _make_profile(subscription_tier="free")
        _override_db(_make_db(profile, [_make_scholarship()]))

        for q in ("", "   ", "\t\n"):
            resp = client.get("/api/scholarships/matched", params={"query": q})
            assert resp.status_code == 200
        assert profile.searches_used_this_week == 0

    def test_quota_exhausted_user_can_still_refresh(self, client):
        """A capped free user keeps full feed access — only new keyword
        searches are blocked."""
        profile = _make_profile(
            subscription_tier="free",
            searches_used_this_week=FREE_SEARCH_LIMIT,
        )
        _override_db(_make_db(profile, [_make_scholarship()] * 10))

        resp = client.get("/api/scholarships/matched")
        assert resp.status_code == 200
        body = resp.json()
        # Capped users still see every legitimate result — nothing is locked.
        assert len(body["results"]) == 10
        assert body["visible"] == 10
        assert all(r["is_locked"] is False for r in body["results"])
        assert profile.searches_used_this_week == FREE_SEARCH_LIMIT


# ---------------------------------------------------------------------------
# D. Premium — unlimited, same full visibility
# ---------------------------------------------------------------------------

class TestPremium:
    def test_premium_sees_all_results_and_never_debited(self, client):
        """Premium: all results visible + unlimited searches."""
        scholarships = [
            _make_scholarship(title=f"Award {i:02d}") for i in range(10)
        ]
        profile = _make_profile(
            subscription_tier="premium",
            searches_used_this_week=999,
        )
        _override_db(_make_db(profile, scholarships))

        resp = client.get("/api/scholarships/matched")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) == 10
        assert body["visible"] == 10
        assert body["tier"] == "premium"
        assert all(r["is_locked"] is False for r in body["results"])

        # Keyword searches never consume quota for premium.
        resp = client.get("/api/scholarships/matched", params={"query": "award"})
        assert resp.status_code == 200
        assert profile.searches_used_this_week == 999

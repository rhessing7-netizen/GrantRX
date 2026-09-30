"""Regression tests for PATCH-like profile update semantics.

E2E Phase 1 found that optional scalar profile fields could not be cleared:
the frontend omitted empty values and the backend ignored explicit nulls.
These tests pin the intended contract:

  * omitted field  -> existing value preserved
  * explicit null  -> nullable optional field cleared
  * null on a protected/non-nullable field -> ignored
  * arrays/booleans still update normally
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.database import get_db
from app.main import app
from app.middleware.auth import DEMO_USER_ID


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
        "subscription_tier": "free",
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
        "has_completed_tour": False,
        "created_at": None,
        "updated_at": None,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _db_returning(profile):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = profile
    _override_db(db)
    return db


class TestPutProfilesPartialUpdate:
    def test_omitted_fields_preserve_existing_values(self, client):
        """PUT without a field must leave the stored value untouched."""
        profile = _make_profile()
        _db_returning(profile)

        resp = client.put("/profiles", json={"disciplines": ["Biology"]})
        assert resp.status_code == 200

        assert profile.disciplines == ["Biology"]          # updated
        assert profile.gpa == 3.6                           # preserved
        assert profile.state_residence == "OH"              # preserved
        assert profile.metro_area == "Cleveland-Elyria"     # preserved
        assert profile.sai_score == 1500                    # preserved
        assert profile.clinical_phase == "didactic"         # preserved
        assert profile.target_credential == "PharmD"        # preserved

    def test_explicit_null_clears_optional_scalars(self, client):
        """PUT with explicit null clears whitelisted nullable fields."""
        profile = _make_profile()
        _db_returning(profile)

        resp = client.put(
            "/profiles",
            json={
                "gpa": None,
                "state_residence": None,
                "metro_area": None,
                "clinical_phase": None,
                "sai_score": None,
                "target_credential": None,
            },
        )
        assert resp.status_code == 200

        assert profile.gpa is None
        assert profile.state_residence is None
        assert profile.metro_area is None
        assert profile.clinical_phase is None
        assert profile.sai_score is None
        assert profile.target_credential is None
        # Untouched fields still intact
        assert profile.disciplines == ["pharmacy"]
        assert profile.first_gen is True

    def test_null_on_protected_field_is_ignored(self, client):
        """Explicit null must NOT clear non-clearable fields."""
        profile = _make_profile(subscription_tier="premium")
        _db_returning(profile)

        resp = client.put("/profiles", json={"subscription_tier": None})
        # subscription_tier=None fails pydantic enum validation or is ignored;
        # either way the stored tier must remain untouched.
        if resp.status_code == 200:
            assert profile.subscription_tier == "premium"
        else:
            assert resp.status_code == 422
            assert profile.subscription_tier == "premium"

    def test_arrays_and_booleans_still_update(self, client):
        """Explicit empty arrays and false booleans continue to apply."""
        profile = _make_profile(hobbies=["reading"], first_gen=True)
        _db_returning(profile)

        resp = client.put(
            "/profiles",
            json={"hobbies": [], "first_gen": False, "disciplines": []},
        )
        assert resp.status_code == 200
        assert profile.hobbies == []
        assert profile.first_gen is False
        assert profile.disciplines == []

    def test_mixed_clear_and_update(self, client):
        """One request can clear some fields and set others."""
        profile = _make_profile()
        _db_returning(profile)

        resp = client.put(
            "/profiles",
            json={"gpa": 3.9, "state_residence": None},
        )
        assert resp.status_code == 200
        assert profile.gpa == 3.9
        assert profile.state_residence is None
        assert profile.metro_area == "Cleveland-Elyria"  # omitted -> preserved


class TestPostProfilesUpsertClears:
    def test_upsert_explicit_null_clears(self, client):
        """POST /profiles upsert path honors explicit null for clearable fields."""
        profile = _make_profile()
        _db_returning(profile)

        resp = client.post(
            "/profiles",
            json={
                "disciplines": ["Biology"],
                "target_credentials": [],
                "gpa": None,
                "state_residence": None,
            },
        )
        assert resp.status_code == 200
        assert profile.gpa is None
        assert profile.state_residence is None
        assert profile.disciplines == ["Biology"]


class TestSubscriptionTierEntitlement:
    """subscription_tier is server-controlled via Stripe webhooks; ordinary
    client profile payloads must never raise or lower it."""

    def test_new_profile_never_receives_client_tier(self, client):
        """POST create: client-sent tier is dropped; ORM default (free) applies."""
        _db_returning(None)  # no existing profile
        with patch("app.main.Profile") as MockProfile:
            MockProfile.return_value = _make_profile()
            resp = client.post(
                "/profiles",
                json={
                    "disciplines": ["Biology"],
                    "subscription_tier": "premium",  # attempted self-promotion
                },
            )
        assert resp.status_code == 200
        kwargs = MockProfile.call_args.kwargs
        assert "subscription_tier" not in kwargs

    def test_premium_survives_post_upsert(self, client):
        """Onboarding re-save (POST upsert) must not downgrade Premium."""
        profile = _make_profile(subscription_tier="premium")
        _db_returning(profile)

        resp = client.post(
            "/profiles",
            json={"disciplines": ["Biology"], "hobbies": ["music"]},
        )
        assert resp.status_code == 200
        assert profile.subscription_tier == "premium"
        assert profile.disciplines == ["Biology"]

    def test_premium_survives_put_edit(self, client):
        """Ordinary profile edit must not downgrade Premium."""
        profile = _make_profile(subscription_tier="premium")
        _db_returning(profile)

        resp = client.put("/profiles", json={"gpa": 3.9})
        assert resp.status_code == 200
        assert profile.subscription_tier == "premium"
        assert profile.gpa == 3.9

    def test_free_stays_free_and_cannot_self_promote(self, client):
        """Client-sent 'premium' is ignored on both PUT and POST upsert."""
        profile = _make_profile(subscription_tier="free")
        _db_returning(profile)

        resp = client.put("/profiles", json={"subscription_tier": "premium"})
        assert resp.status_code == 200
        assert profile.subscription_tier == "free"

        resp = client.post(
            "/profiles",
            json={"subscription_tier": "premium", "disciplines": ["Biology"]},
        )
        assert resp.status_code == 200
        assert profile.subscription_tier == "free"

    def test_premium_cannot_be_client_downgraded(self, client):
        """Client-sent 'free' must not downgrade an existing Premium profile."""
        profile = _make_profile(subscription_tier="premium")
        _db_returning(profile)

        resp = client.put("/profiles", json={"subscription_tier": "free"})
        assert resp.status_code == 200
        assert profile.subscription_tier == "premium"

"""Tests for Phase 14: Consumer Compliance, Disclaimers & Account Deletion.

Covers:
  1. Self-serve account deletion endpoint (DELETE /api/v1/profile/me)
  2. Stripe subscription cancellation during deletion
  3. Cascading record deletion (user_scholarships, budgets, reports, profile)
  4. Supabase Auth user purge (graceful when not configured)
  5. Profile-not-found edge case
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.middleware.auth import DEMO_USER_ID
from app.models.models import Profile, ScholarshipReport, StudentCollegeBudget, UserScholarship
from app.services.profile_service import delete_account


# ---------------------------------------------------------------------------
# Fixtures
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


def _make_profile(**kwargs):
    defaults = {
        "id": DEMO_USER_ID,
        "email": "student@grantrx.local",
        "full_name": "Test Student",
        "subscription_tier": "premium",
        "stripe_customer_id": "cus_test123",
        "stripe_subscription_id": "sub_test123",
        "stripe_subscription_status": "active",
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _build_db(profile=None):
    """Build a mock DB session that tracks delete() calls per model."""
    db = MagicMock()

    # Track delete calls per model class
    delete_calls: dict = {}

    def query_side_effect(arg):
        q = MagicMock()
        if arg is Profile:
            q.filter.return_value.first.return_value = profile
        else:
            q.filter.return_value.first.return_value = None

        # Track delete calls
        def make_delete(model):
            def _delete(synchronize_session=False):
                delete_calls[model.__name__] = True
            return _delete

        q.filter.return_value.delete = make_delete(arg)
        return q

    db.query.side_effect = query_side_effect
    db._delete_calls = delete_calls
    return db


# ===========================================================================
# 1. Account Deletion Endpoint
# ===========================================================================


class TestAccountDeletionEndpoint:
    """DELETE /api/v1/profile/me — self-serve account deletion."""

    def test_delete_returns_success_message(self, client):
        """Successful deletion returns the expected status/message."""
        profile = _make_profile()
        db = _build_db(profile=profile)
        _override_db(db)

        with patch(
            "app.services.profile_service._cancel_stripe_subscription",
            return_value=True,
        ), patch(
            "app.services.profile_service._delete_supabase_user",
            return_value=False,
        ):
            resp = client.delete("/api/v1/profile/me")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "deleted"
        assert "permanently purged" in body["message"].lower()
        assert body["stripe_canceled"] is True
        db.commit.assert_called_once()

    def test_delete_returns_404_when_profile_missing(self, client):
        """No profile found returns 404."""
        db = _build_db(profile=None)
        _override_db(db)

        resp = client.delete("/api/v1/profile/me")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_delete_cancels_active_stripe_subscription(self, client):
        """Active subscription triggers Stripe cancellation."""
        profile = _make_profile(
            stripe_subscription_id="sub_active123",
            stripe_subscription_status="active",
        )
        db = _build_db(profile=profile)
        _override_db(db)

        with patch(
            "app.services.profile_service._cancel_stripe_subscription",
            return_value=True,
        ) as mock_cancel, patch(
            "app.services.profile_service._delete_supabase_user",
            return_value=False,
        ):
            resp = client.delete("/api/v1/profile/me")

        assert resp.status_code == 200
        mock_cancel.assert_called_once_with("sub_active123")

    def test_delete_skips_stripe_for_free_user(self, client):
        """Free user without subscription does not call Stripe."""
        profile = _make_profile(
            subscription_tier="free",
            stripe_subscription_id=None,
            stripe_subscription_status=None,
        )
        db = _build_db(profile=profile)
        _override_db(db)

        with patch(
            "app.services.profile_service._cancel_stripe_subscription",
            return_value=False,
        ) as mock_cancel, patch(
            "app.services.profile_service._delete_supabase_user",
            return_value=False,
        ):
            resp = client.delete("/api/v1/profile/me")

        assert resp.status_code == 200
        mock_cancel.assert_not_called()
        assert resp.json()["stripe_canceled"] is False

    def test_delete_skips_stripe_for_canceled_subscription(self, client):
        """Canceled subscription status does not trigger Stripe cancellation."""
        profile = _make_profile(
            stripe_subscription_id="sub_canceled",
            stripe_subscription_status="canceled",
        )
        db = _build_db(profile=profile)
        _override_db(db)

        with patch(
            "app.services.profile_service._cancel_stripe_subscription",
        ) as mock_cancel, patch(
            "app.services.profile_service._delete_supabase_user",
            return_value=False,
        ):
            resp = client.delete("/api/v1/profile/me")

        assert resp.status_code == 200
        mock_cancel.assert_not_called()

    def test_delete_cascades_to_all_user_tables(self, client):
        """Deletion removes user_scholarships, budgets, reports, and profile."""
        profile = _make_profile()
        db = _build_db(profile=profile)
        _override_db(db)

        with patch(
            "app.services.profile_service._cancel_stripe_subscription",
            return_value=False,
        ), patch(
            "app.services.profile_service._delete_supabase_user",
            return_value=False,
        ):
            client.delete("/api/v1/profile/me")

        # Verify all user-owned tables had delete() called
        assert "UserScholarship" in db._delete_calls
        assert "StudentCollegeBudget" in db._delete_calls
        assert "ScholarshipReport" in db._delete_calls
        assert "Profile" in db._delete_calls

    def test_delete_purges_supabase_user_when_configured(self, client):
        """Supabase user deletion is attempted when env vars are set."""
        profile = _make_profile()
        db = _build_db(profile=profile)
        _override_db(db)

        with patch(
            "app.services.profile_service._cancel_stripe_subscription",
            return_value=False,
        ), patch(
            "app.services.profile_service._delete_supabase_user",
            return_value=True,
        ) as mock_supabase:
            resp = client.delete("/api/v1/profile/me")

        assert resp.status_code == 200
        assert resp.json()["supabase_deleted"] is True
        mock_supabase.assert_called_once_with(str(DEMO_USER_ID))

    def test_delete_succeeds_even_if_stripe_fails(self, client):
        """Local data is still deleted even if Stripe cancellation fails."""
        profile = _make_profile()
        db = _build_db(profile=profile)
        _override_db(db)

        with patch(
            "app.services.profile_service._cancel_stripe_subscription",
            return_value=False,
        ), patch(
            "app.services.profile_service._delete_supabase_user",
            return_value=False,
        ):
            resp = client.delete("/api/v1/profile/me")

        assert resp.status_code == 200
        assert resp.json()["stripe_canceled"] is False
        db.commit.assert_called_once()


# ===========================================================================
# 2. profile_service unit tests
# ===========================================================================


class TestProfileServiceDeleteAccount:
    """Unit tests for delete_account in profile_service."""

    def test_delete_account_returns_not_found_for_missing_profile(self):
        db = _build_db(profile=None)
        result = delete_account(db, "nonexistent-user-id")
        assert result["status"] == "not_found"
        db.commit.assert_not_called()

    def test_delete_account_cancels_trialing_subscription(self):
        """Trialing subscriptions are also canceled."""
        profile = _make_profile(
            stripe_subscription_id="sub_trial",
            stripe_subscription_status="trialing",
        )
        db = _build_db(profile=profile)

        with patch(
            "app.services.profile_service._cancel_stripe_subscription",
            return_value=True,
        ) as mock_cancel, patch(
            "app.services.profile_service._delete_supabase_user",
            return_value=False,
        ):
            result = delete_account(db, str(DEMO_USER_ID))

        mock_cancel.assert_called_once_with("sub_trial")
        assert result["stripe_canceled"] is True

    def test_delete_account_commits_transaction(self):
        profile = _make_profile()
        db = _build_db(profile=profile)

        with patch(
            "app.services.profile_service._cancel_stripe_subscription",
            return_value=False,
        ), patch(
            "app.services.profile_service._delete_supabase_user",
            return_value=False,
        ):
            delete_account(db, str(DEMO_USER_ID))

        db.commit.assert_called_once()


# ===========================================================================
# 3. Stripe cancellation helper
# ===========================================================================


class TestStripeCancellationHelper:
    """Tests for _cancel_stripe_subscription helper."""

    def test_returns_false_without_api_key(self):
        from app.services.profile_service import _cancel_stripe_subscription

        with patch("app.services.profile_service.stripe", create=True):
            import app.services.profile_service as svc
            with patch.object(svc, "_cancel_stripe_subscription", wraps=svc._cancel_stripe_subscription):
                # Simulate stripe not having api_key
                import sys
                mock_stripe = MagicMock()
                mock_stripe.api_key = ""
                sys.modules["stripe"] = mock_stripe
                try:
                    result = _cancel_stripe_subscription("sub_123")
                finally:
                    sys.modules.pop("stripe", None)
        assert result is False

    def test_returns_true_on_successful_cancellation(self):
        from app.services.profile_service import _cancel_stripe_subscription

        import sys
        mock_stripe = MagicMock()
        mock_stripe.api_key = "sk_test_x"
        mock_stripe.Subscription.delete = MagicMock()
        sys.modules["stripe"] = mock_stripe

        try:
            result = _cancel_stripe_subscription("sub_123")
        finally:
            sys.modules.pop("stripe", None)

        assert result is True
        mock_stripe.Subscription.delete.assert_called_once_with("sub_123")

    def test_returns_false_on_stripe_exception(self):
        from app.services.profile_service import _cancel_stripe_subscription

        import sys
        mock_stripe = MagicMock()
        mock_stripe.api_key = "sk_test_x"
        mock_stripe.Subscription.delete.side_effect = Exception("Stripe API error")
        sys.modules["stripe"] = mock_stripe

        try:
            result = _cancel_stripe_subscription("sub_123")
        finally:
            sys.modules.pop("stripe", None)

        assert result is False

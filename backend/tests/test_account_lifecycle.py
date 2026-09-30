"""Regression tests for fail-safe account deletion ordering."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.profile_service import SubscriptionCancellationError, delete_account


class _Profile:
    id = "user-1"
    stripe_subscription_id = "sub_123"
    stripe_subscription_status = "active"


def _db_with_profile():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = _Profile()
    return db


def test_active_subscription_failure_aborts_before_database_deletion():
    db = _db_with_profile()
    with patch("app.services.profile_service._cancel_stripe_subscription", return_value=False), \
         patch("app.services.profile_service._delete_supabase_user") as delete_auth:
        with pytest.raises(SubscriptionCancellationError):
            delete_account(db, "user-1")
    db.commit.assert_not_called()
    delete_auth.assert_not_called()


def test_supabase_deletion_occurs_only_after_database_commit():
    db = _db_with_profile()
    events = []
    db.commit.side_effect = lambda: events.append("commit")
    with patch("app.services.profile_service._cancel_stripe_subscription", return_value=True), \
         patch("app.services.profile_service._delete_supabase_user", side_effect=lambda _uid: events.append("auth") or True):
        result = delete_account(db, "user-1")
    assert events == ["commit", "auth"]
    assert result["status"] == "deleted"
    assert result["auth_cleanup_required"] is False


def test_supabase_failure_is_reported_after_personal_data_commit():
    db = _db_with_profile()
    with patch("app.services.profile_service._cancel_stripe_subscription", return_value=True), \
         patch("app.services.profile_service._delete_supabase_user", return_value=False):
        result = delete_account(db, "user-1")
    db.commit.assert_called_once()
    assert result["status"] == "deleted_auth_cleanup_required"
    assert result["auth_cleanup_required"] is True

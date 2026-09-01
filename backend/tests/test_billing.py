"""Unit tests for Stripe billing: checkout session creation, webhook handling,
and the free-tier paywall (search quota + Kanban tracking limit).

Stripe API calls are fully mocked — no network requests are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.middleware.tier_guard import (
    FREE_ACTIVE_TRACKING_LIMIT,
    FREE_SEARCH_LIMIT,
    consume_search,
)
from app.services import stripe_service
from app.services.stripe_service import (
    create_checkout_session,
    handle_webhook_event,
    verify_webhook_signature,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_profile(**kwargs):
    defaults = {
        "id": "00000000-0000-0000-0000-000000000001",
        "email": "student@grantrx.local",
        "subscription_tier": "free",
        "searches_used_this_week": 0,
        "search_cycle_reset_at": None,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "stripe_subscription_status": None,
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# Tests: create_checkout_session
# ---------------------------------------------------------------------------

class TestCreateCheckoutSession:
    def test_raises_without_api_key(self):
        """Missing STRIPE_SECRET_KEY should raise RuntimeError."""
        with patch.object(stripe_service.stripe, "api_key", ""):
            with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY"):
                create_checkout_session(
                    user_id="user-1",
                    email="a@b.com",
                    plan="monthly",
                    success_url="https://app/success",
                    cancel_url="https://app/cancel",
                )

    def test_raises_for_unknown_plan(self):
        """An unknown plan should raise ValueError."""
        with patch.object(stripe_service.stripe, "api_key", "sk_test_x"):
            with pytest.raises(ValueError, match="Unknown plan"):
                create_checkout_session(
                    user_id="user-1",
                    email="a@b.com",
                    plan="lifetime",
                    success_url="https://app/success",
                    cancel_url="https://app/cancel",
                )

    def test_monthly_plan_maps_to_monthly_price(self):
        """plan='monthly' should use the STRIPE_PRICE_MONTHLY price ID."""
        mock_session = MagicMock(url="https://checkout.stripe.com/x", id="cs_123")
        with (
            patch.object(stripe_service.stripe, "api_key", "sk_test_x"),
            patch.dict(stripe_service.PLAN_PRICES, {"monthly": "price_monthly_9", "annual": "price_annual_79"}),
            patch.object(
                stripe_service.stripe.checkout.Session, "create", return_value=mock_session
            ) as mock_create,
        ):
            create_checkout_session(
                user_id="user-1",
                email="a@b.com",
                plan="monthly",
                success_url="https://app/success",
                cancel_url="https://app/cancel",
            )
            params = mock_create.call_args.kwargs
            assert params["mode"] == "subscription"
            assert params["line_items"] == [{"price": "price_monthly_9", "quantity": 1}]

    def test_annual_plan_maps_to_annual_price(self):
        """plan='annual' should use the STRIPE_PRICE_ANNUAL price ID."""
        mock_session = MagicMock(url="https://checkout.stripe.com/x", id="cs_123")
        with (
            patch.object(stripe_service.stripe, "api_key", "sk_test_x"),
            patch.dict(stripe_service.PLAN_PRICES, {"monthly": "price_monthly_9", "annual": "price_annual_79"}),
            patch.object(
                stripe_service.stripe.checkout.Session, "create", return_value=mock_session
            ) as mock_create,
        ):
            create_checkout_session(
                user_id="user-1",
                email="a@b.com",
                plan="annual",
                success_url="https://app/success",
                cancel_url="https://app/cancel",
            )
            params = mock_create.call_args.kwargs
            assert params["line_items"] == [{"price": "price_annual_79", "quantity": 1}]

    def test_customer_email_prefill_for_stripe_link(self):
        """customer_email should be passed for Stripe Link identification."""
        mock_session = MagicMock(url="https://checkout.stripe.com/x", id="cs_123")
        with (
            patch.object(stripe_service.stripe, "api_key", "sk_test_x"),
            patch.dict(stripe_service.PLAN_PRICES, {"monthly": "price_m", "annual": "price_a"}),
            patch.object(
                stripe_service.stripe.checkout.Session, "create", return_value=mock_session
            ) as mock_create,
        ):
            create_checkout_session(
                user_id="user-1",
                email="link-user@grantrx.local",
                plan="monthly",
                success_url="https://app/success",
                cancel_url="https://app/cancel",
            )
            params = mock_create.call_args.kwargs
            assert params["customer_email"] == "link-user@grantrx.local"

    def test_no_customer_email_when_missing(self):
        """customer_email should be omitted when email is None."""
        mock_session = MagicMock(url="https://checkout.stripe.com/x", id="cs_123")
        with (
            patch.object(stripe_service.stripe, "api_key", "sk_test_x"),
            patch.dict(stripe_service.PLAN_PRICES, {"monthly": "price_m", "annual": "price_a"}),
            patch.object(
                stripe_service.stripe.checkout.Session, "create", return_value=mock_session
            ) as mock_create,
        ):
            create_checkout_session(
                user_id="user-1",
                email=None,
                plan="monthly",
                success_url="https://app/success",
                cancel_url="https://app/cancel",
            )
            params = mock_create.call_args.kwargs
            assert "customer_email" not in params

    def test_dynamic_payment_methods_no_explicit_types(self):
        """payment_method_types must be omitted so Checkout uses dynamic
        payment methods (Apple Pay, Google Pay, Link) from the Dashboard."""
        mock_session = MagicMock(url="https://checkout.stripe.com/x", id="cs_123")
        with (
            patch.object(stripe_service.stripe, "api_key", "sk_test_x"),
            patch.dict(stripe_service.PLAN_PRICES, {"monthly": "price_m", "annual": "price_a"}),
            patch.object(
                stripe_service.stripe.checkout.Session, "create", return_value=mock_session
            ) as mock_create,
        ):
            create_checkout_session(
                user_id="user-1",
                email="a@b.com",
                plan="monthly",
                success_url="https://app/success",
                cancel_url="https://app/cancel",
            )
            params = mock_create.call_args.kwargs
            assert "payment_method_types" not in params
            assert "automatic_payment_methods" not in params  # PaymentIntent-only param

    def test_client_reference_and_metadata(self):
        """client_reference_id and metadata must identify the user for webhooks."""
        mock_session = MagicMock(url="https://checkout.stripe.com/x", id="cs_123")
        with (
            patch.object(stripe_service.stripe, "api_key", "sk_test_x"),
            patch.dict(stripe_service.PLAN_PRICES, {"monthly": "price_m", "annual": "price_a"}),
            patch.object(
                stripe_service.stripe.checkout.Session, "create", return_value=mock_session
            ) as mock_create,
        ):
            create_checkout_session(
                user_id="user-42",
                email="a@b.com",
                plan="annual",
                success_url="https://app/success",
                cancel_url="https://app/cancel",
            )
            params = mock_create.call_args.kwargs
            assert params["client_reference_id"] == "user-42"
            assert params["metadata"]["user_id"] == "user-42"
            assert params["metadata"]["plan_type"] == "annual"
            # Metadata must propagate to the Subscription for webhook resolution
            assert params["subscription_data"]["metadata"]["user_id"] == "user-42"


# ---------------------------------------------------------------------------
# Tests: webhook signature verification
# ---------------------------------------------------------------------------

class TestWebhookSignature:
    def test_raises_without_webhook_secret(self):
        """Missing STRIPE_WEBHOOK_SECRET should raise RuntimeError."""
        with patch.object(stripe_service, "WEBHOOK_SECRET", ""):
            with pytest.raises(RuntimeError, match="STRIPE_WEBHOOK_SECRET"):
                verify_webhook_signature(b"{}", "sig_header")

    def test_valid_signature_constructs_event(self):
        """A valid signature should return the constructed event."""
        fake_event = {"type": "customer.subscription.created", "data": {"object": {}}}
        with (
            patch.object(stripe_service, "WEBHOOK_SECRET", "whsec_test"),
            patch.object(
                stripe_service.stripe.Webhook, "construct_event", return_value=fake_event
            ) as mock_construct,
        ):
            event = verify_webhook_signature(b'{"a":1}', "sig_header")
            assert event == fake_event
            mock_construct.assert_called_once_with(b'{"a":1}', "sig_header", "whsec_test")

    def test_invalid_signature_propagates_error(self):
        """An invalid signature should raise (caught as 400 by the endpoint)."""
        with (
            patch.object(stripe_service, "WEBHOOK_SECRET", "whsec_test"),
            patch.object(
                stripe_service.stripe.Webhook,
                "construct_event",
                side_effect=ValueError("Invalid signature"),
            ),
        ):
            with pytest.raises(ValueError):
                verify_webhook_signature(b"{}", "bad_sig")


# ---------------------------------------------------------------------------
# Tests: webhook event handling
# ---------------------------------------------------------------------------

class TestWebhookEvents:
    def test_subscription_created_grants_premium(self):
        """An active subscription.created event should set premium tier."""
        profile = _make_profile()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = profile

        event = {
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_123",
                    "customer": "cus_456",
                    "status": "active",
                    "metadata": {"user_id": str(profile.id)},
                }
            },
        }
        result = handle_webhook_event(db, event)
        assert result["status"] == "updated"
        assert profile.subscription_tier == "premium"
        assert profile.stripe_customer_id == "cus_456"
        assert profile.stripe_subscription_id == "sub_123"
        db.commit.assert_called_once()

    def test_subscription_deleted_downgrades_to_free(self):
        """A subscription.deleted event should downgrade to free tier."""
        profile = _make_profile(subscription_tier="premium", stripe_customer_id="cus_456")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = profile

        event = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_123",
                    "customer": "cus_456",
                }
            },
        }
        result = handle_webhook_event(db, event)
        assert result["status"] == "downgraded"
        assert profile.subscription_tier == "free"
        assert profile.stripe_subscription_status == "canceled"

    def test_unknown_event_ignored(self):
        """Unhandled event types should be safely ignored."""
        db = MagicMock()
        event = {"type": "charge.refunded", "data": {"object": {}}}
        result = handle_webhook_event(db, event)
        assert result["status"] == "ignored"
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: paywall rate-limiting (search quota)
# ---------------------------------------------------------------------------

class TestSearchQuotaPaywall:
    def test_premium_user_never_debited(self):
        """Premium users bypass the quota entirely."""
        profile = _make_profile(subscription_tier="premium", searches_used_this_week=999)
        db = MagicMock()
        consume_search(profile, db)  # should not raise
        assert profile.searches_used_this_week == 999  # unchanged

    def test_free_user_debited_below_limit(self):
        """Free users under the limit get their counter incremented."""
        profile = _make_profile(searches_used_this_week=4)
        db = MagicMock()
        consume_search(profile, db)
        assert profile.searches_used_this_week == 5
        db.commit.assert_called_once()

    def test_free_user_blocked_at_limit_with_402(self):
        """The 11th search must raise HTTP 402 with PAYWALL_REQUIRED payload."""
        profile = _make_profile(searches_used_this_week=FREE_SEARCH_LIMIT)
        db = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            consume_search(profile, db)
        assert exc_info.value.status_code == 402
        detail = exc_info.value.detail
        assert detail["detail"] == "PAYWALL_REQUIRED"
        assert detail["feature"] == "keyword_search"
        assert detail["upgrade_url"] == "/billing"

    def test_free_tracking_limit_constant(self):
        """The Kanban free-tier limit should match the advertised '3 active apps'."""
        assert FREE_ACTIVE_TRACKING_LIMIT == 3

"""Tests for Phase 13: Customer Support Operations & Billing Portal.

Covers:
  1. Stripe Customer Portal session creation endpoint
  2. Scholarship issue reporting endpoint (crowdsourced)
  3. Transactional email service (welcome, receipt, dunning)
  4. Webhook handler integration with email notifications
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.middleware.auth import DEMO_USER_ID
from app.models.models import Profile, Scholarship, ScholarshipReport
from app.services import email_service
from app.services.stripe_service import (
    create_billing_portal_session,
    handle_webhook_event,
)


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
        "searches_used_this_week": 0,
        "search_cycle_reset_at": None,
        "feed_token": "test-feed-token",
        "terms_accepted_at": None,
        "privacy_accepted_at": None,
        "marketing_opt_in": False,
        "marketing_opt_in_at": None,
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
        "deadline": "2026-03-15",
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


def _build_db(profile=None, scholarship_lookup=None):
    """Build a mock DB session for the portal and report endpoints."""
    db = MagicMock()

    def query_side_effect(arg):
        q = MagicMock()
        if arg is Profile:
            q.filter.return_value.first.return_value = profile
        elif arg is Scholarship:
            q.filter.return_value.first.return_value = scholarship_lookup
        else:
            q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = query_side_effect
    return db


# ===========================================================================
# 1. Stripe Customer Portal Endpoint
# ===========================================================================


class TestBillingPortal:
    """POST /api/v1/billing/portal — Stripe Customer Portal session."""

    def test_portal_returns_url_for_premium_user(self, client):
        """Premium user with stripe_customer_id gets a portal URL."""
        profile = _make_profile()
        db = _build_db(profile=profile)
        _override_db(db)

        mock_session = MagicMock(url="https://billing.stripe.com/session/abc123")
        with patch(
            "app.main.create_billing_portal_session",
            return_value=mock_session,
        ):
            resp = client.post("/api/v1/billing/portal")

        assert resp.status_code == 200
        body = resp.json()
        assert "url" in body
        assert body["url"] == "https://billing.stripe.com/session/abc123"

    def test_portal_returns_404_without_profile(self, client):
        """No profile found returns 404."""
        db = _build_db(profile=None)
        _override_db(db)

        resp = client.post("/api/v1/billing/portal")
        assert resp.status_code == 404

    def test_portal_returns_400_without_stripe_customer_id(self, client):
        """Free user without stripe_customer_id returns 400."""
        profile = _make_profile(
            subscription_tier="free",
            stripe_customer_id=None,
        )
        db = _build_db(profile=profile)
        _override_db(db)

        resp = client.post("/api/v1/billing/portal")
        assert resp.status_code == 400
        assert "No Stripe customer" in resp.json()["detail"]

    def test_portal_returns_503_without_stripe_api_key(self, client):
        """Stripe API not configured returns 503."""
        profile = _make_profile()
        db = _build_db(profile=profile)
        _override_db(db)

        with patch(
            "app.main.create_billing_portal_session",
            side_effect=RuntimeError("STRIPE_SECRET_KEY not configured"),
        ):
            resp = client.post("/api/v1/billing/portal")
        assert resp.status_code == 503


class TestCreateBillingPortalSession:
    """Unit tests for create_billing_portal_session in stripe_service."""

    def test_raises_without_api_key(self):
        with patch.object(
            __import__("app.services.stripe_service", fromlist=["stripe"]).stripe,
            "api_key",
            "",
        ):
            with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY"):
                create_billing_portal_session(customer_id="cus_123")

    def test_creates_session_with_correct_params(self):
        import app.services.stripe_service as svc

        mock_session = MagicMock(url="https://billing.stripe.com/x")
        with patch.object(svc.stripe, "api_key", "sk_test_x"):
            with patch.object(
                svc.stripe.billing_portal.Session,
                "create",
                return_value=mock_session,
            ) as mock_create:
                result = create_billing_portal_session(
                    customer_id="cus_123",
                    return_url="https://app.example.com",
                )

        assert result.url == "https://billing.stripe.com/x"
        mock_create.assert_called_once_with(
            customer="cus_123",
            return_url="https://app.example.com",
        )


# ===========================================================================
# 2. Scholarship Issue Reporting
# ===========================================================================


class TestScholarshipReport:
    """POST /api/v1/scholarships/{id}/report — crowdsourced issue reporting."""

    def test_report_creates_record(self, client):
        """Valid report creates a scholarship_reports record."""
        scholarship = _make_scholarship()
        db = _build_db(scholarship_lookup=scholarship)
        _override_db(db)

        mock_report = MagicMock()
        mock_report.id = uuid4()
        mock_report.scholarship_id = scholarship.id
        mock_report.reason = "broken_link"
        mock_report.notes = "Page returns 404"
        mock_report.status = "open"
        mock_report.created_at = datetime.utcnow()

        with patch("app.main.ScholarshipReport", return_value=mock_report):
            resp = client.post(
                f"/api/v1/scholarships/{scholarship.id}/report",
                json={"reason": "broken_link", "notes": "Page returns 404"},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["reason"] == "broken_link"
        assert body["notes"] == "Page returns 404"
        assert body["status"] == "open"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_report_without_notes(self, client):
        """Report without notes is accepted."""
        scholarship = _make_scholarship()
        db = _build_db(scholarship_lookup=scholarship)
        _override_db(db)

        mock_report = MagicMock()
        mock_report.id = uuid4()
        mock_report.scholarship_id = scholarship.id
        mock_report.reason = "expired"
        mock_report.notes = None
        mock_report.status = "open"
        mock_report.created_at = datetime.utcnow()

        with patch("app.main.ScholarshipReport", return_value=mock_report):
            resp = client.post(
                f"/api/v1/scholarships/{scholarship.id}/report",
                json={"reason": "expired"},
            )
        assert resp.status_code == 201
        assert resp.json()["reason"] == "expired"

    def test_report_rejects_invalid_reason(self, client):
        """Invalid reason value returns 422 validation error."""
        scholarship = _make_scholarship()
        db = _build_db(scholarship_lookup=scholarship)
        _override_db(db)

        resp = client.post(
            f"/api/v1/scholarships/{scholarship.id}/report",
            json={"reason": "spam"},
        )
        assert resp.status_code == 422

    def test_report_returns_404_for_unknown_scholarship(self, client):
        """Reporting a non-existent scholarship returns 404."""
        db = _build_db(scholarship_lookup=None)
        _override_db(db)

        resp = client.post(
            f"/api/v1/scholarships/{uuid4()}/report",
            json={"reason": "broken_link"},
        )
        assert resp.status_code == 404

    def test_report_accepts_all_valid_reasons(self, client):
        """All three valid reason values are accepted."""
        for reason in ("broken_link", "inaccurate_deadline", "expired"):
            scholarship = _make_scholarship()
            db = _build_db(scholarship_lookup=scholarship)
            _override_db(db)

            mock_report = MagicMock()
            mock_report.id = uuid4()
            mock_report.scholarship_id = scholarship.id
            mock_report.reason = reason
            mock_report.notes = None
            mock_report.status = "open"
            mock_report.created_at = datetime.utcnow()

            with patch("app.main.ScholarshipReport", return_value=mock_report):
                resp = client.post(
                    f"/api/v1/scholarships/{scholarship.id}/report",
                    json={"reason": reason},
                )
            assert resp.status_code == 201
            assert resp.json()["reason"] == reason


# ===========================================================================
# 3. Transactional Email Service
# ===========================================================================


class TestEmailService:
    """Tests for welcome_email, payment_receipt, and dunning_notification."""

    def test_welcome_email_returns_false_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            result = email_service.welcome_email(
                to="test@example.com",
                name="Jane Doe",
            )
        assert result is False

    def test_welcome_email_returns_false_without_resend_package(self):
        """When resend is not installed, returns False gracefully."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "resend":
                raise ImportError("No module named 'resend'")
            return original_import(name, *args, **kwargs)

        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test"}):
            with patch.object(builtins, "__import__", side_effect=mock_import):
                result = email_service.welcome_email(
                    to="test@example.com",
                    name="Jane",
                )
        assert result is False

    def test_welcome_email_sends_via_resend(self):
        """When resend is configured, welcome_email sends successfully."""
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock(return_value={"id": "email-123"})

        import sys
        original_resend = sys.modules.get("resend")
        sys.modules["resend"] = mock_resend

        try:
            with patch.dict(os.environ, {"RESEND_API_KEY": "re_test"}):
                result = email_service.welcome_email(
                    to="jane@example.com",
                    name="Jane Doe",
                )
            assert result is True
            mock_resend.Emails.send.assert_called_once()
            call_args = mock_resend.Emails.send.call_args[0][0]
            assert call_args["to"] == "jane@example.com"
            assert "Welcome" in call_args["subject"]
            assert "Jane" in call_args["text"]
        finally:
            if original_resend is not None:
                sys.modules["resend"] = original_resend
            else:
                sys.modules.pop("resend", None)

    def test_payment_receipt_sends_via_resend(self):
        """payment_receipt sends with amount and plan info."""
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock(return_value={"id": "email-456"})

        import sys
        sys.modules["resend"] = mock_resend

        try:
            with patch.dict(os.environ, {"RESEND_API_KEY": "re_test"}):
                result = email_service.payment_receipt(
                    to="john@example.com",
                    name="John Smith",
                    amount="$9.00",
                    plan="monthly",
                    invoice_url="https://invoice.stripe.com/123",
                )
            assert result is True
            call_args = mock_resend.Emails.send.call_args[0][0]
            assert "$9.00" in call_args["text"]
            assert "monthly" in call_args["text"]
            assert "https://invoice.stripe.com/123" in call_args["text"]
        finally:
            sys.modules.pop("resend", None)

    def test_dunning_notification_sends_via_resend(self):
        """dunning_notification sends with retry info."""
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock(return_value={"id": "email-789"})

        import sys
        sys.modules["resend"] = mock_resend

        try:
            with patch.dict(os.environ, {"RESEND_API_KEY": "re_test"}):
                result = email_service.dunning_notification(
                    to="jane@example.com",
                    name="Jane",
                    amount="$9.00",
                    attempt=2,
                    next_attempt="2026-09-10",
                )
            assert result is True
            call_args = mock_resend.Emails.send.call_args[0][0]
            assert "payment failed" in call_args["subject"].lower()
            assert "attempt #2" in call_args["text"]
            assert "2026-09-10" in call_args["text"]
        finally:
            sys.modules.pop("resend", None)

    def test_welcome_email_uses_first_name(self):
        """Welcome email uses the first name from full_name."""
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock(return_value={"id": "e"})

        import sys
        sys.modules["resend"] = mock_resend

        try:
            with patch.dict(os.environ, {"RESEND_API_KEY": "re_test"}):
                email_service.welcome_email(
                    to="test@example.com",
                    name="Alex Johnson-Smith",
                )
            text = mock_resend.Emails.send.call_args[0][0]["text"]
            assert "Hi Alex," in text
        finally:
            sys.modules.pop("resend", None)

    def test_welcome_email_handles_none_name(self):
        """Welcome email uses 'there' when name is None."""
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock(return_value={"id": "e"})

        import sys
        sys.modules["resend"] = mock_resend

        try:
            with patch.dict(os.environ, {"RESEND_API_KEY": "re_test"}):
                email_service.welcome_email(to="test@example.com", name=None)
            text = mock_resend.Emails.send.call_args[0][0]["text"]
            assert "Hi there," in text
        finally:
            sys.modules.pop("resend", None)


# ===========================================================================
# 4. Webhook Email Integration
# ===========================================================================


class TestWebhookEmailIntegration:
    """Verify that webhook handlers trigger email notifications."""

    def test_invoice_paid_sends_receipt_email(self):
        """_on_invoice_paid sends a payment receipt email."""
        from app.services.stripe_service import _on_invoice_paid

        profile = _make_profile(email="john@example.com")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = profile

        invoice = {
            "billing_reason": "subscription_cycle",
            "customer": "cus_test123",
            "subscription": "sub_test123",
            "total": 900,
            "currency": "usd",
            "hosted_invoice_url": "https://invoice.stripe.com/abc",
        }

        with patch("app.services.email_service.payment_receipt") as mock_receipt:
            result = _on_invoice_paid(db, invoice)

        assert result["status"] == "renewed"
        mock_receipt.assert_called_once()
        call_kwargs = mock_receipt.call_args[1]
        assert call_kwargs["to"] == "john@example.com"
        assert call_kwargs["amount"] == "$9.00"
        assert call_kwargs["plan"] == "Premium"

    def test_invoice_paid_skips_email_without_profile_email(self):
        """_on_invoice_paid does not send email if profile has no email."""
        from app.services.stripe_service import _on_invoice_paid

        profile = _make_profile(email=None)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = profile

        invoice = {
            "billing_reason": "subscription_cycle",
            "customer": "cus_test123",
            "subscription": "sub_test123",
            "total": 900,
            "currency": "usd",
        }

        with patch("app.services.email_service.payment_receipt") as mock_receipt:
            result = _on_invoice_paid(db, invoice)

        assert result["status"] == "renewed"
        mock_receipt.assert_not_called()

    def test_invoice_failed_sends_dunning_email(self):
        """_on_invoice_failed sends a dunning notification."""
        from app.services.stripe_service import _on_invoice_failed

        profile = _make_profile(email="jane@example.com")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = profile

        invoice = {
            "customer": "cus_test123",
            "total": 900,
            "currency": "usd",
            "attempt_count": 1,
            "next_payment_attempt": 1696118400,
            "hosted_invoice_url": "https://invoice.stripe.com/xyz",
        }

        with patch("app.services.email_service.dunning_notification") as mock_dunning:
            result = _on_invoice_failed(db, invoice)

        assert result["status"] == "dunning_sent"
        mock_dunning.assert_called_once()
        call_kwargs = mock_dunning.call_args[1]
        assert call_kwargs["to"] == "jane@example.com"
        assert call_kwargs["amount"] == "$9.00"
        assert call_kwargs["attempt"] == 1

    def test_handle_webhook_routes_invoice_failed(self):
        """handle_webhook_event routes invoice.payment_failed to _on_invoice_failed."""
        event = {
            "type": "invoice.payment_failed",
            "data": {"object": {"customer": "cus_test123"}},
        }
        db = MagicMock()
        profile = _make_profile()
        db.query.return_value.filter.return_value.first.return_value = profile

        with patch(
            "app.services.stripe_service._on_invoice_failed",
            return_value={"status": "dunning_sent"},
        ) as mock_failed:
            result = handle_webhook_event(db, event)

        assert result["status"] == "dunning_sent"
        mock_failed.assert_called_once()

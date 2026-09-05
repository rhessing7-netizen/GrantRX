"""Stripe subscription billing service.

Handles:
- Creating Checkout Sessions for monthly ($9/mo) and annual ($79/yr) Premium.
- Processing webhook events to toggle `subscription_tier` and store
  Stripe customer/subscription IDs on the profile.

Required env vars:
  STRIPE_SECRET_KEY      - sk_test_... or sk_live_...
  STRIPE_WEBHOOK_SECRET  - whsec_... (from Stripe Dashboard webhook endpoint)
  STRIPE_PRICE_MONTHLY   - price_... (Stripe Price ID for monthly plan)
  STRIPE_PRICE_ANNUAL    - price_... (Stripe Price ID for annual plan)
  APP_BASE_URL           - e.g. https://api.grantrx.app (for success/cancel defaults)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import stripe
from sqlalchemy.orm import Session

from ..models.models import Profile

logger = logging.getLogger(__name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

PRICE_MONTHLY = os.getenv("STRIPE_PRICE_MONTHLY", "")
PRICE_ANNUAL = os.getenv("STRIPE_PRICE_ANNUAL", "")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")

PLAN_PRICES = {
    "monthly": PRICE_MONTHLY,
    "annual": PRICE_ANNUAL,
}


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


def create_checkout_session(
    user_id: str,
    email: Optional[str],
    plan: str,
    success_url: str,
    cancel_url: str,
) -> stripe.checkout.Session:
    """Create a Stripe Checkout Session for a Premium subscription.

    Dynamic payment methods (Apple Pay, Google Pay, Stripe Link, cards) are
    enabled automatically because `payment_method_types` is intentionally
    omitted — Checkout then uses the payment methods configured in the
    Stripe Dashboard. (Note: `automatic_payment_methods` is a PaymentIntent
    parameter and is not accepted by Checkout Sessions; omitting
    `payment_method_types` is the Checkout equivalent.)

    `customer_email` prefill enables Stripe Link 1-click checkout
    identification. In subscription mode Stripe always creates a Customer,
    so `customer_creation` is not needed (it is only valid in payment mode).
    """
    if not stripe.api_key:
        raise RuntimeError("STRIPE_SECRET_KEY not configured")
    price_id = PLAN_PRICES.get(plan)
    if not price_id:
        raise ValueError(f"Unknown plan: {plan}. Set STRIPE_PRICE_{plan.upper()}")

    metadata = {"user_id": str(user_id), "plan": plan, "plan_type": plan}

    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(user_id),
        "metadata": metadata,
        # Copy metadata onto the Subscription object so that
        # customer.subscription.created webhooks can resolve the user.
        "subscription_data": {"metadata": metadata},
    }
    if email:
        # Prefill for Stripe Link 1-click checkout identification
        params["customer_email"] = email

    return stripe.checkout.Session.create(**params)


def create_billing_portal_session(
    customer_id: str,
    return_url: str = "https://grant-rx.vercel.app",
) -> stripe.billing_portal.Session:
    """Create a Stripe Customer Portal session for self-service billing management."""
    if not stripe.api_key:
        raise RuntimeError("STRIPE_SECRET_KEY not configured")
    return stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )


# ---------------------------------------------------------------------------
# Webhook handling
# ---------------------------------------------------------------------------


def verify_webhook_signature(payload: bytes, signature: str) -> stripe.Event:
    """Verify and construct a Stripe Event from raw payload + signature header."""
    if not WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET not configured")
    return stripe.Webhook.construct_event(payload, signature, WEBHOOK_SECRET)


def _find_profile_by_stripe_id(db: Session, customer_id: str) -> Optional[Profile]:
    return db.query(Profile).filter(Profile.stripe_customer_id == customer_id).first()


def _find_profile_by_user_id(db: Session, user_id: str) -> Optional[Profile]:
    return db.query(Profile).filter(Profile.id == user_id).first()


def handle_webhook_event(db: Session, event: stripe.Event) -> dict:
    """Process a Stripe webhook event and update the profile.

    Returns a summary dict for logging / response.
    """
    etype = event["type"]
    data = event["data"]["object"]
    logger.info("Processing Stripe webhook: %s", etype)

    if etype == "customer.subscription.created":
        return _on_subscription_created(db, data)
    elif etype == "customer.subscription.deleted":
        return _on_subscription_deleted(db, data)
    elif etype == "invoice.payment_succeeded":
        return _on_invoice_paid(db, data)
    elif etype == "invoice.payment_failed":
        return _on_invoice_failed(db, data)
    else:
        logger.debug("Unhandled event type: %s", etype)
        return {"status": "ignored", "event": etype}


def _on_subscription_created(db: Session, sub: dict) -> dict:
    user_id = sub.get("metadata", {}).get("user_id")
    customer_id = sub.get("customer")
    sub_id = sub.get("id")
    status = sub.get("status")

    profile = None
    if user_id:
        profile = _find_profile_by_user_id(db, user_id)
    if not profile and customer_id:
        profile = _find_profile_by_stripe_id(db, customer_id)

    if not profile:
        logger.warning("subscription.created: no profile for user=%s customer=%s", user_id, customer_id)
        return {"status": "no_profile"}

    profile.stripe_customer_id = customer_id
    profile.stripe_subscription_id = sub_id
    profile.stripe_subscription_status = status
    # Active/trialing subscriptions grant premium
    if status in ("active", "trialing"):
        profile.subscription_tier = "premium"
    db.commit()
    return {"status": "updated", "tier": profile.subscription_tier}


def _on_subscription_deleted(db: Session, sub: dict) -> dict:
    sub_id = sub.get("id")
    customer_id = sub.get("customer")

    profile = _find_profile_by_stripe_id(db, customer_id)
    if not profile:
        # Fallback: search by subscription ID
        profile = db.query(Profile).filter(Profile.stripe_subscription_id == sub_id).first()
    if not profile:
        return {"status": "no_profile"}

    profile.stripe_subscription_status = "canceled"
    profile.subscription_tier = "free"
    db.commit()
    return {"status": "downgraded", "tier": "free"}


def _on_invoice_paid(db: Session, invoice: dict) -> dict:
    # Only act on subscription invoices
    if invoice.get("billing_reason") != "subscription_cycle":
        return {"status": "ignored"}

    customer_id = invoice.get("customer")
    sub_id = invoice.get("subscription")
    profile = _find_profile_by_stripe_id(db, customer_id)
    if not profile:
        return {"status": "no_profile"}

    profile.stripe_subscription_status = "active"
    profile.subscription_tier = "premium"
    if sub_id:
        profile.stripe_subscription_id = sub_id
    db.commit()

    # Send payment receipt email
    if profile.email:
        from .email_service import payment_receipt
        amount_total = invoice.get("total")
        currency = invoice.get("currency", "usd")
        amount_str = f"${amount_total / 100:.2f}" if amount_total else None
        invoice_url = invoice.get("hosted_invoice_url")
        payment_receipt(
            to=profile.email,
            name=profile.full_name,
            amount=amount_str,
            plan="Premium",
            invoice_url=invoice_url,
        )

    return {"status": "renewed", "tier": "premium"}


def _on_invoice_failed(db: Session, invoice: dict) -> dict:
    customer_id = invoice.get("customer")
    profile = _find_profile_by_stripe_id(db, customer_id)
    if not profile:
        return {"status": "no_profile"}

    # Send dunning notification email
    if profile.email:
        from .email_service import dunning_notification
        amount_total = invoice.get("total")
        amount_str = f"${amount_total / 100:.2f}" if amount_total else None
        attempt = invoice.get("attempt_count")
        next_attempt = invoice.get("next_payment_attempt")
        invoice_url = invoice.get("hosted_invoice_url")
        dunning_notification(
            to=profile.email,
            name=profile.full_name,
            amount=amount_str,
            attempt=attempt,
            next_attempt=str(next_attempt) if next_attempt else None,
            invoice_url=invoice_url,
        )

    return {"status": "dunning_sent"}

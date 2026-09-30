"""Profile service — account lifecycle operations.

Account deletion is intentionally fail-safe around external systems:
  1. An active Stripe subscription must be canceled before local deletion.
     If Stripe cannot confirm cancellation, deletion stops so GrantRx never
     removes the account while recurring billing may still be active.
  2. User-owned database records are deleted and committed atomically.
  3. Supabase Auth is deleted only *after* the database commit succeeds, so
     an auth identity is never removed before GrantRx has committed deletion.

Supabase cleanup is best-effort after the irreversible local commit. A failed
Auth cleanup is reported explicitly for operations follow-up; it cannot roll
back already-deleted personal data.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from ..models.models import Profile, ScholarshipReport, StudentCollegeBudget, UserScholarship

logger = logging.getLogger(__name__)


class SubscriptionCancellationError(RuntimeError):
    """Raised when account deletion cannot safely stop an active subscription."""


def _cancel_stripe_subscription(subscription_id: str) -> bool:
    """Cancel a Stripe subscription immediately. Returns True only on confirmation."""
    try:
        import stripe  # type: ignore
    except ImportError:
        logger.error("stripe package not installed — cannot cancel subscription %s", subscription_id)
        return False

    if not stripe.api_key:
        logger.error("STRIPE_SECRET_KEY not set — cannot cancel subscription %s", subscription_id)
        return False

    try:
        stripe.Subscription.delete(subscription_id)
        logger.info("Canceled Stripe subscription %s", subscription_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to cancel Stripe subscription %s: %s", subscription_id, exc)
        return False


def _delete_supabase_user(user_id: str) -> bool:
    """Delete the user from Supabase Auth via the Admin API."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        logger.error("SUPABASE_URL/SUPABASE_KEY not set — Supabase user cleanup required for %s", user_id)
        return False

    try:
        from supabase import create_client  # type: ignore

        client = create_client(supabase_url, supabase_key)
        client.auth.admin.delete_user(user_id)
        logger.info("Deleted Supabase auth user %s", user_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to delete Supabase user %s: %s", user_id, exc)
        return False


def delete_account(db: Session, user_id: str) -> dict:
    """Permanently delete a user's account without risking post-deletion billing.

    Active/trialing subscriptions are a hard precondition: Stripe must confirm
    cancellation before destructive local work begins. Database deletion is then
    committed before Supabase Auth deletion, preventing an auth-first partial
    failure. Supabase failure is surfaced as ``auth_cleanup_required`` so it can
    be retried operationally without restoring personal data.
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return {"status": "not_found", "message": "Profile not found."}

    has_active_subscription = bool(
        profile.stripe_subscription_id
        and profile.stripe_subscription_status in ("active", "trialing")
    )
    stripe_canceled = False
    if has_active_subscription:
        stripe_canceled = _cancel_stripe_subscription(profile.stripe_subscription_id)
        if not stripe_canceled:
            raise SubscriptionCancellationError(
                "Active subscription could not be canceled. Account deletion was not performed."
            )

    try:
        db.query(UserScholarship).filter(UserScholarship.user_id == user_id).delete(synchronize_session=False)
        db.query(StudentCollegeBudget).filter(StudentCollegeBudget.user_id == user_id).delete(synchronize_session=False)
        db.query(ScholarshipReport).filter(ScholarshipReport.reported_by == user_id).delete(synchronize_session=False)
        db.query(Profile).filter(Profile.id == user_id).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Database account deletion failed for user %s", user_id)
        raise

    # External auth deletion occurs only after the database transaction is durable.
    supabase_deleted = _delete_supabase_user(user_id)
    status = "deleted" if supabase_deleted else "deleted_auth_cleanup_required"
    message = (
        "Account, subscription, and personal data permanently purged."
        if supabase_deleted
        else "Personal data was deleted, but authentication cleanup requires follow-up."
    )
    return {
        "status": status,
        "message": message,
        "stripe_canceled": stripe_canceled,
        "supabase_deleted": supabase_deleted,
        "auth_cleanup_required": not supabase_deleted,
    }

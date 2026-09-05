"""Profile service — account lifecycle operations.

Currently provides self-serve account deletion that:
  1. Cancels any active Stripe subscription to stop recurring charges.
  2. Cascades deletion across user-owned records (budget, tracked
     scholarships, reports filed by the user).
  3. Removes the profile row itself.
  4. Purges Supabase Auth credentials when SUPABASE_URL + SUPABASE_KEY
     are configured (graceful no-op otherwise).

All steps are wrapped so that a failure in one external system (Stripe or
Supabase) does not prevent local data deletion, which is the user's
primary intent. Errors are logged and surfaced in the response summary.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from ..models.models import Profile, ScholarshipReport, StudentCollegeBudget, UserScholarship

logger = logging.getLogger(__name__)


def _cancel_stripe_subscription(subscription_id: str) -> bool:
    """Cancel a Stripe subscription immediately. Returns True on success."""
    try:
        import stripe  # type: ignore
    except ImportError:
        logger.warning("stripe package not installed — cannot cancel subscription %s", subscription_id)
        return False

    if not stripe.api_key:
        logger.info("STRIPE_SECRET_KEY not set — skipping Stripe cancellation for %s", subscription_id)
        return False

    try:
        stripe.Subscription.delete(subscription_id)
        logger.info("Canceled Stripe subscription %s", subscription_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to cancel Stripe subscription %s: %s", subscription_id, exc)
        return False


def _delete_supabase_user(user_id: str) -> bool:
    """Delete the user from Supabase Auth via the Admin API.

    Returns True on success, False on failure or when not configured.
    """
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        logger.info("SUPABASE_URL/SUPABASE_KEY not set — skipping Supabase user deletion")
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
    """Permanently delete a user's account and all associated data.

    Order of operations:
      1. Load profile (needed for Stripe customer/subscription IDs).
      2. Cancel Stripe subscription if active.
      3. Delete user_scholarships rows.
      4. Delete student_college_budgets rows.
      5. Delete scholarship_reports filed by the user.
      6. Delete the profile row.
      7. Purge Supabase Auth credentials.
      8. Commit.

    Returns a summary dict with status and per-step indicators.
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if not profile:
        return {
            "status": "not_found",
            "message": "Profile not found.",
        }

    stripe_canceled = False
    if profile.stripe_subscription_id and profile.stripe_subscription_status in ("active", "trialing"):
        stripe_canceled = _cancel_stripe_subscription(profile.stripe_subscription_id)

    # Cascade-delete user-owned records
    db.query(UserScholarship).filter(UserScholarship.user_id == user_id).delete(synchronize_session=False)
    db.query(StudentCollegeBudget).filter(StudentCollegeBudget.user_id == user_id).delete(synchronize_session=False)
    db.query(ScholarshipReport).filter(ScholarshipReport.reported_by == user_id).delete(synchronize_session=False)

    # Delete the profile itself
    db.query(Profile).filter(Profile.id == user_id).delete(synchronize_session=False)

    # Purge Supabase Auth credentials
    supabase_deleted = _delete_supabase_user(user_id)

    db.commit()

    return {
        "status": "deleted",
        "message": "Account, subscription, and personal data permanently purged.",
        "stripe_canceled": stripe_canceled,
        "supabase_deleted": supabase_deleted,
    }

"""Monthly Re-engagement Opportunity Digest Worker.

Queries free-tier users with `marketing_opt_in == True`, computes the
number and total dollar value of newly-scraped scholarships matching
their primary discipline in the last 30 days, and sends a personalized
re-engagement email.

Usage:
    python -m app.workers.reengagement_digest --dry-run   # print to stdout
    python -m app.workers.reengagement_digest              # send via Resend
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import func

from ..database import SessionLocal
from ..models.models import Profile, Scholarship

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 30


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ReengagementPayload:
    """Personalized re-engagement digest for a single free-tier user."""

    user_email: str
    user_name: Optional[str]
    discipline: Optional[str]
    new_count: int
    total_value: int

    @property
    def subject(self) -> str:
        if self.new_count == 0:
            return "GrantRx: New scholarships coming soon"
        return f"GrantRx Update: {self.new_count} new scholarships (${self.total_value:,} total) for your discipline!"

    def render_text(self) -> str:
        first = (self.user_name or "there").split(" ")[0]
        if self.new_count == 0:
            lines = [
                f"Hi {first},",
                "",
                "We're constantly indexing new scholarships for clinical"
                " health students. Check back soon for fresh opportunities"
                " matched to your discipline.",
                "",
                "Browse your feed: https://grant-rx.vercel.app",
                "",
                "— The GrantRx Team",
            ]
        else:
            lines = [
                f"Hi {first},",
                "",
                f"GrantRx Update: {self.new_count} new scholarships"
                f" (${self.total_value:,} total) were just indexed for"
                f" your discipline!",
                "",
                "Log in to see your fresh matches and start applying.",
                "",
                "Browse your feed: https://grant-rx.vercel.app",
                "",
                "— The GrantRx Team",
            ]
        return "\n".join(lines)

    def render_html(self) -> str:
        first = (self.user_name or "there").split(" ")[0]
        if self.new_count == 0:
            body = (
                "<p>We're constantly indexing new scholarships for clinical"
                " health students. Check back soon for fresh opportunities"
                " matched to your discipline.</p>"
            )
        else:
            body = (
                f"<p>GrantRx Update: <strong>{self.new_count} new scholarships</strong>"
                f" (<strong>${self.total_value:,} total</strong>) were just indexed"
                f" for your discipline!</p>"
                "<p>Log in to see your fresh matches and start applying.</p>"
            )
        return (
            '<html><body style="font-family: \'Sora\', sans-serif; color: #1a1a2e; max-width: 560px; margin: 0 auto;">'
            f'<h1 style="font-family: \'Fraunces\', serif; color: #5C7AFF;">GrantRx Update</h1>'
            f"<p>Hi {first},</p>"
            f"{body}"
            '<p><a href="https://grant-rx.vercel.app" style="background: #5C7AFF; color: #fff; padding: 12px 24px; border-radius: 999px; text-decoration: none; display: inline-block;">Browse Your Feed</a></p>'
            '<p style="color: #64748b; font-size: 14px;">— The GrantRx Team</p>'
            "</body></html>"
        )


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def build_digests(db, now: Optional[datetime] = None) -> List[ReengagementPayload]:
    """Build re-engagement payloads for all eligible free-tier users.

    Args:
        db: SQLAlchemy session.
        now: Reference datetime (defaults to now UTC).

    Returns:
        List of ReengagementPayload, one per eligible user.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)

    # Free-tier users with marketing opt-in and an email
    users = (
        db.query(Profile)
        .filter(Profile.subscription_tier == "free")
        .filter(Profile.marketing_opt_in == True)  # noqa: E712
        .filter(Profile.email.isnot(None))
        .all()
    )

    payloads: List[ReengagementPayload] = []

    for user in users:
        discipline = user.primary_discipline
        if not discipline:
            # Users without a discipline still get a generic count
            count_q = (
                db.query(
                    func.count(Scholarship.id),
                    func.coalesce(func.sum(Scholarship.award_amount), 0),
                )
                .filter(Scholarship.created_at >= cutoff)
                .filter(Scholarship.is_archived == False)  # noqa: E712
                .first()
            )
        else:
            # Discipline-specific count using ARRAY overlap
            count_q = (
                db.query(
                    func.count(Scholarship.id),
                    func.coalesce(func.sum(Scholarship.award_amount), 0),
                )
                .filter(Scholarship.created_at >= cutoff)
                .filter(Scholarship.is_archived == False)  # noqa: E712
                .filter(Scholarship.eligible_disciplines.contains([discipline]))
                .first()
            )

        new_count = int(count_q[0]) if count_q else 0
        total_value = int(count_q[1]) if count_q else 0

        # Only include users who have at least 1 new scholarship
        if new_count > 0:
            payloads.append(
                ReengagementPayload(
                    user_email=user.email,
                    user_name=user.full_name,
                    discipline=discipline,
                    new_count=new_count,
                    total_value=total_value,
                )
            )

    return payloads


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------


def send_digests(payloads: List[ReengagementPayload]) -> int:
    """Send re-engagement emails via Resend. Returns number of emails sent."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        logger.warning("RESEND_API_KEY not set — skipping send")
        return 0
    try:
        import resend  # type: ignore
    except ImportError:
        logger.warning("resend package not installed — skipping send")
        return 0

    try:
        resend.api_key = api_key
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to configure Resend API key: %s", exc)
        return 0

    from_email = os.getenv("DIGEST_FROM_EMAIL", "hello@grantrx.app")
    sent = 0
    for p in payloads:
        try:
            resend.Emails.send(
                {
                    "from": from_email,
                    "to": p.user_email,
                    "subject": p.subject,
                    "text": p.render_text(),
                    "html": p.render_html(),
                }
            )
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send re-engagement email to %s: %s", p.user_email, exc)
    return sent


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Send monthly re-engagement digest emails to free-tier users.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print simulated digests to stdout without sending emails.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db = SessionLocal()
    try:
        payloads = build_digests(db)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to build re-engagement digests: %s", exc)
        return 1
    finally:
        db.close()

    if not payloads:
        if args.dry_run:
            print(f"[dry-run] No free-tier users with new scholarships in the last {LOOKBACK_DAYS} days.")
        return 0

    if args.dry_run:
        print(f"[dry-run] {len(payloads)} free-tier user(s) with new opportunities:\n")
        for p in payloads:
            print(f"  To: {p.user_email} ({p.user_name or 'no name'})")
            print(f"  Discipline: {p.discipline or 'generic'}")
            print(f"  Subject: {p.subject}")
            print(f"  New: {p.new_count} scholarships, ${p.total_value:,} total")
            print()
        return 0

    sent = send_digests(payloads)
    logger.info("Sent %d re-engagement digest emails", sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())

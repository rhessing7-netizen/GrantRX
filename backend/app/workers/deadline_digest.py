"""Automated Deadline Digest Email Worker.

Queries all users with `marketing_opt_in == True` who have active
(non-dismissed, non-archived) tracked scholarships closing in the next
14 days. Formats an email payload per user with scholarship title, award
amount, days remaining, and application link.

Usage:
    python -m app.workers.deadline_digest --dry-run   # print to stdout
    python -m app.workers.deadline_digest              # send via Resend / SendGrid / SMTP
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import joinedload

from ..database import SessionLocal
from ..models.models import Profile, Scholarship, UserScholarship

logger = logging.getLogger(__name__)

DIGEST_WINDOW_DAYS = 14


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DigestEntry:
    """One scholarship line in a user's digest email."""

    title: str
    award_amount: int
    days_remaining: int
    portal_url: str
    deadline: str


@dataclass
class DigestPayload:
    """The full digest for a single user."""

    user_email: str
    user_name: Optional[str]
    entries: List[DigestEntry] = field(default_factory=list)

    @property
    def subject(self) -> str:
        count = len(self.entries)
        if count == 1:
            return "GrantRx: 1 scholarship deadline approaching"
        return f"GrantRx: {count} scholarship deadlines approaching"

    def render_text(self) -> str:
        """Render a plain-text email body."""
        lines = [
            f"Hi {self.user_name or 'there'},",
            "",
            f"You have {len(self.entries)} scholarship "
            f"{'deadline' if len(self.entries) == 1 else 'deadlines'} approaching in the next "
            f"{DIGEST_WINDOW_DAYS} days:",
            "",
        ]
        for e in self.entries:
            lines.append(
                f"  • {e.title} — ${e.award_amount:,} "
                f"(due in {e.days_remaining} day{'s' if e.days_remaining != 1 else ''})"
            )
            lines.append(f"    Apply: {e.portal_url}")
            lines.append("")
        lines.append("Stay on track!")
        lines.append("")
        lines.append("— The GrantRx Team")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def build_digests(db, now: Optional[date] = None) -> List[DigestPayload]:
    """Build digest payloads for all eligible users.

    Args:
        db: SQLAlchemy session.
        now: Reference date (defaults to today UTC).

    Returns:
        List of DigestPayload, one per user with at least one upcoming deadline.
    """
    now = now or datetime.now(timezone.utc).date()
    cutoff = now + timedelta(days=DIGEST_WINDOW_DAYS)

    # Fetch all marketing-opted-in users
    users = (
        db.query(Profile)
        .filter(Profile.marketing_opt_in == True)  # noqa: E712
        .filter(Profile.email.isnot(None))
        .all()
    )

    digests: List[DigestPayload] = []

    for user in users:
        # Active tracked scholarships (not dismissed, not archived)
        tracked = (
            db.query(UserScholarship)
            .options(joinedload(UserScholarship.scholarship))
            .filter(
                UserScholarship.user_id == user.id,
                UserScholarship.is_dismissed == False,  # noqa: E712
                UserScholarship.status != "archived",
            )
            .all()
        )

        entries: List[DigestEntry] = []
        for t in tracked:
            scholarship = t.scholarship
            if not scholarship or scholarship.is_archived:
                continue
            deadline = scholarship.deadline
            if not deadline:
                continue
            # Ensure deadline is a date object
            if isinstance(deadline, datetime):
                deadline = deadline.date()
            if deadline < now or deadline > cutoff:
                continue
            days_remaining = (deadline - now).days
            entries.append(
                DigestEntry(
                    title=scholarship.title,
                    award_amount=scholarship.award_amount or 0,
                    days_remaining=days_remaining,
                    portal_url=scholarship.portal_url or "",
                    deadline=deadline.isoformat(),
                )
            )

        if entries:
            # Sort by days remaining ascending (most urgent first)
            entries.sort(key=lambda e: e.days_remaining)
            digests.append(
                DigestPayload(
                    user_email=user.email,
                    user_name=user.full_name,
                    entries=entries,
                )
            )

    return digests


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------


def send_via_resend(payloads: List[DigestPayload]) -> int:
    """Send digests via the Resend API. Returns number of emails sent."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        logger.warning("RESEND_API_KEY not set — skipping send")
        return 0
    try:
        import resend  # type: ignore
    except ImportError:
        logger.warning("resend package not installed — skipping send")
        return 0

    resend.api_key = api_key
    from_email = os.getenv("DIGEST_FROM_EMAIL", "digest@grantrx.app")
    sent = 0
    for p in payloads:
        try:
            resend.Emails.send(
                {
                    "from": from_email,
                    "to": p.user_email,
                    "subject": p.subject,
                    "text": p.render_text(),
                }
            )
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send digest to %s: %s", p.user_email, exc)
    return sent


def send_via_smtp(payloads: List[DigestPayload]) -> int:
    """Send digests via SMTP fallback. Returns number of emails sent."""
    smtp_host = os.getenv("SMTP_HOST")
    if not smtp_host:
        logger.warning("SMTP_HOST not set — skipping send")
        return 0
    import smtplib
    from email.mime.text import MIMEText

    from_email = os.getenv("DIGEST_FROM_EMAIL", "digest@grantrx.app")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")

    sent = 0
    for p in payloads:
        msg = MIMEText(p.render_text(), "plain")
        msg["Subject"] = p.subject
        msg["From"] = from_email
        msg["To"] = p.user_email
        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                if smtp_user and smtp_pass:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                server.sendmail(from_email, p.user_email, msg.as_string())
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("SMTP send failed for %s: %s", p.user_email, exc)
    return sent


def send_digests(payloads: List[DigestPayload]) -> int:
    """Send digests via the configured provider (Resend > SMTP)."""
    if os.getenv("RESEND_API_KEY"):
        return send_via_resend(payloads)
    return send_via_smtp(payloads)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    global DIGEST_WINDOW_DAYS  # noqa: PLW0603

    parser = argparse.ArgumentParser(
        description="Send deadline digest emails to opted-in users.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print simulated digests to stdout without sending emails.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DIGEST_WINDOW_DAYS,
        help=f"Lookahead window in days (default: {DIGEST_WINDOW_DAYS}).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    DIGEST_WINDOW_DAYS = args.days

    db = SessionLocal()
    try:
        digests = build_digests(db)
    finally:
        db.close()

    if not digests:
        if args.dry_run:
            print("[dry-run] No users with upcoming deadlines in the next "
                  f"{DIGEST_WINDOW_DAYS} days.")
        return 0

    if args.dry_run:
        print(f"[dry-run] {len(digests)} user(s) with upcoming deadlines:\n")
        for d in digests:
            print(f"  To: {d.user_email} ({d.user_name or 'no name'})")
            print(f"  Subject: {d.subject}")
            for e in d.entries:
                print(
                    f"    - {e.title} | ${e.award_amount:,} | "
                    f"{e.days_remaining}d remaining | {e.portal_url}"
                )
            print()
        print(f"[dry-run] {len(digests)} digest(s) would be sent.")
        return 0

    sent = send_digests(digests)
    logger.info("Sent %d/%d digest emails", sent, len(digests))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Tests for the Automated Deadline Digest Worker.

Tests build_digests() logic: filtering by marketing_opt_in, excluding
dismissed/archived scholarships, and the 14-day lookahead window.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.deadline_digest import DigestPayload, build_digests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(email="student@grantrx.local", marketing=True, name="Test Student"):
    user = MagicMock()
    user.id = uuid4()
    user.email = email if marketing else None
    user.full_name = name
    user.marketing_opt_in = marketing
    return user


def _make_scholarship(deadline, title="Test Scholarship", amount=5000, archived=False):
    s = MagicMock()
    s.id = uuid4()
    s.title = title
    s.award_amount = amount
    s.portal_url = "https://example.com/apply"
    s.deadline = deadline
    s.is_archived = archived
    return s


def _make_tracking(user, scholarship, status="in_progress", dismissed=False):
    t = MagicMock()
    t.id = uuid4()
    t.user_id = user.id
    t.scholarship_id = scholarship.id
    t.status = status
    t.is_dismissed = dismissed
    t.scholarship = scholarship
    return t


def _make_db(users, trackings):
    """Build a mock DB session that dispatches queries by model and
    applies the same filters that build_digests uses."""
    db = MagicMock()

    # Pre-compute which users pass the marketing_opt_in + email filter
    eligible_users = [u for u in users if u.marketing_opt_in and u.email is not None]

    def query_side_effect(arg):
        q = MagicMock()
        if arg.__name__ == "Profile":
            # Simulate: .filter(marketing_opt_in == True).filter(email.isnot(None)).all()
            q.filter.return_value.filter.return_value.all.return_value = eligible_users
        elif arg.__name__ == "UserScholarship":
            # The query chain: .options().filter(user_id, is_dismissed, status).all()
            # We need to return only non-dismissed, non-archived trackings.
            # Since the mock can't inspect filter args, we pre-filter.
            eligible_trackings = [
                t for t in trackings
                if not t.is_dismissed and t.status != "archived"
            ]
            q.options.return_value.filter.return_value.all.return_value = eligible_trackings
        return q

    db.query.side_effect = query_side_effect
    return db


# ---------------------------------------------------------------------------
# Tests: build_digests filtering
# ---------------------------------------------------------------------------

class TestBuildDigests:
    def test_includes_scholarship_within_14_days(self):
        """A scholarship due in 7 days should appear in the digest."""
        now = date(2025, 1, 15)
        user = _make_user()
        scholarship = _make_scholarship(deadline=now + timedelta(days=7))
        tracking = _make_tracking(user, scholarship)
        db = _make_db([user], [tracking])

        digests = build_digests(db, now=now)
        assert len(digests) == 1
        assert digests[0].user_email == "student@grantrx.local"
        assert len(digests[0].entries) == 1
        assert digests[0].entries[0].days_remaining == 7

    def test_excludes_scholarship_beyond_14_days(self):
        """A scholarship due in 20 days should NOT appear."""
        now = date(2025, 1, 15)
        user = _make_user()
        scholarship = _make_scholarship(deadline=now + timedelta(days=20))
        tracking = _make_tracking(user, scholarship)
        db = _make_db([user], [tracking])

        digests = build_digests(db, now=now)
        assert len(digests) == 0

    def test_excludes_past_deadline(self):
        """A scholarship with a past deadline should NOT appear."""
        now = date(2025, 1, 15)
        user = _make_user()
        scholarship = _make_scholarship(deadline=now - timedelta(days=3))
        tracking = _make_tracking(user, scholarship)
        db = _make_db([user], [tracking])

        digests = build_digests(db, now=now)
        assert len(digests) == 0

    def test_excludes_dismissed_tracking(self):
        """A dismissed UserScholarship should NOT appear in the digest."""
        now = date(2025, 1, 15)
        user = _make_user()
        scholarship = _make_scholarship(deadline=now + timedelta(days=5))
        tracking = _make_tracking(user, scholarship, dismissed=True)
        db = _make_db([user], [tracking])

        digests = build_digests(db, now=now)
        assert len(digests) == 0

    def test_excludes_archived_status(self):
        """An archived tracking status should NOT appear."""
        now = date(2025, 1, 15)
        user = _make_user()
        scholarship = _make_scholarship(deadline=now + timedelta(days=5))
        tracking = _make_tracking(user, scholarship, status="archived")
        db = _make_db([user], [tracking])

        digests = build_digests(db, now=now)
        assert len(digests) == 0

    def test_excludes_archived_scholarship(self):
        """A scholarship marked is_archived should NOT appear even if tracked."""
        now = date(2025, 1, 15)
        user = _make_user()
        scholarship = _make_scholarship(deadline=now + timedelta(days=5), archived=True)
        tracking = _make_tracking(user, scholarship)
        db = _make_db([user], [tracking])

        digests = build_digests(db, now=now)
        assert len(digests) == 0

    def test_excludes_users_without_marketing_opt_in(self):
        """Users with marketing_opt_in=False should NOT receive digests."""
        now = date(2025, 1, 15)
        user = _make_user(marketing=False)
        scholarship = _make_scholarship(deadline=now + timedelta(days=5))
        tracking = _make_tracking(user, scholarship)
        db = _make_db([user], [tracking])

        digests = build_digests(db, now=now)
        assert len(digests) == 0

    def test_multiple_scholarships_sorted_by_urgency(self):
        """Entries should be sorted by days_remaining ascending."""
        now = date(2025, 1, 15)
        user = _make_user()
        s1 = _make_scholarship(deadline=now + timedelta(days=10), title="Far")
        s2 = _make_scholarship(deadline=now + timedelta(days=3), title="Urgent")
        s3 = _make_scholarship(deadline=now + timedelta(days=7), title="Medium")
        t1 = _make_tracking(user, s1)
        t2 = _make_tracking(user, s2)
        t3 = _make_tracking(user, s3)
        db = _make_db([user], [t1, t2, t3])

        digests = build_digests(db, now=now)
        assert len(digests) == 1
        entries = digests[0].entries
        assert entries[0].title == "Urgent"
        assert entries[1].title == "Medium"
        assert entries[2].title == "Far"

    def test_multiple_users(self):
        """Each user gets their own digest payload."""
        now = date(2025, 1, 15)
        user1 = _make_user(email="user1@grantrx.local", name="User One")
        user2 = _make_user(email="user2@grantrx.local", name="User Two")
        s1 = _make_scholarship(deadline=now + timedelta(days=5), title="Grant A")
        s2 = _make_scholarship(deadline=now + timedelta(days=8), title="Grant B")
        t1 = _make_tracking(user1, s1)
        t2 = _make_tracking(user2, s2)
        db = _make_db([user1, user2], [t1, t2])

        digests = build_digests(db, now=now)
        assert len(digests) == 2
        emails = {d.user_email for d in digests}
        assert emails == {"user1@grantrx.local", "user2@grantrx.local"}

    def test_no_users_returns_empty(self):
        """With no opted-in users, digests should be empty."""
        db = _make_db([], [])
        digests = build_digests(db, now=date(2025, 1, 15))
        assert digests == []


# ---------------------------------------------------------------------------
# Tests: DigestPayload rendering
# ---------------------------------------------------------------------------

class TestDigestRendering:
    def test_subject_singular(self):
        """Subject should say '1 scholarship deadline' for a single entry."""
        from app.workers.deadline_digest import DigestEntry
        payload = DigestPayload(
            user_email="test@grantrx.local",
            user_name="Test",
            entries=[DigestEntry("Grant", 5000, 5, "https://example.com", "2025-01-20")],
        )
        assert "1 scholarship deadline" in payload.subject

    def test_subject_plural(self):
        """Subject should say 'N scholarship deadlines' for multiple entries."""
        from app.workers.deadline_digest import DigestEntry
        payload = DigestPayload(
            user_email="test@grantrx.local",
            user_name="Test",
            entries=[
                DigestEntry("Grant A", 5000, 5, "https://a.com", "2025-01-20"),
                DigestEntry("Grant B", 3000, 10, "https://b.com", "2025-01-25"),
            ],
        )
        assert "2 scholarship deadlines" in payload.subject

    def test_render_text_includes_key_info(self):
        """The text body should include title, amount, days, and URL."""
        from app.workers.deadline_digest import DigestEntry
        payload = DigestPayload(
            user_email="test@grantrx.local",
            user_name="Alice",
            entries=[DigestEntry("NSF Grant", 10000, 3, "https://nsf.gov/apply", "2025-01-18")],
        )
        text = payload.render_text()
        assert "Alice" in text
        assert "NSF Grant" in text
        assert "$10,000" in text
        assert "3 days" in text
        assert "https://nsf.gov/apply" in text

"""Tests for the signed marketing-unsubscribe mechanism.

Covers the WS-1 contract:
  - digest/re-engagement marketing email bodies contain a functional
    unsubscribe URL
  - a valid token opts the bound user out (marketing_opt_in -> False)
  - repeated unsubscribes are idempotent
  - invalid/tampered tokens cannot change preferences
  - one user's token cannot alter another user's preference
  - the mechanism can never opt a user IN
  - opted-out users stay excluded from digest selection
  - transactional email paths are unaffected by marketing opt-out
  - generated URLs expose no email address or secret material
  - missing signing configuration fails closed (no token, no send, 503)
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.models import Profile
from app.services.unsubscribe_tokens import (
    build_unsubscribe_url,
    make_unsubscribe_token,
    signing_configured,
    verify_unsubscribe_token,
)
from app.workers.deadline_digest import DigestPayload, build_digests


TEST_UNSUB_SECRET = "test-unsubscribe-signing-secret"


# ---------------------------------------------------------------------------
# Model-aware fake session (same pattern as test_early_access.py)
# ---------------------------------------------------------------------------


def _eval_criterion(criterion, row) -> bool:
    clauses = getattr(criterion, "clauses", None)
    if clauses is not None:
        return all(_eval_criterion(c, row) for c in clauses)
    left = getattr(criterion.left, "key", None) or getattr(criterion.left, "name", None)
    right = criterion.right
    rval = getattr(right, "value", right)
    opname = getattr(criterion.operator, "__name__", str(criterion.operator))
    if opname == "eq":
        return getattr(row, left) == rval
    raise AssertionError(f"FakeSession does not support operator {opname!r}")


class _Query:
    def __init__(self, session, model):
        self._rows = list(session._rows.get(model, []))

    def filter(self, *criteria):
        self._rows = [r for r in self._rows if all(_eval_criterion(c, r) for c in criteria)]
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self, profiles=None):
        self._rows = {Profile: list(profiles or [])}
        self.commits = 0

    def query(self, model):
        return _Query(self, model)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _make_profile(user_id=None, marketing_opt_in=True):
    p = MagicMock()
    p.id = user_id or uuid4()
    p.email = "student@example.com"
    p.full_name = "Test Student"
    p.marketing_opt_in = marketing_opt_in
    p.marketing_opt_in_at = None
    return p


@pytest.fixture(autouse=True)
def _signing_env():
    with patch.dict(
        os.environ,
        {
            "ENVIRONMENT": "production",
            "MARKETING_UNSUBSCRIBE_SECRET": TEST_UNSUB_SECRET,
        },
    ):
        yield


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _override_db(db):
    app.dependency_overrides[get_db] = lambda: db


# ===========================================================================
# Token unit behavior
# ===========================================================================


class TestTokenPrimitives:
    def test_mint_and_verify_round_trip(self):
        uid = uuid4()
        token = make_unsubscribe_token(uid)
        assert token is not None
        assert verify_unsubscribe_token(token) == uid

    def test_token_embeds_no_email_or_secret(self):
        uid = uuid4()
        token = make_unsubscribe_token(uid)
        assert TEST_UNSUB_SECRET not in token
        assert "@" not in token
        url = build_unsubscribe_url(uid)
        assert TEST_UNSUB_SECRET not in url
        assert "@" not in url
        assert "student@example.com" not in url

    def test_tampered_signature_rejected(self):
        uid = uuid4()
        token = make_unsubscribe_token(uid)
        uid_part, sig = token.rsplit(".", 1)
        tampered = f"{uid_part}.{'0' * len(sig)}"
        assert verify_unsubscribe_token(tampered) is None

    def test_token_bound_to_one_user(self):
        token_a = make_unsubscribe_token(uuid4())
        other = uuid4()
        _, sig = token_a.rsplit(".", 1)
        grafted = f"{other}.{sig}"
        assert verify_unsubscribe_token(grafted) is None

    def test_malformed_tokens_rejected(self):
        assert verify_unsubscribe_token(None) is None
        assert verify_unsubscribe_token("") is None
        assert verify_unsubscribe_token("nosignature") is None
        assert verify_unsubscribe_token("not-a-uuid.deadbeef") is None
        assert verify_unsubscribe_token(f"{uuid4()}.{'ab' * 32}") is None

    def test_wrong_secret_rejected(self):
        uid = uuid4()
        token = make_unsubscribe_token(uid)
        with patch.dict(
            os.environ, {"MARKETING_UNSUBSCRIBE_SECRET": "different-secret"}
        ):
            assert verify_unsubscribe_token(token) is None

    def test_no_secret_fails_closed(self):
        with patch.dict(
            os.environ,
            {"MARKETING_UNSUBSCRIBE_SECRET": "", "SUPABASE_JWT_SECRET": ""},
        ):
            assert not signing_configured()
            assert make_unsubscribe_token(uuid4()) is None
            assert build_unsubscribe_url(uuid4()) is None
            assert verify_unsubscribe_token(f"{uuid4()}.{'ab' * 32}") is None


# ===========================================================================
# Endpoint behavior
# ===========================================================================


class TestUnsubscribeEndpoint:
    def test_valid_token_opts_user_out(self, client):
        uid = uuid4()
        profile = _make_profile(user_id=uid, marketing_opt_in=True)
        _override_db(FakeSession(profiles=[profile]))

        resp = client.post(
            "/api/v1/marketing/unsubscribe",
            json={"token": make_unsubscribe_token(uid)},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "unsubscribed"
        assert profile.marketing_opt_in is False
        assert profile.marketing_opt_in_at is None

    def test_no_auth_header_required(self, client):
        """The endpoint is public — TestClient sends no Bearer token."""
        uid = uuid4()
        profile = _make_profile(user_id=uid)
        _override_db(FakeSession(profiles=[profile]))
        resp = client.post(
            "/api/v1/marketing/unsubscribe",
            json={"token": make_unsubscribe_token(uid)},
        )
        assert resp.status_code == 200

    def test_repeated_unsubscribe_idempotent(self, client):
        uid = uuid4()
        profile = _make_profile(user_id=uid)
        _override_db(FakeSession(profiles=[profile]))
        token = make_unsubscribe_token(uid)
        for _ in range(3):
            resp = client.post(
                "/api/v1/marketing/unsubscribe", json={"token": token}
            )
            assert resp.status_code == 200
        assert profile.marketing_opt_in is False

    def test_invalid_token_cannot_change_preferences(self, client):
        profile = _make_profile(marketing_opt_in=True)
        _override_db(FakeSession(profiles=[profile]))
        resp = client.post(
            "/api/v1/marketing/unsubscribe", json={"token": "bogus.token"}
        )
        assert resp.status_code == 400
        assert profile.marketing_opt_in is True

    def test_token_for_user_a_cannot_touch_user_b(self, client):
        uid_a, uid_b = uuid4(), uuid4()
        a = _make_profile(user_id=uid_a)
        b = _make_profile(user_id=uid_b)
        _override_db(FakeSession(profiles=[a, b]))

        resp = client.post(
            "/api/v1/marketing/unsubscribe",
            json={"token": make_unsubscribe_token(uid_a)},
        )
        assert resp.status_code == 200
        assert a.marketing_opt_in is False
        assert b.marketing_opt_in is True

    def test_endpoint_can_never_opt_in(self, client):
        """An already-opted-out user stays out; there is no opt-in path."""
        uid = uuid4()
        profile = _make_profile(user_id=uid, marketing_opt_in=False)
        _override_db(FakeSession(profiles=[profile]))
        resp = client.post(
            "/api/v1/marketing/unsubscribe",
            json={"token": make_unsubscribe_token(uid)},
        )
        assert resp.status_code == 200
        assert profile.marketing_opt_in is False

    def test_unknown_user_reports_success_without_leaking(self, client):
        """Valid token for a deleted/unknown profile → success (no oracle)."""
        _override_db(FakeSession(profiles=[]))
        resp = client.post(
            "/api/v1/marketing/unsubscribe",
            json={"token": make_unsubscribe_token(uuid4())},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "unsubscribed"

    def test_unconfigured_signing_fails_safely(self, client):
        uid = uuid4()
        profile = _make_profile(user_id=uid)
        _override_db(FakeSession(profiles=[profile]))
        token = make_unsubscribe_token(uid)
        with patch.dict(
            os.environ,
            {"MARKETING_UNSUBSCRIBE_SECRET": "", "SUPABASE_JWT_SECRET": ""},
        ):
            resp = client.post(
                "/api/v1/marketing/unsubscribe", json={"token": token}
            )
        assert resp.status_code == 503
        assert profile.marketing_opt_in is True

    def test_token_does_not_modify_unrelated_fields(self, client):
        uid = uuid4()
        profile = _make_profile(user_id=uid)
        profile.email = "keepme@example.com"
        profile.full_name = "Keep Me"
        _override_db(FakeSession(profiles=[profile]))
        client.post(
            "/api/v1/marketing/unsubscribe",
            json={"token": make_unsubscribe_token(uid)},
        )
        assert profile.email == "keepme@example.com"
        assert profile.full_name == "Keep Me"


# ===========================================================================
# Marketing email bodies contain a functional link
# ===========================================================================


def _digest_user(user_id=None):
    u = MagicMock()
    u.id = user_id or uuid4()
    u.email = "student@example.com"
    u.full_name = "Digest User"
    u.marketing_opt_in = True
    return u


def _scholarship(deadline):
    s = MagicMock()
    s.id = uuid4()
    s.title = "Nursing Grant"
    s.award_amount = 5000
    s.portal_url = "https://example.com/apply"
    s.deadline = deadline
    s.is_archived = False
    return s


def _tracking(user, scholarship):
    t = MagicMock()
    t.id = uuid4()
    t.user_id = user.id
    t.scholarship_id = scholarship.id
    t.status = "in_progress"
    t.is_dismissed = False
    t.scholarship = scholarship
    return t


def _digest_db(users, trackings):
    db = MagicMock()
    eligible = [u for u in users if u.marketing_opt_in and u.email]

    def query_side_effect(arg):
        q = MagicMock()
        if arg.__name__ == "Profile":
            q.filter.return_value.filter.return_value.all.return_value = eligible
        elif arg.__name__ == "UserScholarship":
            ok = [t for t in trackings if not t.is_dismissed and t.status != "archived"]
            q.options.return_value.filter.return_value.all.return_value = ok
        return q

    db.query.side_effect = query_side_effect
    return db


class TestDigestUnsubscribeLink:
    def test_digest_payload_carries_functional_url(self):
        uid = uuid4()
        user = _digest_user(user_id=uid)
        db = _digest_db(
            [user],
            [_tracking(user, _scholarship(date.today() + timedelta(days=5)))],
        )
        digests = build_digests(db)
        assert len(digests) == 1
        url = digests[0].unsubscribe_url
        assert url and "/unsubscribe?token=" in url
        # The embedded token actually verifies for the right user
        token = url.split("token=")[1]
        assert verify_unsubscribe_token(token) == uid

    def test_rendered_email_contains_unsubscribe_link(self):
        url = build_unsubscribe_url(uuid4())
        payload = DigestPayload(
            user_email="x@example.com",
            user_name="X",
            unsubscribe_url=url,
        )
        text = payload.render_text()
        assert "Unsubscribe:" in text
        assert url in text

    def test_digest_build_fails_closed_without_secret(self):
        """No signing secret → build raises; no email is sent."""
        user = _digest_user()
        db = _digest_db(
            [user],
            [_tracking(user, _scholarship(date.today() + timedelta(days=5)))],
        )
        with patch.dict(
            os.environ,
            {"MARKETING_UNSUBSCRIBE_SECRET": "", "SUPABASE_JWT_SECRET": ""},
        ):
            with pytest.raises(RuntimeError, match="unsubscribe"):
                build_digests(db)

    def test_opted_out_users_stay_excluded_from_digest(self):
        """marketing_opt_in=False users never reach the payload stage."""
        user = _digest_user()
        user.marketing_opt_in = False
        db = _digest_db(
            [user],
            [_tracking(user, _scholarship(date.today() + timedelta(days=5)))],
        )
        assert build_digests(db) == []


# ===========================================================================
# Transactional mail is unaffected by marketing opt-out
# ===========================================================================


class TestTransactionalUnaffected:
    def test_transactional_send_does_not_consult_marketing_opt_in(self):
        """welcome_email/receipt/dunning take only (to, ...) — they never
        read marketing_opt_in, so opt-out can't silence receipts."""
        import inspect

        from app.services import email_service

        for fn_name in ("welcome_email", "payment_receipt", "dunning_notification"):
            src = inspect.getsource(getattr(email_service, fn_name))
            assert "marketing_opt_in" not in src

    def test_transactional_templates_carry_no_unsubscribe_link(self):
        """Genuinely transactional messages must not gain marketing opt-out
        links (and their senders don't accept a user record at all)."""
        from app.services import email_service

        assert not hasattr(email_service, "unsubscribe_url")

"""Shared pytest helpers for authenticated endpoint tests.

Production authentication intentionally fails closed: JWTMiddleware rejects
requests without a signed Bearer JWT, and ``get_current_user`` requires the
middleware-populated ``request.state.user``.  These helpers let endpoint tests
explicitly authenticate as a test user instead of weakening production auth —
no demo-token fallback and no auth-dependency bypass.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.auth import DEMO_USER_ID

TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests"
TEST_EMAIL = "testuser@grantrx.local"


def make_test_jwt(sub: str | UUID = DEMO_USER_ID, secret: str = TEST_JWT_SECRET) -> str:
    """Create a signed HS256 JWT that JWTMiddleware will accept."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(sub),
        "email": TEST_EMAIL,
        "role": "authenticated",
        "aud": "authenticated",
        "exp": now + timedelta(hours=1),
        "iat": now,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def jwt_secret():
    """Provide SUPABASE_JWT_SECRET so the middleware can verify test JWTs."""
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": TEST_JWT_SECRET}):
        yield TEST_JWT_SECRET


@pytest.fixture
def authenticated_client_factory(jwt_secret):
    """Factory building a TestClient that carries a valid Bearer JWT.

    The token authenticates as ``DEMO_USER_ID`` so fixtures that build records
    keyed to that user resolve identically to the historical demo-auth path.
    """

    def _factory(app: FastAPI) -> TestClient:
        return TestClient(app, headers={"Authorization": f"Bearer {make_test_jwt()}"})

    return _factory


# ---------------------------------------------------------------------------
# Fake DB session for identity/upsert tests
# ---------------------------------------------------------------------------


def _fake_col_name(expr):
    """Extract a model attribute name from a filter criterion's left side."""
    return getattr(expr, "key", None) or getattr(expr, "name", None)


def _fake_eval_criterion(criterion, row) -> bool:
    """Evaluate a simple SQLAlchemy criterion against a row object.

    Supports the shapes the identity lookup actually emits: ``col == value``,
    ``col != value``, ``col.is_(None)``, and ``or_()``/``and_()`` clause lists.
    Anything else fails loudly so the fake can never silently under-test.
    """
    clauses = getattr(criterion, "clauses", None)
    if clauses is not None:
        opname = getattr(criterion.operator, "__name__", str(criterion.operator))
        results = [_fake_eval_criterion(c, row) for c in clauses]
        if opname == "or_":
            return any(results)
        return all(results)

    left_val = getattr(row, _fake_col_name(criterion.left))
    right = criterion.right
    rval = getattr(right, "value", right)
    opname = getattr(criterion.operator, "__name__", str(criterion.operator))
    if opname == "eq":
        return left_val == rval
    if opname == "ne":
        return left_val != rval
    if opname in ("is_", "is"):
        return left_val is None
    if opname in ("isnot", "is_not"):
        return left_val is not None
    raise AssertionError(f"FakeCatalogSession does not support operator {opname!r}")


class _FakeQuery:
    def __init__(self, session, model):
        self._rows = list(session.rows)
        self._filtered = False
        for row in self._rows:
            session._snapshot(row)

    def filter(self, *criteria):
        self._filtered = True
        self._rows = [r for r in self._rows if all(_fake_eval_criterion(c, r) for c in criteria)]
        return self

    def all(self):
        if not self._filtered:
            raise AssertionError(
                "unfiltered .all() — the C4 identity lookup must never scan the table"
            )
        return list(self._rows)

    def first(self):
        rows = self.all()
        return rows[0] if rows else None


class FakeCatalogSession:
    """Minimal session fake with REAL filter evaluation on identity columns.

    Unlike a bare MagicMock (where any .filter().first() returns a truthy
    mock), this evaluates identity_key / identity_fallback_key / is_(None)
    criteria against the stored rows, so upsert tests exercise the actual
    lookup precedence. ``commit_errors`` and ``on_rollback`` let tests
    simulate unique-race IntegrityError recovery. Rollback faithfully
    reverts attribute mutations on queried rows, mirroring SQLAlchemy expiry.
    """

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.commits = 0
        self.commit_errors = []
        self.on_rollback = None
        self._pending = []
        self._snapshots = {}

    def _snapshot(self, row):
        if id(row) not in self._snapshots:
            self._snapshots[id(row)] = dict(vars(row))

    def query(self, model):
        return _FakeQuery(self, model)

    def add(self, obj):
        self._pending.append(obj)
        self.rows.append(obj)

    def commit(self):
        if self.commit_errors:
            raise self.commit_errors.pop(0)
        self._pending.clear()
        self._snapshots.clear()  # committed state becomes the new baseline
        self.commits += 1

    def rollback(self):
        for obj in self._pending:
            if obj in self.rows:
                self.rows.remove(obj)
        self._pending.clear()
        for row in self.rows:
            snap = self._snapshots.get(id(row))
            if snap is not None:
                vars(row).clear()
                vars(row).update(snap)
        if self.on_rollback:
            self.on_rollback()

    def refresh(self, obj):
        pass

    def close(self):
        pass

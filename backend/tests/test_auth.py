"""Unit tests for the authentication middleware.

Tests cover:
  - Valid JWT tokens (decoded successfully, user injected)
  - Missing authorization header (dev mode: demo user; prod: 401)
  - Expired JWT tokens (401 in production, demo fallback in dev)
  - Invalid JWT tokens (401 in production, demo fallback in dev)
  - Public paths bypass auth entirely
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

import jwt
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from app.middleware.auth import DEMO_TOKEN, DEMO_USER_ID, JWTMiddleware, User

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

TEST_SECRET = "test-jwt-secret-for-unit-tests"
TEST_USER_ID = "12345678-1234-1234-1234-123456789012"
TEST_EMAIL = "testuser@grantrx.local"


def _make_jwt(expired: bool = False, secret: str = TEST_SECRET) -> str:
    """Create a signed JWT for testing."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TEST_USER_ID,
        "email": TEST_EMAIL,
        "role": "authenticated",
        "aud": "authenticated",
        "exp": now - timedelta(hours=1) if expired else now + timedelta(hours=1),
        "iat": now,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def app_dev():
    """FastAPI app in dev mode (no JWT secret required, demo token accepted)."""
    app = FastAPI()
    app.add_middleware(JWTMiddleware)

    @app.get("/protected")
    def protected(request: Request):
        user = getattr(request.state, "user", None)
        if user:
            return {"user_id": str(user.id), "role": user.role}
        return JSONResponse({"detail": "no user"}, status_code=401)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    with patch.dict(os.environ, {"ENVIRONMENT": "development", "SUPABASE_JWT_SECRET": TEST_SECRET}):
        yield app


@pytest.fixture
def app_prod():
    """FastAPI app in production mode (JWT required, no demo fallback)."""
    app = FastAPI()
    app.add_middleware(JWTMiddleware)

    @app.get("/protected")
    def protected(request: Request):
        user = getattr(request.state, "user", None)
        if user:
            return {"user_id": str(user.id), "role": user.role}
        return JSONResponse({"detail": "no user"}, status_code=401)

    with patch.dict(os.environ, {"ENVIRONMENT": "production", "SUPABASE_JWT_SECRET": TEST_SECRET}):
        yield app


@pytest.fixture
def client_dev(app_dev):
    return TestClient(app_dev)


@pytest.fixture
def client_prod(app_prod):
    return TestClient(app_prod)


# ---------------------------------------------------------------------------
# Tests: Public paths
# ---------------------------------------------------------------------------

class TestPublicPaths:
    def test_health_endpoint_bypasses_auth(self, client_dev):
        """Public paths should be accessible without any auth header."""
        resp = client_dev.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Tests: Dev mode authentication
# ---------------------------------------------------------------------------

class TestDevModeAuth:
    def test_demo_token_accepted_in_dev_mode(self, client_dev):
        """The demo token should be accepted in development mode."""
        resp = client_dev.get(
            "/protected",
            headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == str(DEMO_USER_ID)

    def test_missing_auth_header_injects_demo_user(self, client_dev):
        """In dev mode, missing auth header should inject the demo user."""
        resp = client_dev.get("/protected")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == str(DEMO_USER_ID)

    def test_valid_jwt_accepted_in_dev_mode(self, client_dev):
        """A valid JWT should be accepted in dev mode."""
        token = _make_jwt()
        resp = client_dev.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == TEST_USER_ID

    def test_expired_jwt_falls_back_to_demo_in_dev(self, monkeypatch):
        """In dev mode, an expired JWT should fall back to the demo user."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)

        app = FastAPI()
        app.add_middleware(JWTMiddleware)

        @app.get("/protected")
        def protected(request: Request):
            user = getattr(request.state, "user", None)
            if user:
                return {"user_id": str(user.id), "role": user.role}
            return JSONResponse({"detail": "no user"}, status_code=401)

        client = TestClient(app)
        token = _make_jwt(expired=True)
        resp = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        # In dev mode, expired JWT falls back to demo user
        assert resp.status_code == 200
        assert resp.json()["user_id"] == str(DEMO_USER_ID)


# ---------------------------------------------------------------------------
# Tests: Production mode authentication
# ---------------------------------------------------------------------------

class TestProductionAuth:
    def test_missing_auth_header_returns_401(self, client_prod):
        """In production, missing auth header should return 401."""
        resp = client_prod.get("/protected")
        assert resp.status_code == 401
        assert "Missing authorization header" in resp.json()["detail"]

    def test_valid_jwt_accepted_in_production(self, client_prod):
        """A valid JWT should be accepted in production mode."""
        token = _make_jwt()
        resp = client_prod.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == TEST_USER_ID

    def test_expired_jwt_returns_401_in_production(self, client_prod):
        """In production, an expired JWT should return 401."""
        token = _make_jwt(expired=True)
        resp = client_prod.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_invalid_jwt_returns_401_in_production(self, client_prod):
        """In production, an invalid JWT should return 401."""
        resp = client_prod.get(
            "/protected",
            headers={"Authorization": "Bearer invalid-jwt-token"},
        )
        assert resp.status_code == 401
        assert "Invalid token" in resp.json()["detail"]

    def test_demo_token_rejected_in_production(self, client_prod):
        """In production, the demo token should NOT be accepted as a valid JWT."""
        # The demo token is not a valid JWT, so it should be rejected
        resp = client_prod.get(
            "/protected",
            headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
        )
        assert resp.status_code == 401

"""Dual-path Supabase JWT verification tests.

Covers the algorithm-routed verification in JWTMiddleware:
  - HS256 → SUPABASE_JWT_SECRET (legacy projects + test fixtures)
  - asymmetric (ES256 etc.) → Supabase JWKS via PyJWKClient
  - issuer/audience/expiration enforcement on both paths
  - fail-closed behavior for every rejection class

All asymmetric coverage is offline: a fake JWKS resolver stands in for the
network seam (_jwks_signing_key), keyed by kid so rotation behavior is real.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

import app.middleware.auth as auth
from app.middleware.auth import JWTMiddleware, DEMO_TOKEN, DEMO_USER_ID

TEST_SECRET = "test-jwt-secret-for-unit-tests"
TEST_SUPABASE_URL = "https://test.supabase.co"
TEST_ISS = f"{TEST_SUPABASE_URL}/auth/v1"
TEST_USER_ID = "12345678-1234-1234-1234-123456789012"

# Two EC keys let us exercise kid-based selection and rotation for real.
_EC_KEY_1 = ec.generate_private_key(ec.SECP256R1())
_EC_KEY_2 = ec.generate_private_key(ec.SECP256R1())
_EC_KEYS = {
    "kid-1": _EC_KEY_1,
    "kid-2": _EC_KEY_2,
}


def _fake_jwks_signing_key(token: str, base_url: str):
    """Emulates PyJWKClient.get_signing_key_from_jwt without network:
    select the public key by kid, fail closed on unknown kid."""
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    key = _EC_KEYS.get(kid)
    if key is None:
        raise jwt.InvalidTokenError("unable to resolve signing key")
    return key.public_key()


@pytest.fixture(autouse=True)
def patch_jwks(monkeypatch):
    """All tests run offline — the JWKS network seam is stubbed."""
    monkeypatch.setattr(auth, "_jwks_signing_key", _fake_jwks_signing_key)


def _claims(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TEST_USER_ID,
        "email": "testuser@grantrx.local",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": TEST_ISS,
        "exp": now + timedelta(hours=1),
        "iat": now,
    }
    payload.update(overrides)
    return payload


def _es256_token(kid: str = "kid-1", key=_EC_KEY_1, **claims) -> str:
    headers = {"kid": kid, "typ": "JWT"}
    return jwt.encode(_claims(**claims), key, algorithm="ES256", headers=headers)


def _hs256_token(secret: str = TEST_SECRET, **claims) -> str:
    return jwt.encode(_claims(**claims), secret, algorithm="HS256")


@pytest.fixture
def prod_app():
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

    with patch.dict(os.environ, {
        "ENVIRONMENT": "production",
        "SUPABASE_JWT_SECRET": TEST_SECRET,
        "SUPABASE_URL": TEST_SUPABASE_URL,
    }):
        yield app


@pytest.fixture
def client(prod_app):
    return TestClient(prod_app)


def _get(client, token: str):
    return client.get("/protected", headers={"Authorization": f"Bearer {token}"})


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

class TestAcceptedTokens:
    def test_valid_hs256_accepted(self, client):
        resp = _get(client, _hs256_token())
        assert resp.status_code == 200
        assert resp.json()["user_id"] == TEST_USER_ID

    def test_valid_es256_accepted(self, client):
        resp = _get(client, _es256_token())
        assert resp.status_code == 200
        assert resp.json()["user_id"] == TEST_USER_ID

    def test_kid_selection_picks_matching_key(self, client):
        """kid=kid-2 must verify against key 2, not key 1."""
        resp = _get(client, _es256_token(kid="kid-2", key=_EC_KEY_2))
        assert resp.status_code == 200

    def test_rotation_both_keys_accepted(self, client):
        """Both current and rotated keys resolve by kid."""
        assert _get(client, _es256_token(kid="kid-1", key=_EC_KEY_1)).status_code == 200
        assert _get(client, _es256_token(kid="kid-2", key=_EC_KEY_2)).status_code == 200


# ---------------------------------------------------------------------------
# Rejection paths — all fail closed with 401
# ---------------------------------------------------------------------------

class TestRejectedTokens:
    def test_unknown_kid_rejected(self, client):
        other = ec.generate_private_key(ec.SECP256R1())
        token = _es256_token(kid="kid-unknown", key=other)
        assert _get(client, token).status_code == 401

    def test_unsupported_alg_rejected(self, client):
        token = jwt.encode(_claims(), TEST_SECRET, algorithm="HS512")
        assert _get(client, token).status_code == 401

    def test_alg_none_rejected(self, client):
        token = jwt.encode(_claims(), None, algorithm="none")
        assert _get(client, token).status_code == 401

    def test_es256_wrong_key_rejected(self, client):
        wrong = ec.generate_private_key(ec.SECP256R1())
        # Token signed by `wrong` but kid claims kid-1 → signature won't verify
        headers = {"kid": "kid-1", "typ": "JWT"}
        token = jwt.encode(_claims(), wrong, algorithm="ES256", headers=headers)
        assert _get(client, token).status_code == 401

    def test_hs256_wrong_secret_rejected(self, client):
        token = _hs256_token(secret="a-different-secret")
        assert _get(client, token).status_code == 401

    def test_wrong_audience_rejected(self, client):
        assert _get(client, _es256_token(aud="service_role")).status_code == 401
        assert _get(client, _hs256_token(aud="service_role")).status_code == 401

    def test_wrong_issuer_rejected(self, client):
        bad_iss = "https://evil.example.com/auth/v1"
        assert _get(client, _es256_token(iss=bad_iss)).status_code == 401
        assert _get(client, _hs256_token(iss=bad_iss)).status_code == 401

    def test_expired_rejected(self, client):
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        assert _get(client, _es256_token(exp=past)).status_code == 401
        assert _get(client, _hs256_token(exp=past)).status_code == 401

    def test_malformed_token_rejected(self, client):
        assert _get(client, "not.a.jwt").status_code == 401
        assert _get(client, DEMO_TOKEN).status_code == 401

    def test_missing_bearer_rejected(self, client):
        assert client.get("/protected").status_code == 401


# ---------------------------------------------------------------------------
# Configuration failures — must not authenticate
# ---------------------------------------------------------------------------

class TestConfigurationFailures:
    def test_missing_supabase_url_fails_closed(self, prod_app):
        with patch.dict(os.environ, {"SUPABASE_URL": ""}):
            client = TestClient(prod_app)
            resp = _get(client, _hs256_token())
        assert resp.status_code in (401, 500)
        assert resp.json()["detail"] != "ok"

    def test_missing_jwt_secret_fails_closed_for_hs256(self, prod_app):
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": ""}):
            client = TestClient(prod_app)
            resp = _get(client, _hs256_token())
        assert resp.status_code in (401, 500)

    def test_asymmetric_does_not_need_jwt_secret(self, client):
        """JWKS verification must not depend on the shared secret."""
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": ""}):
            resp = _get(client, _es256_token())
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# SUPABASE_URL normalization
# ---------------------------------------------------------------------------

class TestSupabaseUrlNormalization:
    def test_trailing_slash_removed(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co/")
        assert auth._supabase_base_url() == "https://x.supabase.co"

    def test_path_rejected(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co/rest/v1")
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert auth._supabase_base_url() is None

    def test_http_rejected_in_production(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert auth._supabase_base_url() is None

    def test_http_allowed_in_dev(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("ALLOW_DEMO_AUTH", "true")
        assert auth._supabase_base_url() == "http://localhost:54321"

    def test_empty_and_malformed_rejected(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        for bad in ("", "   ", "not-a-url", "ftp://x.supabase.co"):
            monkeypatch.setenv("SUPABASE_URL", bad)
            assert auth._supabase_base_url() is None


# ---------------------------------------------------------------------------
# Dev-mode protections unchanged
# ---------------------------------------------------------------------------

class TestDevModeProtections:
    def test_demo_token_rejected_in_production(self, client):
        assert _get(client, DEMO_TOKEN).status_code == 401

    def test_missing_config_without_env_fails_closed(self, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("ALLOW_DEMO_AUTH", raising=False)
        monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
        monkeypatch.setenv("SUPABASE_URL", TEST_SUPABASE_URL)
        app = FastAPI()
        app.add_middleware(JWTMiddleware)

        @app.get("/protected")
        def protected(request: Request):
            return {"ok": True}

        assert TestClient(app).get("/protected").status_code == 401

    def test_health_still_public(self, client):
        assert client.get("/health").status_code == 200

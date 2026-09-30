"""Central runtime configuration for GrantRx URLs and branded identities.

Production deployments should set APP_URL and API_BASE_URL explicitly. Localhost
is the only built-in fallback so missing production configuration cannot silently
send users to an obsolete deployment or domain.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse


def _url_env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"{name} must be an absolute http(s) URL")
    return value


APP_URL = _url_env("APP_URL", "http://localhost:3000")
API_BASE_URL = _url_env("API_BASE_URL", os.getenv("APP_BASE_URL", "http://localhost:8000"))
PORTAL_RETURN_URL = _url_env("PORTAL_RETURN_URL", APP_URL)

TRANSACTIONAL_FROM_EMAIL = os.getenv("TRANSACTIONAL_FROM_EMAIL", "hello@grantrx.com")
DIGEST_FROM_EMAIL = os.getenv("DIGEST_FROM_EMAIL", "digest@grantrx.com")
PRIVACY_EMAIL = os.getenv("PRIVACY_EMAIL", "privacy@grantrx.com")
CALENDAR_UID_DOMAIN = os.getenv("CALENDAR_UID_DOMAIN", "grantrx.com").strip() or "grantrx.com"


def allowed_origins() -> list[str]:
    """Return explicit CORS origins, with safe localhost defaults for development."""
    raw = os.getenv("ALLOWED_ORIGINS", "")
    if raw.strip():
        return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    return ["http://localhost:3000", "http://127.0.0.1:3000"]

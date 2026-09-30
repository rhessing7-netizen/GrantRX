"""Signed marketing-unsubscribe tokens for EdFintia-generated email.

EdFintia's own marketing/digest emails (deadline digest, re-engagement) must
carry a functional unsubscribe link. Recipients must be able to opt out
WITHOUT logging in, so the link carries a bearer credential — but that
credential must not be a raw user id, an email address, or an auth JWT.

Token format:

    {user_uuid}.{hex_hmac_sha256}

where the HMAC is computed over the purpose-bound message
``edfintia:marketing-unsubscribe:{user_uuid}``. The signature authorizes
exactly one narrow action — setting ``Profile.marketing_opt_in = False`` —
for exactly one user. It cannot opt anyone in, cannot touch any other field,
and cannot be minted or altered without the server-side signing secret.

Signing key: ``MARKETING_UNSUBSCRIBE_SECRET`` is preferred; when unset the
existing ``SUPABASE_JWT_SECRET`` is reused so every real deployment is already
configured. The purpose prefix makes these tokens a different protocol from
Supabase auth JWTs — a JWT can never verify as an unsubscribe token and vice
versa. If neither secret is configured every function fails closed: no token
is minted and verification rejects everything.

Expiration: none. The single action this token authorizes is idempotent and
one-directional (opt-out only), so replay is harmless and links in older
emails keep working. Rotation of the signing secret invalidates outstanding
links — acceptable trade-off documented here.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional
from urllib.parse import quote
from uuid import UUID

from ..config import APP_URL

logger = logging.getLogger(__name__)

_PURPOSE = "edfintia:marketing-unsubscribe"


def _signing_secret() -> Optional[str]:
    """Return the configured signing secret, or None when unconfigured."""
    secret = os.getenv("MARKETING_UNSUBSCRIBE_SECRET") or os.getenv(
        "SUPABASE_JWT_SECRET"
    )
    if not secret:
        return None
    secret = secret.strip()
    return secret or None


def signing_configured() -> bool:
    """True when a signing secret is available for mint/verify."""
    return _signing_secret() is not None


def _signature(user_id: str, secret: str) -> str:
    message = f"{_PURPOSE}:{user_id}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def make_unsubscribe_token(user_id) -> Optional[str]:
    """Mint a signed unsubscribe token for ``user_id``.

    Returns None when no signing secret is configured — callers must treat
    that as a hard failure for marketing sends (never send marketing email
    without a functional opt-out link).
    """
    secret = _signing_secret()
    if not secret:
        return None
    uid = str(user_id)
    return f"{uid}.{_signature(uid, secret)}"


def verify_unsubscribe_token(token: Optional[str]) -> Optional[UUID]:
    """Verify a token and return the bound user id, or None if invalid.

    Constant-time comparison; purpose-bound signature; rejects malformed,
    tampered, or cross-secret tokens. Returns None (never raises) so the
    endpoint can respond with a generic client-safe error.
    """
    if not token or "." not in token:
        return None
    uid, _, sig = token.rpartition(".")
    secret = _signing_secret()
    if not secret or not uid or not sig:
        return None
    if not hmac.compare_digest(sig, _signature(uid, secret)):
        return None
    try:
        return UUID(uid)
    except (ValueError, AttributeError):
        return None


def build_unsubscribe_url(user_id) -> Optional[str]:
    """Absolute URL for the branded unsubscribe confirmation page."""
    token = make_unsubscribe_token(user_id)
    if not token:
        return None
    return f"{APP_URL}/unsubscribe?token={quote(token)}"

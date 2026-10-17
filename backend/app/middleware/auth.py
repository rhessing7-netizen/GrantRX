import logging
import os
from urllib.parse import urlparse
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    # Onboarding live-matching projection runs before a profile/session exists
    "/api/scholarships/match-preview",
    # Public discovery showcase — a fixed daily sample of discoverable
    # catalog records for signed-out visitors (read-only, no user data)
    "/api/scholarships/showcase",
    # Public early-access / waitlist signup (pre-launch, no account required)
    "/api/v1/early-access",
    # Signed marketing unsubscribe — the email link IS the credential;
    # recipients must be able to opt out without logging in first.
    "/api/v1/marketing/unsubscribe",
}

PUBLIC_PREFIXES = (
    "/api/calendar/feed.ics",
    "/api/billing/webhook",
    # Public opportunity detail — read-only, discoverable records only.
    # Trailing slash scopes the prefix to the detail route; the sibling
    # /api/scholarships/* authenticated endpoints stay protected.
    "/api/scholarships/showcase/",
)

# ---------------------------------------------------------------------------
# Dev-mode demo user
# ---------------------------------------------------------------------------

DEMO_TOKEN = "grantrx-dev-demo"
DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DEMO_USER_EMAIL = "demo@grantrx.local"

# Explicit asymmetric allowlist for Supabase's JWKS-based signing keys
# (ES256 today; the rest cover Supabase/PyJWT asymmetric options so a future
# project-side algorithm change doesn't silently break auth). The JWT header
# only selects the verifier — trust is established by signature + claims.
ASYMMETRIC_ALGORITHMS = frozenset({
    "ES256", "ES384", "ES512",
    "RS256", "RS384", "RS512",
    "PS256", "PS384", "PS512",
    "EdDSA",
})

_JWKS_CLIENT: jwt.PyJWKClient | None = None
_JWKS_URI: str | None = None


def _supabase_base_url() -> str | None:
    """Normalized SUPABASE_URL (scheme://host, no path) for issuer + JWKS.

    Returns None for unset/malformed values, non-http(s) schemes, URLs with a
    path (e.g. a pasted /rest/v1 endpoint), and http:// outside dev/test —
    callers must fail closed rather than verify against a guess.
    """
    raw = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        return None
    if parsed.scheme == "http" and not _is_dev_mode():
        return None
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _jwks_signing_key(token: str, base_url: str):
    """Resolve the public signing key for a token via Supabase's JWKS.

    PyJWKClient caches the key set and refetches on unknown kid, covering
    Supabase signing-key rotation. One client per URI, created lazily — no
    network I/O happens on the HS256 path.
    """
    global _JWKS_CLIENT, _JWKS_URI
    uri = f"{base_url}/auth/v1/.well-known/jwks.json"
    if _JWKS_CLIENT is None or _JWKS_URI != uri:
        _JWKS_CLIENT = jwt.PyJWKClient(
            uri, cache_keys=True, lifespan=300, cache_jwk_set=True,
        )
        _JWKS_URI = uri
    try:
        return _JWKS_CLIENT.get_signing_key_from_jwt(token).key
    except (jwt.PyJWKClientError, jwt.PyJWKSetError, jwt.DecodeError) as e:
        # Unresolvable kid, malformed JWK set, or unreachable JWKS — all fail
        # closed as an invalid token, never as authentication.
        raise jwt.InvalidTokenError("unable to resolve signing key") from e


def _is_dev_mode() -> bool:
    """Check if the server is running in development mode."""
    environment = os.getenv("ENVIRONMENT", "production").lower()
    allow_demo = os.getenv("ALLOW_DEMO_AUTH", "false").lower() in ("1", "true", "yes")
    return environment in ("development", "dev", "test", "testing") and allow_demo


class User:
    def __init__(self, id: UUID, email: str | None, role: str):
        self.id = id
        self.email = email
        self.role = role


class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        request.state.user = None

        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Public prefix-based paths (e.g. .ics feed, Stripe webhook)
        if any(request.url.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return await call_next(request)

        auth_header = request.headers.get("authorization")

        # ------------------------------------------------------------------
        # Dev-mode fallback: accept demo token or missing auth header
        # ------------------------------------------------------------------
        if _is_dev_mode():
            if not auth_header or not auth_header.lower().startswith("bearer "):
                logger.warning(
                    "DEV MODE: No auth header — injecting demo user %s for %s",
                    DEMO_USER_ID,
                    request.url.path,
                )
                request.state.user = User(
                    id=DEMO_USER_ID,
                    email=DEMO_USER_EMAIL,
                    role="authenticated",
                )
                return await call_next(request)

            token = auth_header[7:].strip()
            if token == DEMO_TOKEN:
                logger.debug("DEV MODE: Demo token accepted for %s", request.url.path)
                request.state.user = User(
                    id=DEMO_USER_ID,
                    email=DEMO_USER_EMAIL,
                    role="authenticated",
                )
                return await call_next(request)
        else:
            # Production: require auth header
            if not auth_header or not auth_header.lower().startswith("bearer "):
                return JSONResponse(
                    {"detail": "Missing authorization header"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

        # ------------------------------------------------------------------
        # Standard JWT validation (both dev and prod)
        #
        # SUPABASE_URL is required on every path: the token's issuer must equal
        # {SUPABASE_URL}/auth/v1. The unverified header only selects WHICH
        # verifier to use — HS256 → shared secret (legacy projects), an
        # asymmetric allowlist → Supabase JWKS (modern signing keys), anything
        # else → fail closed as invalid.
        # ------------------------------------------------------------------
        supabase_url = _supabase_base_url()
        if not supabase_url:
            logger.error(
                "SUPABASE_URL missing/malformed — cannot validate JWT issuer"
            )
            return JSONResponse(
                {"detail": "JWT validation not configured"},
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        token = auth_header[7:].strip()
        try:
            alg = jwt.get_unverified_header(token).get("alg")
        except jwt.InvalidTokenError:
            alg = None

        key: object | None = None
        algorithms: list[str] = []
        if alg == "HS256":
            secret = os.getenv("SUPABASE_JWT_SECRET")
            if not secret:
                return JSONResponse(
                    {"detail": "JWT secret not configured"},
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            key = secret
            algorithms = ["HS256"]
        elif alg in ASYMMETRIC_ALGORITHMS:
            algorithms = [alg]
            try:
                key = _jwks_signing_key(token, supabase_url)
            except jwt.InvalidTokenError:
                key = None  # resolved below as an invalid token
        # Missing/unsupported/"none" alg: key stays None → invalid token path.

        payload: dict | None = None
        expired = False
        if key is not None:
            try:
                payload = jwt.decode(
                    token,
                    key,
                    algorithms=algorithms,
                    audience="authenticated",
                    issuer=f"{supabase_url}/auth/v1",
                )
            except jwt.ExpiredSignatureError:
                expired = True
            except jwt.InvalidTokenError:
                payload = None

        if expired:
            # In dev mode, fall back to demo user if JWT is expired
            if _is_dev_mode():
                logger.warning(
                    "DEV MODE: Expired JWT — falling back to demo user for %s",
                    request.url.path,
                )
                request.state.user = User(
                    id=DEMO_USER_ID,
                    email=DEMO_USER_EMAIL,
                    role="authenticated",
                )
                return await call_next(request)
            return JSONResponse(
                {"detail": "Token expired"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        if payload is None:
            # In dev mode, fall back to demo user if JWT is invalid
            if _is_dev_mode():
                logger.warning(
                    "DEV MODE: Invalid JWT — falling back to demo user for %s",
                    request.url.path,
                )
                request.state.user = User(
                    id=DEMO_USER_ID,
                    email=DEMO_USER_EMAIL,
                    role="authenticated",
                )
                return await call_next(request)
            return JSONResponse(
                {"detail": "Invalid token"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        sub = payload.get("sub")
        if not sub:
            if _is_dev_mode():
                logger.warning(
                    "DEV MODE: JWT missing sub — falling back to demo user for %s",
                    request.url.path,
                )
                request.state.user = User(
                    id=DEMO_USER_ID,
                    email=DEMO_USER_EMAIL,
                    role="authenticated",
                )
                return await call_next(request)
            return JSONResponse(
                {"detail": "Token missing subject claim"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        request.state.user = User(
            id=UUID(sub),
            email=payload.get("email"),
            role=payload.get("role", "authenticated"),
        )

        return await call_next(request)


security = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    _credentials=Depends(security),
) -> User:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user

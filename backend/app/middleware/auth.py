import logging
import os
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
}

PUBLIC_PREFIXES = (
    "/api/calendar/feed.ics",
    "/api/billing/webhook",
)

# ---------------------------------------------------------------------------
# Dev-mode demo user
# ---------------------------------------------------------------------------

DEMO_TOKEN = "grantrx-dev-demo"
DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DEMO_USER_EMAIL = "demo@grantrx.local"


def _is_dev_mode() -> bool:
    """Check if the server is running in development mode."""
    return os.getenv("ENVIRONMENT", "development").lower() in ("development", "dev", "test", "testing")


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
        # ------------------------------------------------------------------
        secret = os.getenv("SUPABASE_JWT_SECRET")
        if not secret:
            return JSONResponse(
                {"detail": "JWT secret not configured"},
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        token = auth_header[7:].strip()
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError:
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
        except jwt.InvalidTokenError:
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

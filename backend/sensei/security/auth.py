from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from sensei.config import settings

logger = logging.getLogger(__name__)


def _extract_token(request: Request) -> str | None:
    """Extract auth token from Authorization header or query param."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.query_params.get("token")


def check_auth(request: Request) -> bool:
    """Check if a request is authenticated."""
    if not settings.auth_enabled:
        return True
    token = _extract_token(request)
    if not token or not settings.auth_token:
        return False
    return hmac.compare_digest(token, settings.auth_token)


class AuthMiddleware(BaseHTTPMiddleware):
    """Token-based authentication middleware."""

    # Paths that don't require auth
    PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}
    PUBLIC_PREFIXES = ("/api/health", "/api/auth/")

    async def dispatch(self, request: Request, call_next):
        if not settings.auth_enabled:
            return await call_next(request)

        path = request.url.path
        if path in self.PUBLIC_PATHS or any(path.startswith(p) for p in self.PUBLIC_PREFIXES):
            return await call_next(request)

        if not check_auth(request):
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized", "detail": "Valid auth token required"},
            )

        return await call_next(request)


def generate_token() -> str:
    """Generate a secure random auth token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token for secure storage."""
    return hashlib.sha256(token.encode()).hexdigest()

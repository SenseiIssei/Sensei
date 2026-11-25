from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import ClassVar

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from sensei.config import settings

logger = logging.getLogger(__name__)


def _presented_tokens(request: HTTPConnection) -> list[str]:
    """Everywhere a Sensei token may be.

    ``X-Sensei-Token`` is the one that always works: on the gateway the other
    two headers usually carry the provider's key, which Sensei passes on.
    """
    auth_header = request.headers.get("Authorization", "")
    found = [
        request.headers.get("X-Sensei-Token"),
        auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else None,
        request.headers.get("x-api-key"),
        request.query_params.get("token"),
    ]
    return [t for t in found if t]


def check_auth(request: HTTPConnection) -> bool:
    """Check if a request is authenticated."""
    if not settings.auth_enabled:
        return True
    if not settings.auth_token:
        return False
    # Bytes: compare_digest refuses non-ASCII str, which turned a token with an
    # umlaut in it into a 500 instead of a 401.
    expected = settings.auth_token.encode()
    return any(hmac.compare_digest(t.encode(), expected) for t in _presented_tokens(request))


class AuthMiddleware:
    """Token-based authentication.

    Plain ASGI rather than Starlette's BaseHTTPMiddleware, which hands a
    WebSocket straight through (so the chat socket was open to everyone with
    auth turned on) and turns a response that broke off into one that ended.
    """

    # Paths that don't require auth
    PUBLIC_PATHS: ClassVar[set[str]] = {"/", "/health", "/docs", "/openapi.json", "/redoc"}
    # /hooks/ answers only loopback callers that are not web pages (see
    # routers/hooks.py), and the hook runners that call it have no way to
    # present a Sensei token — a 401 there would silently disable compression.
    PUBLIC_PREFIXES = ("/api/health", "/api/auth/", "/hooks/")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not settings.auth_enabled or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path in self.PUBLIC_PATHS or path.startswith(self.PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return
        if check_auth(HTTPConnection(scope)):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": "Unauthorized"})
            return
        refusal = JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "detail": "Valid auth token required"},
        )
        await refusal(scope, receive, send)


def generate_token() -> str:
    """Generate a secure random auth token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token for secure storage."""
    return hashlib.sha256(token.encode()).hexdigest()

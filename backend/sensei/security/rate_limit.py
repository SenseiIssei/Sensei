from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock

from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sensei.config import settings
from sensei.security.urls import is_loopback


@dataclass
class RateBucket:
    requests: list[float] = field(default_factory=list)

    def add(self, timestamp: float) -> None:
        self.requests.append(timestamp)

    def cleanup(self, window: float, now: float) -> None:
        self.requests = [t for t in self.requests if now - t < window]

    @property
    def count(self) -> int:
        return len(self.requests)


class RateLimiter:
    """In-memory sliding window rate limiter.

    Limits requests per client IP within a configurable time window.
    Thread-safe for use with async frameworks.
    """

    def __init__(
        self,
        max_requests: int | None = None,
        window_seconds: int | None = None,
    ):
        self.max_requests = max_requests or settings.rate_limit_requests
        self.window_seconds = window_seconds or settings.rate_limit_window_seconds
        self._buckets: dict[str, RateBucket] = defaultdict(RateBucket)
        self._lock = Lock()

    def check(self, client_id: str) -> tuple[bool, int, int]:
        """Check if a client is within rate limits.

        Returns:
            Tuple of (allowed, remaining, retry_after_seconds)
        """
        if not settings.rate_limit_enabled:
            return True, self.max_requests, 0

        now = time.time()

        with self._lock:
            bucket = self._buckets[client_id]
            bucket.cleanup(self.window_seconds, now)

            if bucket.count >= self.max_requests:
                # Calculate retry-after
                oldest = bucket.requests[0] if bucket.requests else now
                retry_after = int(self.window_seconds - (now - oldest)) + 1
                return False, 0, max(1, retry_after)

            bucket.add(now)
            remaining = self.max_requests - bucket.count
            return True, remaining, 0

    def reset(self, client_id: str) -> None:
        with self._lock:
            self._buckets.pop(client_id, None)

    def reset_all(self) -> None:
        """Forget every client. Used to isolate tests from one another."""
        with self._lock:
            self._buckets.clear()

    def stats(self) -> dict[str, int]:
        """Return rate limiter statistics."""
        with self._lock:
            return {
                "tracked_clients": len(self._buckets),
                "max_requests": self.max_requests,
                "window_seconds": self.window_seconds,
            }


# Global rate limiter instance
rate_limiter = RateLimiter()


_UNLIMITED = frozenset({"/", "/health", "/docs", "/openapi.json", "/redoc"})
_FORWARDED = ("x-forwarded-for", "forwarded", "x-real-ip")


def _is_own_agent(conn: HTTPConnection) -> bool:
    """A coding agent on this machine, using the gateway or the hooks.

    The limit protects a server other people can reach. Counted against an
    agent it did harm: one Claude Code session with a few subagents makes more
    than 60 model calls and tool calls a minute, all from 127.0.0.1, and
    request 61 came back as 429 from Sensei rather than from the provider.
    Behind a reverse proxy everybody is 127.0.0.1, so a forwarded request is
    not exempt.
    """
    if not conn.url.path.startswith(("/v1/", "/hooks/")):
        return False
    if any(name in conn.headers for name in _FORWARDED):
        return False
    return is_loopback(conn.client.host if conn.client else None)


class RateLimitMiddleware:
    """Plain ASGI, so a response that breaks off reaches the client as broken."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return
        conn = HTTPConnection(scope)
        if scope["path"] in _UNLIMITED or _is_own_agent(conn):
            await self.app(scope, receive, send)
            return

        allowed, remaining, retry_after = rate_limiter.check(
            conn.client.host if conn.client else "unknown"
        )
        limit = str(settings.rate_limit_requests)
        if not allowed:
            refusal = JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded", "retry_after": retry_after},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Limit": limit,
                },
            )
            await refusal(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-RateLimit-Remaining"] = str(remaining)
                headers["X-RateLimit-Limit"] = limit
            await send(message)

        await self.app(scope, receive, with_headers)

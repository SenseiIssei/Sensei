from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

from sensei.config import settings


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

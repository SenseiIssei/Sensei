"""Process-wide aggregate of compression savings.

Powers the "money saved" dashboard. In-memory only — it counts tokens, never
prompt contents, and resets on restart (zero telemetry, nothing persisted).
"""
from __future__ import annotations

import threading
import time
from typing import Any

from sensei.config import settings


class SavingsTracker:
    """Thread-safe running total of tokens (and dollars) saved by compression."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = 0
        self.tokens_before = 0
        self.tokens_after = 0
        self.tokens_saved = 0
        self.blocks_compressed = 0
        self.started_at = time.time()

    def record(self, savings: dict[str, Any]) -> None:
        """Fold one request's savings dict (from the gateway) into the totals."""
        with self._lock:
            self.requests += 1
            self.tokens_before += int(savings.get("prompt_tokens_before", 0) or 0)
            self.tokens_after += int(savings.get("prompt_tokens_after", 0) or 0)
            self.tokens_saved += int(savings.get("tokens_saved", 0) or 0)
            self.blocks_compressed += int(savings.get("blocks_compressed", 0) or 0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            before, after, saved = self.tokens_before, self.tokens_after, self.tokens_saved
            requests, blocks, started = self.requests, self.blocks_compressed, self.started_at
        ratio = (after / before) if before else 1.0
        price = settings.usd_per_million_tokens
        return {
            "requests": requests,
            "tokens_before": before,
            "tokens_after": after,
            "tokens_saved": saved,
            "blocks_compressed": blocks,
            "compression_ratio": round(ratio, 4),
            "percent_saved": round((1 - ratio) * 100, 1) if before else 0.0,
            "estimated_cost_saved_usd": round(saved / 1_000_000 * price, 4),
            "price_per_million_usd": price,
            "since": started,
        }

    def reset(self) -> None:
        with self._lock:
            self.requests = 0
            self.tokens_before = 0
            self.tokens_after = 0
            self.tokens_saved = 0
            self.blocks_compressed = 0
            self.started_at = time.time()


_tracker: SavingsTracker | None = None


def get_savings_tracker() -> SavingsTracker:
    global _tracker
    if _tracker is None:
        _tracker = SavingsTracker()
    return _tracker

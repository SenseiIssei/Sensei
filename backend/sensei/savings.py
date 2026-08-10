"""What compression actually saved — the numbers behind the dashboard.

Two layers, deliberately:

**The tracker** is the running total since the process started. It is a handful
of integers behind a lock and it is what `X-Sensei-*` headers and `sensei stats`
have always read.

**The ledger** is a local SQLite file that survives a restart, so the question
"how much have I saved *in total*" has an answer that is not reset every time
you close a laptop lid. It records one row per request: a timestamp, which tool
sent it, which provider and model it went to, and four counters.

It stores no prompt text, no response text, no keys, and no identifiers beyond a
tool name taken from the User-Agent. Nothing is transmitted anywhere — the file
sits next to `.sensei_cache` and `.sensei_memory` and you can delete it. This is
the same promise as the rest of Sensei: `SENSEI_SAVINGS_PERSIST=false` turns it
off entirely and the totals go back to being per-process.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from sensei.config import settings

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    ts       REAL    NOT NULL,
    tool     TEXT    NOT NULL DEFAULT '',
    provider TEXT    NOT NULL DEFAULT '',
    model    TEXT    NOT NULL DEFAULT '',
    before   INTEGER NOT NULL DEFAULT 0,
    after    INTEGER NOT NULL DEFAULT 0,
    saved    INTEGER NOT NULL DEFAULT 0,
    blocks   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
"""

DAY = 86_400.0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class SavingsLedger:
    """Append-only local record of per-request savings.

    Every method swallows and logs sqlite errors. A dashboard that cannot write
    its history is an annoyance; a gateway that returns 500 because a disk is
    full is an outage. The proxy path must never fail because of bookkeeping.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._broken = False

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else settings.savings_db_path

    def _connect(self) -> sqlite3.Connection | None:
        if self._broken:
            return None
        if self._conn is not None:
            return self._conn
        try:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            # WAL so a reader (the dashboard polling) never blocks the writer
            # (the gateway on the hot path).
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Savings ledger unavailable (%s) — history disabled", exc)
            self._broken = True
            return None
        self._conn = conn
        return conn

    def append(
        self,
        savings: dict[str, Any],
        *,
        tool: str = "",
        provider: str = "",
        model: str = "",
    ) -> None:
        if not settings.savings_persist:
            return
        with self._lock:
            conn = self._connect()
            if conn is None:
                return
            try:
                conn.execute(
                    "INSERT INTO events (ts, tool, provider, model, before, after, saved, blocks)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        time.time(),
                        tool[:64],
                        provider[:64],
                        model[:128],
                        _int(savings.get("prompt_tokens_before")),
                        _int(savings.get("prompt_tokens_after")),
                        _int(savings.get("tokens_saved")),
                        _int(savings.get("blocks_compressed")),
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                logger.warning("Could not append to the savings ledger: %s", exc)

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._lock:
            conn = self._connect()
            if conn is None:
                return []
            try:
                return conn.execute(sql, params).fetchall()
            except sqlite3.Error as exc:
                logger.warning("Savings ledger query failed: %s", exc)
                return []

    def totals(self, since: float | None = None) -> dict[str, Any]:
        rows = self._query(
            "SELECT COUNT(*), COALESCE(SUM(before),0), COALESCE(SUM(after),0),"
            " COALESCE(SUM(saved),0), COALESCE(SUM(blocks),0), MIN(ts)"
            " FROM events WHERE ts >= ?",
            (since or 0.0,),
        )
        if not rows:
            return _empty_totals()
        requests, before, after, saved, blocks, first = rows[0]
        return _shape(
            requests=_int(requests),
            before=_int(before),
            after=_int(after),
            saved=_int(saved),
            blocks=_int(blocks),
            since=float(first) if first else time.time(),
        )

    def daily(self, days: int = 30) -> list[dict[str, Any]]:
        """One bucket per calendar day, oldest first, gaps filled with zeroes.

        The gaps matter: a chart that silently skips the days you did not work
        compresses time and makes a quiet week look like a busy one.
        """
        days = max(1, min(days, 366))
        cutoff = time.time() - days * DAY
        rows = self._query(
            "SELECT CAST(ts / 86400 AS INTEGER) AS day, COALESCE(SUM(before),0),"
            " COALESCE(SUM(after),0), COALESCE(SUM(saved),0), COUNT(*)"
            " FROM events WHERE ts >= ? GROUP BY day ORDER BY day",
            (cutoff,),
        )
        by_day = {_int(r[0]): r for r in rows}
        today = int(time.time() // DAY)
        out: list[dict[str, Any]] = []
        for index in range(today - days + 1, today + 1):
            row = by_day.get(index)
            before, after, saved, requests = (
                (_int(row[1]), _int(row[2]), _int(row[3]), _int(row[4])) if row else (0, 0, 0, 0)
            )
            out.append(
                {
                    "date": time.strftime("%Y-%m-%d", time.gmtime(index * DAY)),
                    "tokens_before": before,
                    "tokens_after": after,
                    "tokens_saved": saved,
                    "requests": requests,
                    "estimated_cost_saved_usd": _usd(saved),
                }
            )
        return out

    def breakdown(self, dimension: str, *, limit: int = 12) -> list[dict[str, Any]]:
        """Totals grouped by tool, provider or model."""
        if dimension not in ("tool", "provider", "model"):
            raise ValueError(f"not a groupable dimension: {dimension}")
        rows = self._query(
            f"SELECT CASE WHEN {dimension} = '' THEN 'unknown' ELSE {dimension} END AS k,"  # noqa: S608
            " COALESCE(SUM(before),0), COALESCE(SUM(after),0), COALESCE(SUM(saved),0), COUNT(*)"
            " FROM events GROUP BY k ORDER BY SUM(saved) DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "key": str(row[0]),
                "tokens_before": _int(row[1]),
                "tokens_after": _int(row[2]),
                "tokens_saved": _int(row[3]),
                "requests": _int(row[4]),
                "percent_saved": _percent(_int(row[1]), _int(row[2])),
                "estimated_cost_saved_usd": _usd(_int(row[3])),
            }
            for row in rows
        ]

    def prune(self) -> int:
        """Drop rows past the retention window. Returns how many went."""
        cutoff = time.time() - max(1, settings.savings_retention_days) * DAY
        with self._lock:
            conn = self._connect()
            if conn is None:
                return 0
            try:
                cursor = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
                conn.commit()
                return cursor.rowcount or 0
            except sqlite3.Error as exc:
                logger.warning("Could not prune the savings ledger: %s", exc)
                return 0

    def clear(self) -> None:
        with self._lock:
            conn = self._connect()
            if conn is None:
                return
            try:
                conn.execute("DELETE FROM events")
                conn.commit()
            except sqlite3.Error as exc:
                logger.warning("Could not clear the savings ledger: %s", exc)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


# ── Shared shaping so the API answers the same shape everywhere ─────────────


def _usd(saved: int) -> float:
    return round(saved / 1_000_000 * settings.usd_per_million_tokens, 4)


def _percent(before: int, after: int) -> float:
    return round((1 - after / before) * 100, 1) if before else 0.0


def _shape(
    *, requests: int, before: int, after: int, saved: int, blocks: int, since: float
) -> dict[str, Any]:
    ratio = (after / before) if before else 1.0
    return {
        "requests": requests,
        "tokens_before": before,
        "tokens_after": after,
        "tokens_saved": saved,
        "blocks_compressed": blocks,
        "compression_ratio": round(ratio, 4),
        "percent_saved": round((1 - ratio) * 100, 1) if before else 0.0,
        "estimated_cost_saved_usd": _usd(saved),
        "price_per_million_usd": settings.usd_per_million_tokens,
        "since": since,
    }


def _empty_totals() -> dict[str, Any]:
    return _shape(requests=0, before=0, after=0, saved=0, blocks=0, since=time.time())


class SavingsTracker:
    """Thread-safe running total of tokens (and dollars) saved by compression."""

    def __init__(self, ledger: SavingsLedger | None = None) -> None:
        self._lock = threading.Lock()
        self.requests = 0
        self.tokens_before = 0
        self.tokens_after = 0
        self.tokens_saved = 0
        self.blocks_compressed = 0
        self.started_at = time.time()
        self.ledger = ledger or SavingsLedger()

    def record(
        self,
        savings: dict[str, Any],
        *,
        tool: str = "",
        provider: str = "",
        model: str = "",
    ) -> None:
        """Fold one request's savings dict (from the gateway) into the totals."""
        with self._lock:
            self.requests += 1
            self.tokens_before += _int(savings.get("prompt_tokens_before"))
            self.tokens_after += _int(savings.get("prompt_tokens_after"))
            self.tokens_saved += _int(savings.get("tokens_saved"))
            self.blocks_compressed += _int(savings.get("blocks_compressed"))
        self.ledger.append(savings, tool=tool, provider=provider, model=model)

    def snapshot(self) -> dict[str, Any]:
        """Totals for this process only — what the headers have always shown."""
        with self._lock:
            return _shape(
                requests=self.requests,
                before=self.tokens_before,
                after=self.tokens_after,
                saved=self.tokens_saved,
                blocks=self.blocks_compressed,
                since=self.started_at,
            )

    def lifetime(self) -> dict[str, Any]:
        """Totals across every run recorded in the ledger."""
        return self.ledger.totals()

    def reset(self) -> None:
        """Zero the in-memory counters. The ledger is deliberately untouched —
        `sensei stats --forget` is the one that throws history away."""
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


def reset_savings_tracker() -> None:
    """Drop the singleton. Used by tests, which need a fresh ledger per case."""
    global _tracker
    if _tracker is not None:
        _tracker.ledger.close()
    _tracker = None

"""What the gateway must remember across a restart, per conversation.

Two things the client never sends back in the form the provider saw:

- **Answered retrieves.** When the client answered a ``sensei_retrieve`` call
  with "no such tool", the gateway forwarded the original instead. Every later
  request must forward the *same* text, or the history changes under the
  model's feet — and the original may since have left the CCR store.
- **Hidden exchanges** (only with ``gateway_retrieve_intercept``): the real
  call/result/answer sequence behind a merged message.

Both are kept in a small SQLite file next to the CCR store, scoped by
conversation lineage *and* by a keyed tag of the credential, so one user's
conversation can never be completed with another's. Entries expire after
``gateway_state_ttl_hours``. With ``gateway_state_persist=false`` (or a broken
disk) the same API works from memory only.

This file holds original tool output — the same kind of content the CCR store
already keeps on disk — and nothing else: no prompts beyond those results, no
keys (credentials are only ever an HMAC under a random key stored here).
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from sensei.config import SENSEI_HOME, settings

logger = logging.getLogger(__name__)

clock = time.time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (
    scope TEXT NOT NULL,
    kind  TEXT NOT NULL,
    key   TEXT NOT NULL,
    body  TEXT NOT NULL,
    ts    REAL NOT NULL,
    PRIMARY KEY (scope, kind, key)
);
CREATE INDEX IF NOT EXISTS items_ts ON items (ts);
"""

_MEMORY_LIMIT = 4096


class GatewayState:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._broken = False
        self._memory: OrderedDict[tuple[str, str, str], tuple[float, str]] = OrderedDict()
        self._secret: bytes | None = None

    @property
    def path(self) -> Path:
        if self._path is not None:
            return self._path
        if settings.gateway_state_db:
            return Path(settings.gateway_state_db).expanduser()
        return SENSEI_HOME / "gateway-state.db"

    def _connect(self) -> sqlite3.Connection | None:
        if not settings.gateway_state_persist or self._broken:
            return None
        if self._conn is not None:
            return self._conn
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Gateway state unavailable (%s) - keeping it in memory", exc)
            self._broken = True
            return None
        self._conn = conn
        return conn

    def _ttl(self) -> float:
        return max(1, settings.gateway_state_ttl_hours) * 3600.0

    # ---- credential tags ---------------------------------------------------

    def credential_tag(self, credential: str) -> str:
        """A stable, keyed tag for a credential. The credential is not stored."""
        with self._lock:
            if self._secret is None:
                self._secret = self._load_secret()
            key = self._secret
        return hmac.new(key, credential.encode("utf-8"), "sha256").hexdigest()[:32]

    def _load_secret(self) -> bytes:
        conn = self._connect()
        if conn is not None:
            try:
                row = conn.execute("SELECT v FROM meta WHERE k = 'secret'").fetchone()
                if row:
                    return bytes.fromhex(row[0])
                secret = secrets.token_bytes(32)
                conn.execute("INSERT INTO meta (k, v) VALUES ('secret', ?)", (secret.hex(),))
                conn.commit()
                return secret
            except (sqlite3.Error, ValueError) as exc:
                logger.warning("Gateway state secret unavailable: %s", exc)
        return secrets.token_bytes(32)

    # ---- items -------------------------------------------------------------

    def get(self, scope: str, kind: str, key: str) -> Any:
        now = clock()
        with self._lock:
            hit = self._memory.get((scope, kind, key))
            if hit is not None and now - hit[0] <= self._ttl():
                self._memory.move_to_end((scope, kind, key))
                return json.loads(hit[1])
            conn = self._connect()
            if conn is None:
                return None
            try:
                row = conn.execute(
                    "SELECT body, ts FROM items WHERE scope = ? AND kind = ? AND key = ?",
                    (scope, kind, key),
                ).fetchone()
            except sqlite3.Error as exc:
                logger.warning("Gateway state read failed: %s", exc)
                return None
        if row is None or now - float(row[1]) > self._ttl():
            return None
        return json.loads(row[0])

    def put(self, scope: str, kind: str, key: str, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False)
        now = clock()
        with self._lock:
            self._memory[(scope, kind, key)] = (now, body)
            self._memory.move_to_end((scope, kind, key))
            while len(self._memory) > _MEMORY_LIMIT:
                self._memory.popitem(last=False)
            conn = self._connect()
            if conn is None:
                return
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO items (scope, kind, key, body, ts) VALUES (?, ?, ?, ?, ?)",
                    (scope, kind, key, body, now),
                )
                conn.execute("DELETE FROM items WHERE ts < ?", (now - self._ttl(),))
                conn.commit()
            except sqlite3.Error as exc:
                logger.warning("Gateway state write failed: %s", exc)

    def forget_memory(self) -> None:
        """Drop the in-memory layer only — what a restart does. For tests."""
        with self._lock:
            self._memory.clear()
            self._secret = None
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def clear(self) -> None:
        with self._lock:
            self._memory.clear()
            conn = self._connect()
            if conn is not None:
                try:
                    conn.execute("DELETE FROM items")
                    conn.commit()
                except sqlite3.Error:
                    pass

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            self._secret = None


state = GatewayState()

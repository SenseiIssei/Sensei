from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from sensei.config import settings

logger = logging.getLogger(__name__)


class Session:
    """Represents a single user session with isolated data."""

    def __init__(
        self,
        session_id: str,
        user_id: str = "default",
        created_at: float | None = None,
        last_active: float | None = None,
        data: dict[str, Any] | None = None,
        on_change: Callable[["Session"], None] | None = None,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.created_at = created_at or time.time()
        self.last_active = last_active or time.time()
        self.data: dict[str, Any] = data or {}
        self._conversations: list[dict[str, Any]] = []
        # Called whenever the session mutates so the manager can persist it.
        self._on_change = on_change

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change(self)

    def touch(self) -> None:
        self.last_active = time.time()

    def is_expired(self, timeout_minutes: int) -> bool:
        return time.time() - self.last_active > timeout_minutes * 60

    def add_message(self, role: str, content: str) -> None:
        self._conversations.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })
        self.touch()
        self._changed()

    def get_messages(self) -> list[dict[str, Any]]:
        return list(self._conversations)

    def clear(self) -> None:
        self._conversations.clear()
        self.data.clear()
        self.touch()
        self._changed()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "data": self.data,
            "conversations": self._conversations,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        on_change: Callable[["Session"], None] | None = None,
    ) -> Session:
        sess = cls(
            session_id=data["session_id"],
            user_id=data.get("user_id", "default"),
            created_at=data.get("created_at"),
            last_active=data.get("last_active"),
            data=data.get("data", {}),
            on_change=on_change,
        )
        sess._conversations = data.get("conversations", [])
        return sess


class SessionManager:
    """Manages per-user sessions with local data isolation.

    Each user gets their own session with isolated conversation history.
    All data stays on the local machine — nothing is sent to external
    servers except the compressed prompt to the model provider.
    """

    def __init__(self, session_dir: Path | None = None, timeout_minutes: int | None = None):
        self.session_dir = session_dir or settings.session_path
        self.timeout_minutes = timeout_minutes or settings.session_timeout_minutes
        self._sessions: dict[str, Session] = {}
        self._load_sessions()

    def create_session(self, user_id: str = "default") -> Session:
        """Create a new isolated session for a user."""
        session_id = str(uuid.uuid4())
        session = Session(session_id=session_id, user_id=user_id, on_change=self._save_session)
        self._sessions[session_id] = session
        self._save_session(session)
        logger.info("Created session %s for user %s", session_id, user_id)
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID, checking expiry."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired(self.timeout_minutes):
            self.delete_session(session_id)
            return None
        session.touch()
        return session

    def get_or_create(self, session_id: str | None, user_id: str = "default") -> Session:
        """Get an existing session or create a new one."""
        if session_id:
            session = self.get_session(session_id)
            if session:
                return session
        return self.create_session(user_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its local data."""
        session = self._sessions.pop(session_id, None)
        if session:
            self._delete_session_file(session_id)
            logger.info("Deleted session %s", session_id)
            return True
        return False

    def list_sessions(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """List active sessions, optionally filtered by user."""
        sessions = []
        for sid, session in self._sessions.items():
            if session.is_expired(self.timeout_minutes):
                self.delete_session(sid)
                continue
            if user_id and session.user_id != user_id:
                continue
            sessions.append({
                "session_id": sid,
                "user_id": session.user_id,
                "created_at": session.created_at,
                "last_active": session.last_active,
            })
        return sessions

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count removed."""
        expired = [
            sid for sid, session in self._sessions.items()
            if session.is_expired(self.timeout_minutes)
        ]
        for sid in expired:
            self.delete_session(sid)
        return len(expired)

    def _save_session(self, session: Session) -> None:
        path = self.session_dir / f"{session.session_id}.json"
        try:
            path.write_text(
                json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("Failed to save session %s: %s", session.session_id, e)

    def _delete_session_file(self, session_id: str) -> None:
        path = self.session_dir / f"{session_id}.json"
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def _load_sessions(self) -> None:
        if not self.session_dir.exists():
            return
        for path in self.session_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                session = Session.from_dict(data, on_change=self._save_session)
                if not session.is_expired(self.timeout_minutes):
                    self._sessions[session.session_id] = session
                else:
                    path.unlink(missing_ok=True)
            except (json.JSONDecodeError, OSError, KeyError):
                continue
        logger.info("Loaded %d sessions from %s", len(self._sessions), self.session_dir)

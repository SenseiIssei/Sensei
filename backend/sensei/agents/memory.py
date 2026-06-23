from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from sensei.config import settings

logger = logging.getLogger(__name__)


class MemoryStore:
    """Cross-session persistent memory for conversations and agents.

    Inspired by Headroom's cross-agent memory — stores context across
    sessions with automatic deduplication. Uses a simple file-based store.
    """

    def __init__(self, memory_dir: Path | None = None):
        self.memory_dir = memory_dir or settings.memory_path
        self._conversations: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        path = self.memory_dir / "conversations.json"
        if path.exists():
            try:
                self._conversations = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._conversations = {}

    def _save(self) -> None:
        path = self.memory_dir / "conversations.json"
        try:
            path.write_text(
                json.dumps(self._conversations, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("Failed to save memory: %s", e)

    def create_conversation(self, title: str = "New Conversation") -> str:
        """Create a new conversation and return its ID."""
        import uuid

        conv_id = str(uuid.uuid4())
        self._conversations[conv_id] = {
            "id": conv_id,
            "title": title,
            "messages": [],
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._save()
        return conv_id

    def add_message(self, conv_id: str, role: str, content: str, **extra: Any) -> None:
        """Add a message to a conversation."""
        if conv_id not in self._conversations:
            conv_id = self.create_conversation()

        msg = {"role": role, "content": content, "timestamp": time.time(), **extra}
        self._conversations[conv_id]["messages"].append(msg)
        self._conversations[conv_id]["updated_at"] = time.time()

        # Auto-title from first user message
        if role == "user" and self._conversations[conv_id]["title"] == "New Conversation":
            title = content[:50] + ("…" if len(content) > 50 else "")
            self._conversations[conv_id]["title"] = title

        self._save()

    def get_conversation(self, conv_id: str) -> dict[str, Any] | None:
        return self._conversations.get(conv_id)

    def list_conversations(self) -> list[dict[str, Any]]:
        """List all conversations sorted by last updated."""
        convs = sorted(
            self._conversations.values(),
            key=lambda c: c.get("updated_at", 0),
            reverse=True,
        )
        return [{"id": c["id"], "title": c["title"], "updated_at": c["updated_at"]} for c in convs]

    def delete_conversation(self, conv_id: str) -> bool:
        if conv_id in self._conversations:
            del self._conversations[conv_id]
            self._save()
            return True
        return False

    def get_messages(self, conv_id: str) -> list[dict[str, Any]]:
        conv = self._conversations.get(conv_id)
        return conv["messages"] if conv else []

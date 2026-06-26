from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from sensei.agents.memory import MemoryStore

router = APIRouter(prefix="/conversations", tags=["conversations"])

# Shared memory store (initialized in main.py on startup).
_memory: MemoryStore | None = None


def init_conversations_deps(memory: MemoryStore) -> None:
    global _memory
    _memory = memory


@router.get("")
async def list_conversations() -> list[dict[str, Any]]:
    """List all conversations, most recently updated first."""
    if _memory is None:
        return []
    return _memory.list_conversations()


@router.get("/{conv_id}")
async def get_conversation(conv_id: str) -> dict[str, Any] | None:
    """Get a single conversation (with messages) by ID."""
    if _memory is None:
        return None
    return _memory.get_conversation(conv_id)


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str) -> dict[str, bool]:
    """Delete a conversation by ID."""
    if _memory is None:
        return {"deleted": False}
    return {"deleted": _memory.delete_conversation(conv_id)}

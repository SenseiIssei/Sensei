from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from sensei.agents.memory import MemoryStore
from sensei.agents.tools import ToolRegistry, retrieve_original_tool
from sensei.compression.ccr import CCRStore
from sensei.compression.router import ContentRouter
from sensei.config import settings
from sensei.models.base import ChatMessage, Role
from sensei.models.registry import get_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Shared state (initialized in main.py)
_memory: MemoryStore | None = None
_tool_registry: ToolRegistry | None = None
_content_router: ContentRouter | None = None


def init_chat_deps(
    memory: MemoryStore,
    tools: ToolRegistry,
    router_c: ContentRouter,
) -> None:
    global _memory, _tool_registry, _content_router
    _memory = memory
    _tool_registry = tools
    _content_router = router_c


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    message: str
    model: str
    tokens_saved: int = 0
    compression_ratio: float = 1.0


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a message and get a response (non-streaming)."""
    if _memory is None:
        raise RuntimeError("Chat dependencies not initialized")

    # Get or create conversation
    conv_id = request.conversation_id or _memory.create_conversation()

    # Build message list
    messages: list[ChatMessage] = []
    if request.system_prompt:
        messages.append(ChatMessage(role=Role.system, content=request.system_prompt))

    # Add conversation history
    for msg in _memory.get_messages(conv_id):
        messages.append(ChatMessage(role=Role(msg["role"]), content=msg["content"]))

    # Add new user message
    messages.append(ChatMessage(role=Role.user, content=request.message))
    _memory.add_message(conv_id, "user", request.message)

    # Compress messages
    msg_dicts = [{"role": m.role.value, "content": m.content} for m in messages]
    total_saved = 0
    if settings.compression_enabled and _content_router:
        compressed_msgs, results = _content_router.compress_messages(msg_dicts)
        total_saved = sum(r.tokens_saved for r in results)
        messages = [ChatMessage(role=Role(m["role"]), content=m["content"]) for m in compressed_msgs]

    # Get model provider and generate
    provider = await get_provider()
    completion = await provider.chat(
        messages=messages,
        model=request.model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )

    # Store assistant response
    _memory.add_message(conv_id, "assistant", completion.content)

    return ChatResponse(
        conversation_id=conv_id,
        message=completion.content,
        model=completion.model,
        tokens_saved=total_saved,
        compression_ratio=(
            completion.usage.compressed_prompt_tokens / completion.usage.prompt_tokens
            if completion.usage.prompt_tokens > 0
            else 1.0
        ),
    )


@router.websocket("/ws")
async def chat_stream(ws: WebSocket) -> None:
    """WebSocket endpoint for streaming chat."""
    await ws.accept()

    if _memory is None or _content_router is None:
        await ws.send_json({"type": "error", "content": "Server not initialized"})
        await ws.close()
        return

    try:
        while True:
            data = await ws.receive_text()
            try:
                request = json.loads(data)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "content": "Invalid JSON"})
                continue

            message = request.get("message", "")
            conv_id = request.get("conversation_id")
            model = request.get("model")
            temperature = request.get("temperature", 0.7)
            max_tokens = request.get("max_tokens", 4096)
            system_prompt = request.get("system_prompt")

            if not message:
                await ws.send_json({"type": "error", "content": "Empty message"})
                continue

            # Get or create conversation
            conv_id = conv_id or _memory.create_conversation()

            # Build messages
            messages: list[ChatMessage] = []
            if system_prompt:
                messages.append(ChatMessage(role=Role.system, content=system_prompt))

            for msg in _memory.get_messages(conv_id):
                messages.append(ChatMessage(role=Role(msg["role"]), content=msg["content"]))

            messages.append(ChatMessage(role=Role.user, content=message))
            _memory.add_message(conv_id, "user", message)

            # Compress
            msg_dicts = [{"role": m.role.value, "content": m.content} for m in messages]
            total_saved = 0
            if settings.compression_enabled:
                compressed_msgs, results = _content_router.compress_messages(msg_dicts)
                total_saved = sum(r.tokens_saved for r in results)
                messages = [
                    ChatMessage(role=Role(m["role"]), content=m["content"])
                    for m in compressed_msgs
                ]

            # Send metadata
            await ws.send_json({
                "type": "meta",
                "conversation_id": conv_id,
                "tokens_saved": total_saved,
                "compression_enabled": settings.compression_enabled,
            })

            # Stream response
            provider = await get_provider()
            full_response = ""

            try:
                async for token in provider.stream_chat(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    full_response += token
                    await ws.send_json({"type": "token", "content": token})
            except Exception as e:
                logger.error("Streaming error: %s", e)
                await ws.send_json({"type": "error", "content": str(e)})

            # Store assistant response
            if full_response:
                _memory.add_message(conv_id, "assistant", full_response)

            await ws.send_json({"type": "done"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        try:
            await ws.send_json({"type": "error", "content": str(e)})
            await ws.close()
        except Exception:
            pass


@router.get("/conversations")
async def list_conversations() -> list[dict[str, Any]]:
    """List all conversations."""
    if _memory is None:
        return []
    return _memory.list_conversations()


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str) -> dict[str, Any] | None:
    """Get a conversation by ID."""
    if _memory is None:
        return None
    return _memory.get_conversation(conv_id)


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str) -> dict[str, bool]:
    """Delete a conversation."""
    if _memory is None:
        return {"deleted": False}
    return {"deleted": _memory.delete_conversation(conv_id)}

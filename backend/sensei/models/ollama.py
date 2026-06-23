from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncIterator

import httpx

from sensei.config import settings
from sensei.models.base import (
    ChatCompletion,
    ChatMessage,
    ModelInfo,
    ModelProvider,
    ModelStatus,
    Role,
    UsageStats,
)

logger = logging.getLogger(__name__)


class OllamaProvider(ModelProvider):
    """Local model provider using Ollama — free, no API key required.

    Ollama runs models locally and exposes a REST API at localhost:11434.
    Supports any GGUF model including GLM-5.2 quantized variants.
    """

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
    ):
        self.host = (host or settings.ollama_host).rstrip("/")
        self.model = model or settings.ollama_model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.host,
                timeout=httpx.Timeout(300.0, connect=10.0),
            )
        return self._client

    def _format_messages(self, messages: list[ChatMessage]) -> list[dict]:
        return [{"role": msg.role.value, "content": msg.content} for msg in messages]

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> ChatCompletion | AsyncIterator[str]:
        if stream:
            return self.stream_chat(messages, model, temperature, max_tokens)

        client = await self._get_client()
        target_model = model or self.model

        payload = {
            "model": target_model,
            "messages": self._format_messages(messages),
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "stream": False,
        }

        resp = await client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        return ChatCompletion(
            id=str(uuid.uuid4()),
            model=data.get("model", target_model),
            content=data.get("message", {}).get("content", ""),
            role=Role.assistant,
            usage=UsageStats(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            ),
            finish_reason="stop",
        )

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        client = await self._get_client()
        target_model = model or self.model

        payload = {
            "model": target_model,
            "messages": self._format_messages(messages),
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "stream": True,
        }

        async with client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    if chunk.get("done"):
                        break
                    if content := chunk.get("message", {}).get("content"):
                        yield content
                except json.JSONDecodeError:
                    continue

    async def get_info(self) -> ModelInfo:
        available = await self.is_available()
        return ModelInfo(
            id=f"ollama:{self.model}",
            name=f"{self.model} (Ollama Local)",
            provider="local",
            backend="ollama",
            context_window=settings.local_context_size,
            status=ModelStatus.available if available else ModelStatus.unavailable,
            description=f"Local model via Ollama at {self.host} — free, no API key",
        )

    async def is_available(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags")
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            # Check if our model (or a prefix match) is available
            return any(self.model in m or m in self.model for m in models) if models else True
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """List all models available in Ollama."""
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags")
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import AsyncIterator

import httpx

from sensei.models.base import (
    ChatCompletion,
    ChatMessage,
    ModelInfo,
    ModelProvider,
    ModelStatus,
    Role,
    UsageStats,
)
from sensei.config import settings

logger = logging.getLogger(__name__)


class APIModelProvider(ModelProvider):
    """OpenAI-compatible API provider (Z.ai, OpenRouter, HuggingFace, etc.)."""

    # Provider defaults
    PROVIDER_DEFAULTS = {
        "zai": {
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-5.2",
        },
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "model": "zhipuai/glm-5.2",
        },
        "huggingface": {
            "base_url": "https://api-inference.huggingface.co/models",
            "model": "THUDM/glm-5.2-744b",
        },
    }

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ):
        self.provider_name = provider or settings.api_provider

        # Resolve settings based on provider
        if self.provider_name == "zai":
            self.base_url = base_url or settings.zai_api_base_url
            self.api_key = api_key or settings.zai_api_key
            self.model = model or settings.zai_api_model
        elif self.provider_name == "openrouter":
            self.base_url = base_url or settings.openrouter_api_base_url
            self.api_key = api_key or settings.openrouter_api_key
            self.model = model or settings.openrouter_api_model
        elif self.provider_name == "huggingface":
            self.base_url = base_url or settings.huggingface_api_base_url
            self.api_key = api_key or settings.huggingface_api_key
            self.model = model or settings.huggingface_api_model
        else:
            # Custom or legacy
            self.base_url = base_url or settings.api_base_url or self.PROVIDER_DEFAULTS.get(
                self.provider_name, {}
            ).get("base_url", "")
            self.api_key = api_key or settings.api_key
            self.model = model or settings.api_model or self.PROVIDER_DEFAULTS.get(
                self.provider_name, {}
            ).get("model", "glm-5.2")

        self.base_url = self.base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    def _format_messages(self, messages: list[ChatMessage]) -> list[dict]:
        return [
            {
                "role": msg.role.value,
                "content": msg.content,
                **({"name": msg.name} if msg.name else {}),
                **({"tool_call_id": msg.tool_call_id} if msg.tool_call_id else {}),
            }
            for msg in messages
        ]

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
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        resp = await client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage_data = data.get("usage", {})

        usage = UsageStats(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return ChatCompletion(
            id=data.get("id", str(uuid.uuid4())),
            model=data.get("model", target_model),
            content=choice["message"]["content"],
            role=Role(choice["message"].get("role", "assistant")),
            usage=usage,
            finish_reason=choice.get("finish_reason", "stop"),
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
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        async with client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    import json

                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    if content := delta.get("content"):
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def get_info(self) -> ModelInfo:
        available = await self.is_available()
        provider_labels = {
            "zai": "Z.ai",
            "openrouter": "OpenRouter",
            "huggingface": "HuggingFace",
            "custom": "Custom API",
        }
        label = provider_labels.get(self.provider_name, self.provider_name)
        return ModelInfo(
            id=f"api:{self.model}",
            name=f"{self.model} ({label})",
            provider="api",
            backend="openai-compatible",
            context_window=1_000_000,
            status=ModelStatus.available if available else ModelStatus.unavailable,
            description=f"GLM-5.2 via {label} API at {self.base_url}",
        )

    async def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            client = await self._get_client()
            resp = await client.get("/models")
            return resp.status_code == 200
        except Exception:
            # Fallback: try a minimal request
            try:
                client = await self._get_client()
                test_msg = ChatMessage(role=Role.user, content="ping")
                resp = await client.post(
                    "/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
                return resp.status_code in (200, 400, 429)
            except Exception:
                return False

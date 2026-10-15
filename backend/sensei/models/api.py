from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import ClassVar

import httpx

from sensei.config import Settings, settings
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


class APIModelProvider(ModelProvider):
    """OpenAI-compatible API provider supporting 14+ providers.

    Supported: OpenAI, Anthropic (Claude), Google Gemini, OpenRouter,
    Z.ai (GLM), HuggingFace, Groq, Mistral, Together AI, DeepSeek,
    Cohere, Fireworks AI, Perplexity, and any custom OpenAI-compatible endpoint.
    """

    # Derived from the Settings model rather than repeated here: this table
    # used to be a second copy of every default, and the two drifted — the
    # settings said one model while the fallback below still said gpt-4o.
    PROVIDER_DEFAULTS: ClassVar[dict[str, dict[str, str]]] = {
        name: {
            "base_url": Settings.model_fields[f"{name}_api_base_url"].default,
            "model": Settings.model_fields[f"{name}_api_model"].default,
        }
        for name in (
            "zai", "openrouter", "huggingface", "openai", "anthropic", "google", "groq",
            "mistral", "together", "deepseek", "cohere", "fireworks", "perplexity",
        )
    }  # fmt: skip

    # Providers that use OpenAI-compatible chat/completions endpoint
    OPENAI_COMPATIBLE: ClassVar[set[str]] = {
        "openai",
        "openrouter",
        "groq",
        "together",
        "deepseek",
        "fireworks",
        "perplexity",
        "zai",
        "mistral",
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
        provider_settings_map = {
            "zai": (settings.zai_api_base_url, settings.zai_api_key, settings.zai_api_model),
            "openrouter": (
                settings.openrouter_api_base_url,
                settings.openrouter_api_key,
                settings.openrouter_api_model,
            ),
            "huggingface": (
                settings.huggingface_api_base_url,
                settings.huggingface_api_key,
                settings.huggingface_api_model,
            ),
            "openai": (
                settings.openai_api_base_url,
                settings.openai_api_key,
                settings.openai_api_model,
            ),
            "anthropic": (
                settings.anthropic_api_base_url,
                settings.anthropic_api_key,
                settings.anthropic_api_model,
            ),
            "google": (
                settings.google_api_base_url,
                settings.google_api_key,
                settings.google_api_model,
            ),
            "groq": (settings.groq_api_base_url, settings.groq_api_key, settings.groq_api_model),
            "mistral": (
                settings.mistral_api_base_url,
                settings.mistral_api_key,
                settings.mistral_api_model,
            ),
            "together": (
                settings.together_api_base_url,
                settings.together_api_key,
                settings.together_api_model,
            ),
            "deepseek": (
                settings.deepseek_api_base_url,
                settings.deepseek_api_key,
                settings.deepseek_api_model,
            ),
            "cohere": (
                settings.cohere_api_base_url,
                settings.cohere_api_key,
                settings.cohere_api_model,
            ),
            "fireworks": (
                settings.fireworks_api_base_url,
                settings.fireworks_api_key,
                settings.fireworks_api_model,
            ),
            "perplexity": (
                settings.perplexity_api_base_url,
                settings.perplexity_api_key,
                settings.perplexity_api_model,
            ),
        }

        if self.provider_name in provider_settings_map:
            s_base, s_key, s_model = provider_settings_map[self.provider_name]
            self.base_url = base_url or s_base
            self.api_key = api_key or s_key
            self.model = model or s_model
        else:
            # Custom or legacy
            self.base_url = (
                base_url
                or settings.api_base_url
                or self.PROVIDER_DEFAULTS.get(self.provider_name, {}).get("base_url", "")
            )
            self.api_key = api_key or settings.api_key
            self.model = (
                model
                or settings.api_model
                or self.PROVIDER_DEFAULTS.get(self.provider_name, {}).get("model", "")
            )

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
            description=f"{self.model} via {label} at {self.base_url}",
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

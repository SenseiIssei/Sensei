from __future__ import annotations

import logging

from sensei.config import settings
from sensei.models.base import ModelInfo, ModelProvider, ModelStatus
from sensei.models.api import APIModelProvider
from sensei.models.local import LocalModelProvider, _detect_gpu
from sensei.models.ollama import OllamaProvider

logger = logging.getLogger(__name__)

_provider_cache: dict[str, ModelProvider] = {}


def get_local_provider() -> LocalModelProvider:
    if "local" not in _provider_cache:
        _provider_cache["local"] = LocalModelProvider()
    return _provider_cache["local"]  # type: ignore


def get_ollama_provider() -> OllamaProvider:
    if "ollama" not in _provider_cache:
        _provider_cache["ollama"] = OllamaProvider()
    return _provider_cache["ollama"]  # type: ignore


def get_api_provider() -> APIModelProvider:
    if "api" not in _provider_cache:
        _provider_cache["api"] = APIModelProvider()
    return _provider_cache["api"]  # type: ignore


async def get_provider() -> ModelProvider:
    """Get the active model provider based on settings.

    Priority in auto mode:
    1. Ollama (local, free, no API key) — if running
    2. Local model (llama.cpp/vLLM) — if configured
    3. API provider (OpenRouter/Z.ai/HuggingFace) — if key configured
    """
    mode = settings.model_provider

    if mode == "local":
        ollama = get_ollama_provider()
        if await ollama.is_available():
            logger.info("Using Ollama local provider")
            return ollama
        return get_local_provider()

    if mode == "api":
        return get_api_provider()

    # auto: try Ollama -> local -> API
    ollama = get_ollama_provider()
    if await ollama.is_available():
        logger.info("Auto-detected Ollama provider")
        return ollama

    local = get_local_provider()
    if await local.is_available():
        logger.info("Auto-detected local model provider")
        return local

    api = get_api_provider()
    if await api.is_available():
        logger.info("Auto-detected API model provider (%s)", settings.api_provider)
        return api

    logger.warning("No model provider available. Configure Ollama, local model, or API key.")
    return api


async def list_available_models() -> list[ModelInfo]:
    """List all available models from all providers."""
    models: list[ModelInfo] = []

    ollama = get_ollama_provider()
    if await ollama.is_available():
        info = await ollama.get_info()
        models.append(info)

    local = get_local_provider()
    if await local.is_available():
        info = await local.get_info()
        models.append(info)

    api = get_api_provider()
    if await api.is_available():
        info = await api.get_info()
        models.append(info)

    if not models:
        models.append(
            ModelInfo(
                id="ollama:glm-5.2",
                name="GLM-5.2 (Ollama - not running)",
                provider="local",
                backend="ollama",
                context_window=settings.local_context_size,
                status=ModelStatus.unavailable,
                description="Install Ollama and run: ollama pull glm-5.2",
            )
        )
        models.append(
            ModelInfo(
                id="local:glm-5.2",
                name="GLM-5.2 Local (not configured)",
                provider="local",
                backend=settings.local_backend,
                context_window=settings.local_context_size,
                status=ModelStatus.unavailable,
                description="Set SENSEI_LOCAL_MODEL_PATH to enable",
            )
        )
        provider_labels = {
            "zai": "Z.ai",
            "openrouter": "OpenRouter",
            "huggingface": "HuggingFace",
            "openai": "OpenAI",
            "anthropic": "Anthropic (Claude)",
            "google": "Google Gemini",
            "groq": "Groq",
            "mistral": "Mistral",
            "together": "Together AI",
            "deepseek": "DeepSeek",
            "cohere": "Cohere",
            "fireworks": "Fireworks AI",
            "perplexity": "Perplexity",
            "custom": "Custom",
        }
        label = provider_labels.get(settings.api_provider, settings.api_provider)
        models.append(
            ModelInfo(
                id=f"api:{settings.api_provider}",
                name=f"GLM-5.2 ({label} - not configured)",
                provider="api",
                backend="openai-compatible",
                context_window=1_000_000,
                status=ModelStatus.unavailable,
                description=f"Set SENSEI_{settings.api_provider.upper()}_API_KEY to enable",
            )
        )

    return models


async def get_model_info(model_id: str) -> ModelInfo | None:
    models = await list_available_models()
    for m in models:
        if m.id == model_id:
            return m
    return None


def detect_gpu() -> bool:
    """Public GPU detection for the stats endpoint."""
    return _detect_gpu()

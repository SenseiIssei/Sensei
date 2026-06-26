"""Runtime settings API — choose provider/model and insert an API key without
restarting the server. Changes update the live settings, persist to the repo
``.env``, and clear the provider cache so they take effect immediately.

Intended for local/self-hosted use; protect with ``SENSEI_AUTH_ENABLED`` if you
expose the server beyond localhost.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sensei.config import ENV_PATH, settings
from sensei.models import registry

router = APIRouter(prefix="/settings", tags=["settings"])

# Provider → display name, whether it has a free tier, and a few model choices.
PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "ollama": {"name": "Ollama (local)", "free": True, "models": ["glm-5.2", "llama3.3", "qwen2.5"]},
    "openrouter": {
        "name": "OpenRouter",
        "free": True,
        "models": [
            "zhipuai/glm-5.2",
            "openai/gpt-4o",
            "anthropic/claude-3.5-sonnet",
            "meta-llama/llama-3.3-70b-instruct",
            "google/gemini-2.0-flash-exp",
        ],
    },
    "openai": {"name": "OpenAI", "free": False, "models": ["gpt-4o", "gpt-4o-mini", "o3-mini"]},
    "anthropic": {
        "name": "Anthropic",
        "free": False,
        "models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
    },
    "groq": {"name": "Groq", "free": True, "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"]},
    "google": {"name": "Google Gemini", "free": True, "models": ["gemini-2.0-flash", "gemini-1.5-pro"]},
    "deepseek": {"name": "DeepSeek", "free": False, "models": ["deepseek-chat", "deepseek-reasoner"]},
    "mistral": {"name": "Mistral", "free": False, "models": ["mistral-large-latest", "codestral-latest"]},
}


def _key_attr(provider: str) -> str:
    return f"{provider}_api_key"


def _model_attr(provider: str) -> str:
    return f"{provider}_api_model"


def _current_model(provider: str) -> str:
    if provider == "ollama":
        return settings.ollama_model
    return getattr(settings, _model_attr(provider), "") or ""


def _snapshot() -> dict[str, Any]:
    provider = settings.api_provider
    return {
        "provider": provider,
        "model": _current_model(provider),
        "model_provider": settings.model_provider,
        "api_key_set": bool(getattr(settings, _key_attr(provider), "")),
        "compression_enabled": settings.compression_enabled,
        "log_file": settings.log_file,
        "catalog": [{"id": pid, **info} for pid, info in PROVIDER_CATALOG.items()],
    }


@router.get("")
async def get_settings() -> dict[str, Any]:
    return _snapshot()


class SettingsUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    compression_enabled: bool | None = None


def _persist_env(updates: dict[str, str]) -> None:
    """Upsert ``KEY=value`` lines in the repo .env (created if missing)."""
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


@router.put("")
async def update_settings(update: SettingsUpdate) -> dict[str, Any]:
    env_updates: dict[str, str] = {}

    if update.provider is not None:
        if update.provider not in PROVIDER_CATALOG:
            raise HTTPException(status_code=400, detail=f"Unknown provider '{update.provider}'")
        settings.api_provider = update.provider  # type: ignore[assignment]
        env_updates["SENSEI_API_PROVIDER"] = update.provider

    provider = settings.api_provider

    if update.api_key is not None:
        setattr(settings, _key_attr(provider), update.api_key)
        env_updates[f"SENSEI_{provider.upper()}_API_KEY"] = update.api_key
        # A configured key means we can serve from the API provider deterministically.
        settings.model_provider = "ollama" if provider == "ollama" else "api"  # type: ignore[assignment]
        env_updates["SENSEI_MODEL_PROVIDER"] = settings.model_provider

    if update.model:
        if provider == "ollama":
            settings.ollama_model = update.model
            env_updates["SENSEI_OLLAMA_MODEL"] = update.model
        else:
            setattr(settings, _model_attr(provider), update.model)
            env_updates[f"SENSEI_{provider.upper()}_API_MODEL"] = update.model

    if update.compression_enabled is not None:
        settings.compression_enabled = update.compression_enabled
        env_updates["SENSEI_COMPRESSION_ENABLED"] = str(update.compression_enabled).lower()

    if env_updates:
        _persist_env(env_updates)
    # Drop cached providers so the next request rebuilds them with new settings.
    registry._provider_cache.clear()
    return _snapshot()

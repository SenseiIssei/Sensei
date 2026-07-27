"""First-run setup API.

Backs the web wizard so a new user never has to open a text editor. It answers
three questions:

  * is Sensei usable at all right now, or is it missing a model?
  * what can this machine actually run locally?
  * which models does the provider I just configured really offer?

That last one matters more than it looks. A hardcoded model list is wrong
within months — every dropdown in every self-hosted AI tool eventually offers
models that were retired a year ago. Sensei asks the provider instead, and only
falls back to a static list when it can't.

Applying a choice goes through the existing ``PUT /api/settings``, which already
persists to ``.env`` and puts API keys in the encrypted vault.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from sensei import hardware
from sensei.config import settings
from sensei.routers.settings import PROVIDER_CATALOG, _key_attr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])

# Providers exposing an OpenAI-style GET /models. The base URL comes from
# settings, so a custom/self-hosted endpoint works the same way.
_LIVE_MODEL_PROVIDERS = {
    "openai",
    "openrouter",
    "groq",
    "mistral",
    "deepseek",
    "together",
    "fireworks",
    "perplexity",
    "zai",
}


def _configured_providers() -> list[str]:
    return [p for p in PROVIDER_CATALOG if getattr(settings, _key_attr(p), "")]


async def _ollama_models() -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=2.5) as c:
            r = await c.get(f"{settings.ollama_host}/api/tags")
            if r.status_code == 200:
                return sorted(m["name"] for m in r.json().get("models", []))
    except Exception as exc:
        logger.debug("ollama tag listing failed: %s", exc)
    return []


@router.get("/status")
async def setup_status() -> dict[str, Any]:
    """Everything the wizard needs to decide what to show first."""
    ollama_models = await _ollama_models()
    configured = _configured_providers()
    hw = hardware.detect()
    pick = hardware.best_pick(hw)

    # "Ready" means there is genuinely something to talk to — not merely that a
    # config file exists. Claiming readiness we can't back up is how a user ends
    # up staring at a chat box that silently fails.
    ready = bool(ollama_models or configured)

    return {
        "ready": ready,
        "needs_setup": not ready,
        "configured_providers": configured,
        "active_provider": settings.api_provider,
        "model_provider": settings.model_provider,
        "ollama": {
            "running": bool(ollama_models),
            "host": settings.ollama_host,
            "models": ollama_models,
            "active_model": settings.ollama_model,
        },
        "hardware": hw.to_dict(),
        "recommended_local_model": pick,
        "catalog": [{"id": pid, **info} for pid, info in PROVIDER_CATALOG.items()],
        "compression_enabled": settings.compression_enabled,
    }


@router.get("/provider-models/{provider}")
async def provider_models(provider: str) -> dict[str, Any]:
    """Ask the provider which models it actually serves.

    Returns ``source: "live"`` when the provider answered, or ``"catalog"`` with
    the static fallback when it didn't — the caller can say which it is rather
    than presenting a stale guess as fact.
    """
    if provider not in PROVIDER_CATALOG:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")

    fallback = {
        "provider": provider,
        "models": PROVIDER_CATALOG[provider].get("models", []),
        "source": "catalog",
        "detail": "Could not reach the provider — showing a static list that may be out of date.",
    }

    if provider == "ollama":
        models = await _ollama_models()
        if models:
            return {"provider": provider, "models": models, "source": "live", "detail": ""}
        return {**fallback, "detail": "Ollama isn't running. Start it with: ollama serve"}

    if provider not in _LIVE_MODEL_PROVIDERS:
        return {
            **fallback,
            "detail": "This provider has no model-listing endpoint; the list is curated.",
        }

    key = getattr(settings, _key_attr(provider), "")
    if not key:
        return {**fallback, "detail": "Enter an API key to load this provider's live model list."}

    base = getattr(settings, f"{provider}_api_base_url", "")
    if not base:
        return fallback

    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(
                f"{base.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"}
            )
        if r.status_code == 401:
            return {**fallback, "detail": "That API key was rejected by the provider."}
        if r.status_code != 200:
            return {**fallback, "detail": f"Provider returned HTTP {r.status_code}."}
        ids = sorted({m["id"] for m in r.json().get("data", []) if m.get("id")})
        if not ids:
            return fallback
        return {"provider": provider, "models": ids, "source": "live", "detail": ""}
    except Exception as exc:
        logger.debug("live model listing failed for %s: %s", provider, exc)
        return fallback

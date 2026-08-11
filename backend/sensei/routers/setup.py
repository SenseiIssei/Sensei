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

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sensei import hardware
from sensei.config import settings
from sensei.routers.settings import PROVIDER_CATALOG, _key_attr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])

# Providers exposing an OpenAI-style GET /models. The base URL comes from
# settings, so a custom/self-hosted endpoint works the same way.
# Providers that answer `GET /models`, so the list shown is the one they serve
# right now rather than whatever was true when this file was last edited.
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
    "moonshot",
    "dashscope",
    "xai",
    "cerebras",
    "deepinfra",
    # Local servers. Worth listing for the same reason and one more: what a
    # local server serves is whatever the user has loaded, which no catalog
    # anywhere could know.
    "lmstudio",
    "llamacpp",
    "vllm",
}

# Runs on this machine, so there is no account and no key to enter. Asking for
# one before showing the model list would gate a local server behind a
# credential that does not exist.
_LOCAL_PROVIDERS = {"lmstudio", "llamacpp", "vllm", "ollama"}


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


class PullRequest(BaseModel):
    model: str


@router.post("/ollama/pull")
async def ollama_pull(req: PullRequest) -> StreamingResponse:
    """Download a local model, streaming progress as it goes.

    Getting a local model running was the one setup step Sensei sent people to a
    terminal for — `ollama pull <something>`, with the name guessed from a list
    that ages. Ollama's own library is the only current answer to "what can I
    run", so this takes whatever tag the user types and reports progress rather
    than validating against a list Sensei would have to maintain.

    Streamed because these are gigabytes: a request that returns only when the
    download finishes looks identical to one that has hung.
    """
    model = req.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="no model named")

    async def progress() -> AsyncIterator[bytes]:
        try:
            # No overall deadline, but a connect timeout so an Ollama that is not
            # running fails in seconds instead of hanging: the download itself is
            # gigabytes and legitimately takes as long as it takes.
            limits = httpx.Timeout(None, connect=10.0)
            async with (
                httpx.AsyncClient(timeout=limits) as c,
                c.stream("POST", f"{settings.ollama_host}/api/pull", json={"model": model}) as r,
            ):
                if r.status_code != 200:
                    yield _sse({"error": f"Ollama answered {r.status_code}"})
                    return
                async for line in r.aiter_lines():
                    if line.strip():
                        yield _sse(json.loads(line))
        except httpx.ConnectError:
            # By far the most likely failure, and "ConnectError: All connection
            # attempts failed" tells the user nothing they can act on. Ollama is
            # a separate program; if it is not there, say so and where to get it.
            yield _sse(
                {
                    "error": f"Nothing answering at {settings.ollama_host}. "
                    "Ollama is a separate program — install it from https://ollama.com "
                    "and start it, then try again."
                }
            )
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            # Reported into the stream rather than raised: the response has
            # already started, so an exception here would truncate it and the
            # browser would see a download that simply stopped.
            yield _sse({"error": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(progress(), media_type="text/event-stream")


def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


@router.get("/tools")
async def connected_tools() -> dict[str, Any]:
    """Which AI tools are on this machine, and which are routed through Sensei.

    Separate from ``/status``, which answers "can Sensei originate a request of
    its own" — a different question with a different answer, and conflating the
    two is what made a working gateway look unconfigured.
    """
    from sensei import autowire, integrations

    watcher = autowire.current()
    opted_out = integrations.declined()
    rows = await asyncio.to_thread(integrations.status)
    return {
        "tools": [
            {
                "id": i.id,
                "name": i.name,
                "installed": installed,
                "connected": wired,
                "declined": i.id in opted_out,
            }
            for i, installed, wired in rows
        ],
        "auto_connect": {
            "enabled": settings.auto_connect,
            "running": watcher is not None,
            "interval_seconds": settings.auto_connect_interval_seconds,
            "scans": watcher.scans if watcher else 0,
            "connected_since_start": watcher.connected if watcher else [],
            "last_error": watcher.last_error if watcher else None,
        },
    }


async def _openai_style_models(base: str, key: str) -> tuple[int, list[str]]:
    """`GET {base}/models`, returning (status, ids). Raises on transport errors.

    Shared by the hosted and the local paths so the two cannot answer the same
    question differently.
    """
    # No empty bearer for a local server: some reject a malformed header
    # outright, which would look like the server being down.
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(timeout=8.0) as c:
        r = await c.get(f"{base.rstrip('/')}/models", headers=headers)
    if r.status_code != 200:
        return r.status_code, []
    return 200, sorted({m["id"] for m in r.json().get("data", []) if m.get("id")})


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

    if provider in _LOCAL_PROVIDERS:
        # These have no curated list to fall back on, by design — what a local
        # server offers is whatever the user has loaded. So the generic "showing
        # a static list that may be out of date" was shown next to no list at
        # all, and said nothing about the only thing wrong: it is not running.
        base = getattr(settings, f"{provider}_api_base_url", "")
        try:
            status, models = await _openai_style_models(base, "")
        except Exception as exc:
            logger.debug("local model listing failed for %s: %s", provider, exc)
            status, models = 0, []
        if status == 200 and models:
            return {"provider": provider, "models": models, "source": "live", "detail": ""}
        name = PROVIDER_CATALOG.get(provider, {}).get("name", provider)
        return {
            **fallback,
            "models": [],
            "detail": f"Nothing answering at {base or 'its usual address'} — start {name}, "
            "then reload this list.",
        }

    if provider not in _LIVE_MODEL_PROVIDERS:
        return {
            **fallback,
            "detail": "This provider has no model-listing endpoint; the list is curated.",
        }

    key = getattr(settings, _key_attr(provider), "")
    if not key and provider not in _LOCAL_PROVIDERS:
        return {**fallback, "detail": "Enter an API key to load this provider's live model list."}

    base = getattr(settings, f"{provider}_api_base_url", "")
    if not base:
        return fallback

    try:
        status, ids = await _openai_style_models(base, key)
    except Exception as exc:
        logger.debug("live model listing failed for %s: %s", provider, exc)
        return fallback
    if status == 401:
        return {**fallback, "detail": "That API key was rejected by the provider."}
    if status != 200:
        return {**fallback, "detail": f"Provider returned HTTP {status}."}
    if not ids:
        return fallback
    return {"provider": provider, "models": ids, "source": "live", "detail": ""}

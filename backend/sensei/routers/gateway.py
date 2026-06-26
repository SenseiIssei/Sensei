"""OpenAI-compatible compression gateway.

Point any OpenAI-compatible client (the OpenAI SDK, Cursor, Continue, Aider,
LangChain, ...) at ``http://<host>:<port>/v1`` and Sensei will transparently
compress each prompt before forwarding it to the configured upstream provider.
The client sees a normal OpenAI response; Sensei adds the tokens it saved in the
``X-Sensei-*`` response headers and a ``sensei`` block in the JSON body.

This is the project's core wedge: a drop-in proxy that cuts token spend on *any*
existing tool with a one-line base-URL change.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from sensei.compression.router import ContentRouter
from sensei.config import settings
from sensei.models.api import APIModelProvider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gateway"])

# Don't compress messages below this length — overhead isn't worth it.
_MIN_COMPRESS_LEN = 100

_content_router: ContentRouter | None = None


def init_gateway_deps(content_router: ContentRouter) -> None:
    global _content_router
    _content_router = content_router


def _router() -> ContentRouter:
    """The shared content router, lazily created if startup hasn't run."""
    global _content_router
    if _content_router is None:
        _content_router = ContentRouter(enable_caching=False)
    return _content_router


def _no_savings() -> dict[str, Any]:
    return {
        "compression_enabled": False,
        "tokens_saved": 0,
        "blocks_compressed": 0,
        "prompt_tokens_before": 0,
        "prompt_tokens_after": 0,
        "compression_ratio": 1.0,
    }


def compress_request_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compress the content of OpenAI-style chat messages.

    Order, roles, and any extra fields are preserved exactly (no reordering or
    volatile-stripping — this is a transparent proxy). System messages and short
    messages are passed through untouched. Returns ``(messages, savings)``.
    """
    if not settings.compression_enabled:
        return messages, _no_savings()

    cr = _router()
    out: list[dict[str, Any]] = []
    saved = before = after = blocks = 0

    for msg in messages:
        content = msg.get("content")
        role = msg.get("role", "user")
        # Only compress plain string content; skip system, short, and
        # structured (vision / tool-call) content blocks.
        if role == "system" or not isinstance(content, str) or len(content) < _MIN_COMPRESS_LEN:
            out.append(msg)
            continue

        result = cr.compress(content)
        before += result.original_tokens
        after += result.compressed_tokens
        saved += result.tokens_saved
        blocks += 1
        new_msg = dict(msg)
        new_msg["content"] = result.compressed
        out.append(new_msg)

    ratio = round(after / before, 4) if before else 1.0
    return out, {
        "compression_enabled": True,
        "tokens_saved": saved,
        "blocks_compressed": blocks,
        "prompt_tokens_before": before,
        "prompt_tokens_after": after,
        "compression_ratio": ratio,
    }


def _upstream_client(provider: APIModelProvider) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=provider.base_url,
        headers={
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(120.0, connect=10.0),
    )


def _savings_headers(savings: dict[str, Any]) -> dict[str, str]:
    return {
        "X-Sensei-Tokens-Saved": str(savings.get("tokens_saved", 0)),
        "X-Sensei-Compression-Ratio": str(savings.get("compression_ratio", 1.0)),
        "X-Sensei-Compression-Enabled": str(savings.get("compression_enabled", False)).lower(),
    }


@router.get("/v1/models")
async def list_models_openai() -> dict[str, Any]:
    """OpenAI-compatible model list (so clients that probe /v1/models work)."""
    provider = APIModelProvider()
    model_id = provider.model or settings.ollama_model or "glm-5.2"
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": f"sensei:{provider.provider_name}",
            }
        ],
    }


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    """OpenAI-compatible chat completions, with transparent prompt compression."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}},
        )

    messages = body.get("messages")
    if not isinstance(messages, list):
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "'messages' must be a list", "type": "invalid_request_error"}},
        )

    compressed, savings = compress_request_messages(messages)
    headers = _savings_headers(savings)

    provider = APIModelProvider()
    if not provider.api_key:
        return JSONResponse(
            status_code=502,
            headers=headers,
            content={
                "error": {
                    "message": (
                        f"No upstream API key configured for provider "
                        f"'{provider.provider_name}'. Set "
                        f"SENSEI_{provider.provider_name.upper()}_API_KEY."
                    ),
                    "type": "upstream_not_configured",
                }
            },
        )

    payload = dict(body)
    payload["messages"] = compressed
    if not payload.get("model"):
        payload["model"] = provider.model

    if payload.get("stream"):
        async def event_stream():
            async with _upstream_client(provider) as client:
                async with client.stream("POST", "/chat/completions", json=payload) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)

    try:
        async with _upstream_client(provider) as client:
            resp = await client.post("/chat/completions", json=payload)
    except httpx.HTTPError as exc:
        logger.warning("Gateway upstream request failed: %s", exc)
        return JSONResponse(
            status_code=502,
            headers=headers,
            content={"error": {"message": f"Upstream request failed: {exc}", "type": "upstream_error"}},
        )

    content_type = resp.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        data = resp.json()
        if isinstance(data, dict):
            data["sensei"] = savings
        return JSONResponse(status_code=resp.status_code, content=data, headers=headers)

    return JSONResponse(
        status_code=resp.status_code,
        content={"raw": resp.text, "sensei": savings},
        headers=headers,
    )

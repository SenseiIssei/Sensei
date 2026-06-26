"""Compression gateway — OpenAI- and Anthropic-compatible.

Point any tool at Sensei as its API base URL and Sensei transparently compresses
each prompt before forwarding it upstream, then returns a normal response.

- OpenAI clients (OpenAI SDK, Codex, Copilot, Cursor, Continue, Aider,
  LangChain): base URL ``http://<host>:<port>/v1`` → ``/v1/chat/completions``.
- Anthropic clients (Claude Code, Anthropic SDK): ``ANTHROPIC_BASE_URL`` →
  ``http://<host>:<port>`` → ``/v1/messages``.

Auth is pass-through: whatever key the client sends (``Authorization: Bearer`` or
``x-api-key``) is forwarded upstream, so tools keep using their own credentials.
If the client sends no key, Sensei falls back to a server-configured one. Savings
are reported in ``X-Sensei-*`` headers and a ``sensei`` block in JSON responses.
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
from sensei.savings import get_savings_tracker
from sensei.security.redaction import redact_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gateway"])

# Don't compress content below this length — overhead isn't worth it.
_MIN_COMPRESS_LEN = 100
_ANTHROPIC_VERSION = "2023-06-01"

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


# ─── savings bookkeeping ─────────────────────────────────────────────────────


def _no_savings() -> dict[str, Any]:
    return {
        "compression_enabled": False,
        "tokens_saved": 0,
        "blocks_compressed": 0,
        "prompt_tokens_before": 0,
        "prompt_tokens_after": 0,
        "compression_ratio": 1.0,
    }


def _savings(before: int, after: int, saved: int, blocks: int) -> dict[str, Any]:
    return {
        "compression_enabled": True,
        "tokens_saved": saved,
        "blocks_compressed": blocks,
        "prompt_tokens_before": before,
        "prompt_tokens_after": after,
        "compression_ratio": round(after / before, 4) if before else 1.0,
    }


def _savings_headers(savings: dict[str, Any]) -> dict[str, str]:
    return {
        "X-Sensei-Tokens-Saved": str(savings.get("tokens_saved", 0)),
        "X-Sensei-Compression-Ratio": str(savings.get("compression_ratio", 1.0)),
        "X-Sensei-Compression-Enabled": str(savings.get("compression_enabled", False)).lower(),
    }


# ─── compression of request bodies ───────────────────────────────────────────


def _compress_text(text: Any) -> tuple[Any, int, int, int, int]:
    """Compress a single string; return (text, before, after, saved, blocks)."""
    if not isinstance(text, str) or len(text) < _MIN_COMPRESS_LEN:
        return text, 0, 0, 0, 0
    r = _router().compress(text)
    return r.compressed, r.original_tokens, r.compressed_tokens, r.tokens_saved, 1


def compress_request_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compress OpenAI-style chat messages, preserving order/roles/extra fields.

    System messages are compressed only when ``gateway_compress_system`` is on
    (and long enough). Short and structured (vision/tool) content pass through.
    """
    if not settings.compression_enabled:
        return messages, _no_savings()

    # Cache-preserving mode: only touch the last message so the cached prefix
    # (everything before it) stays byte-identical.
    preserve = settings.gateway_preserve_cache
    last_idx = len(messages) - 1

    out: list[dict[str, Any]] = []
    before = after = saved = blocks = 0
    for idx, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content")
        skip_system = role == "system" and not settings.gateway_compress_system
        if (preserve and idx != last_idx) or skip_system or not isinstance(content, str):
            out.append(msg)
            continue
        new_content, b, a, s, bl = _compress_text(content)
        before, after, saved, blocks = before + b, after + a, saved + s, blocks + bl
        new_msg = dict(msg)
        new_msg["content"] = new_content
        out.append(new_msg)

    if not before:
        return out, _no_savings() if not blocks else _savings(0, 0, 0, blocks)
    return out, _savings(before, after, saved, blocks)


def _compress_anthropic_content(content: Any) -> tuple[Any, int, int, int, int]:
    """Compress an Anthropic ``content`` value (string or list of blocks)."""
    if isinstance(content, str):
        return _compress_text(content)
    if isinstance(content, list):
        before = after = saved = blocks = 0
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                nt, b, a, s, bl = _compress_text(block.get("text"))
                nb = dict(block)
                nb["text"] = nt
            elif isinstance(block, dict) and block.get("type") == "tool_result":
                # Tool outputs (file reads, command output, search results) are
                # where agents like Claude Code spend most tokens — and they
                # aren't part of the cached prefix, so compressing them is both
                # high-value and prompt-cache-safe.
                ni, b, a, s, bl = _compress_anthropic_content(block.get("content"))
                nb = dict(block)
                nb["content"] = ni
            else:
                out.append(block)
                continue
            out.append(nb)
            before, after, saved, blocks = before + b, after + a, saved + s, blocks + bl
        return out, before, after, saved, blocks
    return content, 0, 0, 0, 0


def compress_anthropic_request(
    system: Any, messages: list[dict[str, Any]]
) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    """Compress an Anthropic Messages request (top-level ``system`` + messages)."""
    if not settings.compression_enabled:
        return system, messages, _no_savings()

    preserve = settings.gateway_preserve_cache
    before = after = saved = blocks = 0
    new_system = system
    # In cache-preserving mode the system prompt is part of the cached prefix —
    # never touch it.
    if system is not None and settings.gateway_compress_system and not preserve:
        new_system, b, a, s, bl = _compress_anthropic_content(system)
        before, after, saved, blocks = before + b, after + a, saved + s, blocks + bl

    new_messages = []
    last_idx = len(messages) - 1
    for idx, msg in enumerate(messages):
        if preserve and idx != last_idx:
            new_messages.append(msg)  # keep the cached prefix byte-exact
            continue
        nc, b, a, s, bl = _compress_anthropic_content(msg.get("content"))
        nm = dict(msg)
        nm["content"] = nc
        new_messages.append(nm)
        before, after, saved, blocks = before + b, after + a, saved + s, blocks + bl

    savings = _savings(before, after, saved, blocks) if before else _no_savings()
    if blocks and not before:
        savings = _savings(0, 0, 0, blocks)
    return new_system, new_messages, savings


# ─── upstream forwarding ─────────────────────────────────────────────────────


def _incoming_bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else None


# Persistent, connection-pooled clients per upstream. Reusing keep-alive
# connections avoids a fresh TCP+TLS handshake on every request — the dominant
# added latency for a proxy. Auth headers are passed per-request, so a single
# pooled client safely serves requests carrying different keys.
_clients: dict[str, httpx.AsyncClient] = {}
_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=100, keepalive_expiry=90.0)


def _pooled_client(base_url: str) -> httpx.AsyncClient:
    base = base_url.rstrip("/")
    client = _clients.get(base)
    if client is None or client.is_closed:
        try:
            client = httpx.AsyncClient(
                base_url=base, timeout=httpx.Timeout(300.0, connect=10.0), limits=_LIMITS, http2=True
            )
        except ImportError:  # `h2` not installed — pooled HTTP/1.1 keep-alive
            client = httpx.AsyncClient(
                base_url=base, timeout=httpx.Timeout(300.0, connect=10.0), limits=_LIMITS
            )
        _clients[base] = client
    return client


async def close_clients() -> None:
    for client in _clients.values():
        try:
            await client.aclose()
        except Exception:
            pass
    _clients.clear()


def _error(status: int, message: str, etype: str, headers: dict[str, str]) -> JSONResponse:
    return JSONResponse(
        status_code=status, headers=headers, content={"error": {"message": message, "type": etype}}
    )


async def _forward(
    *,
    base_url: str,
    path: str,
    payload: dict[str, Any],
    up_headers: dict[str, str],
    savings: dict[str, Any],
    stream: bool,
    meta: dict[str, Any] | None = None,
    redactions: int = 0,
) -> Any:
    headers = _savings_headers(savings)
    if redactions:
        headers["X-Sensei-Redactions"] = str(redactions)
    get_savings_tracker().record(savings)
    if meta is not None:
        from sensei.audit import get_audit_log

        if redactions:
            meta = {**meta, "redactions": redactions}
        get_audit_log().record("gateway.request", **meta)

    client = _pooled_client(base_url)

    if stream:
        async def event_stream():
            async with client.stream("POST", path, json=payload, headers=up_headers) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)

    try:
        resp = await client.post(path, json=payload, headers=up_headers)
    except httpx.HTTPError as exc:
        logger.warning("Gateway upstream request failed: %s", exc)
        return _error(502, f"Upstream request failed: {exc}", "upstream_error", headers)

    if resp.headers.get("content-type", "").startswith("application/json"):
        data = resp.json()
        if isinstance(data, dict):
            data["sensei"] = savings
        return JSONResponse(status_code=resp.status_code, content=data, headers=headers)
    return JSONResponse(
        status_code=resp.status_code, content={"raw": resp.text, "sensei": savings}, headers=headers
    )


# ─── OpenAI-compatible endpoints ─────────────────────────────────────────────


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
    """OpenAI-compatible chat completions with transparent prompt compression."""
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body", "invalid_request_error", {})

    messages = body.get("messages")
    if not isinstance(messages, list):
        return _error(400, "'messages' must be a list", "invalid_request_error", {})

    compressed, savings = compress_request_messages(messages)

    provider = APIModelProvider()
    api_key = _incoming_bearer(request) or provider.api_key
    if not api_key:
        return _error(
            502,
            f"No API key. Send Authorization: Bearer <key> or set "
            f"SENSEI_{provider.provider_name.upper()}_API_KEY.",
            "upstream_not_configured",
            _savings_headers(savings),
        )

    payload = dict(body)
    payload["messages"] = compressed
    if not payload.get("model"):
        payload["model"] = provider.model

    red_total = 0
    if settings.redaction_enabled:
        payload, red_counts = redact_payload(payload)
        red_total = sum(red_counts.values())

    return await _forward(
        base_url=provider.base_url,
        path="/chat/completions",
        payload=payload,
        up_headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        savings=savings,
        stream=bool(payload.get("stream")),
        redactions=red_total,
        meta={
            "api": "openai",
            "provider": provider.provider_name,
            "model": payload.get("model"),
            "tokens_saved": savings.get("tokens_saved", 0),
        },
    )


# ─── Anthropic-compatible endpoint (Claude Code) ─────────────────────────────


@router.post("/v1/messages")
async def messages_anthropic(request: Request) -> Any:
    """Anthropic Messages API with transparent prompt compression."""
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body", "invalid_request_error", {})

    messages = body.get("messages")
    if not isinstance(messages, list):
        return _error(400, "'messages' must be a list", "invalid_request_error", {})

    new_system, new_messages, savings = compress_anthropic_request(body.get("system"), messages)

    # Forward the client's auth verbatim so both API-key and OAuth (Claude
    # subscription) modes work; fall back to a server-configured key.
    up_headers = {
        "anthropic-version": request.headers.get("anthropic-version", _ANTHROPIC_VERSION),
        "content-type": "application/json",
    }
    has_auth = False
    if xk := request.headers.get("x-api-key"):
        up_headers["x-api-key"] = xk
        has_auth = True
    if auth := request.headers.get("authorization"):
        up_headers["authorization"] = auth
        has_auth = True
    if beta := request.headers.get("anthropic-beta"):
        up_headers["anthropic-beta"] = beta
    if not has_auth and settings.anthropic_api_key:
        up_headers["x-api-key"] = settings.anthropic_api_key
        has_auth = True
    if not has_auth:
        return _error(
            502,
            "No API key. Send x-api-key: <key> or set SENSEI_ANTHROPIC_API_KEY.",
            "upstream_not_configured",
            _savings_headers(savings),
        )

    payload = dict(body)
    if new_system is not None:
        payload["system"] = new_system
    payload["messages"] = new_messages

    red_total = 0
    if settings.redaction_enabled:
        payload, red_counts = redact_payload(payload)
        red_total = sum(red_counts.values())

    return await _forward(
        base_url=settings.anthropic_api_base_url,
        path="/messages",
        payload=payload,
        up_headers=up_headers,
        savings=savings,
        stream=bool(payload.get("stream")),
        redactions=red_total,
        meta={
            "api": "anthropic",
            "model": payload.get("model"),
            "tokens_saved": savings.get("tokens_saved", 0),
        },
    )

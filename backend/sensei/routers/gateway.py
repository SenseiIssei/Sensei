"""Compression gateway — OpenAI- and Anthropic-compatible.

Point any tool at Sensei as its API base URL and Sensei transparently compresses
each prompt before forwarding it upstream, then returns a normal response.

- OpenAI clients (OpenAI SDK, Cursor, Continue, Aider, LangChain):
  base URL ``http://<host>:<port>/v1`` → ``/v1/chat/completions``.
- Codex and anything else on OpenAI's Responses API → ``/v1/responses``
  (plus ``/v1/responses/compact`` and ``/v1/responses/input_tokens``).
- Anthropic clients (Claude Code, Anthropic SDK): ``ANTHROPIC_BASE_URL`` →
  ``http://<host>:<port>`` → ``/v1/messages`` and ``/v1/messages/count_tokens``.

Auth is pass-through: whatever key the client sends (``Authorization: Bearer`` or
``x-api-key``) is forwarded upstream, so tools keep using their own credentials.
If the client sends no key, Sensei falls back to a server-configured one. Savings
are reported in ``X-Sensei-*`` headers and a ``sensei`` block in JSON responses.

Upstream failures are reported as what they were. A provider that answers 429
gets retried (honouring Retry-After) and, if it is still 429, the client sees
429 — not a 200 with an error hidden inside an event stream. Optionally a local
model takes over when the provider stays down; see ``fallback_enabled``.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from sensei import output_shaping
from sensei.compression.router import ContentRouter
from sensei.config import settings
from sensei.models.api import APIModelProvider
from sensei.savings import get_savings_tracker
from sensei.security.filtering import check_policy
from sensei.security.redaction import redact_payload
from sensei.usage import UsageSniffer, from_response

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


class _Tally:
    """Running totals while one request body is compressed."""

    __slots__ = ("after", "before", "blocks", "saved")

    def __init__(self) -> None:
        self.before = self.after = self.saved = self.blocks = 0

    def add(self, before: int, after: int, saved: int, blocks: int) -> None:
        self.before += before
        self.after += after
        self.saved += saved
        self.blocks += blocks

    def result(self) -> dict[str, Any]:
        if self.before:
            return _savings(self.before, self.after, self.saved, self.blocks)
        return _savings(0, 0, 0, self.blocks) if self.blocks else _no_savings()


# Which client sent this. Ordered most- to least-specific, because several of
# these ship an SDK string as well as their own — Claude Code sends both
# "claude-cli" and "anthropic-sdk-python", and attributing its savings to the
# SDK would merge four different tools into one bar on the dashboard.
_CLIENT_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("claude-cli", "Claude Code"),
    ("claude-code", "Claude Code"),
    ("cursor", "Cursor"),
    ("windsurf", "Windsurf"),
    ("codex", "Codex"),
    ("aider", "Aider"),
    ("cline", "Cline"),
    ("roo-code", "Roo Code"),
    ("kilo-code", "Kilo Code"),
    ("continue", "Continue"),
    ("opencode", "opencode"),
    ("goose", "Goose"),
    ("crush", "Crush"),
    ("zed", "Zed"),
    ("copilot", "Copilot"),
    ("rea-agents", "REA"),
    ("sensei", "Sensei UI"),
    # SDKs last: a bare SDK string means "something we don't have a name for",
    # which is still more useful on a chart than "unknown".
    ("anthropic", "Anthropic SDK"),
    ("openai", "OpenAI SDK"),
    ("langchain", "LangChain"),
    ("litellm", "LiteLLM"),
    ("httpx", "httpx"),
    ("curl", "curl"),
)


def _client_name(request: Request) -> str:
    """A stable, human-readable name for whatever sent this request.

    An explicit ``X-Sensei-Client`` header wins, so a tool that wants to be
    labelled correctly can say so instead of being pattern-matched.
    """
    explicit = request.headers.get("x-sensei-client", "").strip()
    if explicit:
        return explicit[:64]
    raw = request.headers.get("user-agent", "").strip()
    agent = raw.lower()
    for needle, label in _CLIENT_SIGNATURES:
        if needle in agent:
            return label

    # Fall back to the agent's own name rather than dropping it: an unmatched
    # `python-httpx/0.28` says which tool it was, and takes one line to add to
    # the table above. Only the product token, so versions group together.
    product = raw.split(" ", 1)[0].split("/", 1)[0]
    return product[:64] if product else ""


def _completion_tokens(data: dict[str, Any]) -> int:
    """How many tokens the model wrote, across every wire format."""
    return from_response(data).output


def _savings_headers(savings: dict[str, Any]) -> dict[str, str]:
    return {
        "X-Sensei-Tokens-Saved": str(savings.get("tokens_saved", 0)),
        "X-Sensei-Compression-Ratio": str(savings.get("compression_ratio", 1.0)),
        "X-Sensei-Compression-Enabled": str(savings.get("compression_enabled", False)).lower(),
    }


# ─── compression of request bodies ───────────────────────────────────────────


def _compress_text(text: Any, *, edit_target: bool = False) -> tuple[Any, int, int, int, int]:
    """Compress a single string; return (text, before, after, saved, blocks)."""
    if not isinstance(text, str) or len(text) < _MIN_COMPRESS_LEN:
        return text, 0, 0, 0, 0
    r = _router().compress(text, edit_target=edit_target)
    return r.compressed, r.original_tokens, r.compressed_tokens, r.tokens_saved, 1


def _compress_part_list(
    parts: list[Any], tally: _Tally, *, edit_target: bool, types: tuple[str, ...]
) -> list[Any]:
    """Compress the text parts of a content list; images, audio and files pass."""
    out = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") in types and "text" in part:
            new_text, *counts = _compress_text(part["text"], edit_target=edit_target)
            tally.add(*counts)
            out.append(part if new_text is part["text"] else {**part, "text": new_text})
        else:
            out.append(part)
    return out


def compress_request_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compress OpenAI-style chat messages, preserving order/roles/extra fields.

    System messages are compressed only when ``gateway_compress_system`` is on.
    ``tool`` messages are tool results — what an agent read from disk or from a
    command — and are compressed as edit targets, so code in them stays exact.
    Images and audio parts pass through untouched.
    """
    if not settings.compression_enabled:
        return messages, _no_savings()

    preserve = settings.gateway_preserve_cache
    last_idx = len(messages) - 1
    tally = _Tally()

    out: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content")
        skip_system = role in ("system", "developer") and not settings.gateway_compress_system
        if (preserve and idx != last_idx) or skip_system:
            out.append(msg)
            continue
        edit_target = role in ("tool", "function")
        if isinstance(content, str):
            new_content, *counts = _compress_text(content, edit_target=edit_target)
            tally.add(*counts)
        elif isinstance(content, list):
            new_content = _compress_part_list(
                content, tally, edit_target=edit_target, types=("text",)
            )
        else:
            out.append(msg)
            continue
        out.append({**msg, "content": new_content})

    return out, tally.result()


def _compress_anthropic_content(
    content: Any, *, edit_target: bool = False
) -> tuple[Any, int, int, int, int]:
    """Compress an Anthropic ``content`` value (string or list of blocks)."""
    if isinstance(content, str):
        return _compress_text(content, edit_target=edit_target)
    if isinstance(content, list):
        tally = _Tally()
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                new_text, *counts = _compress_text(block.get("text"), edit_target=edit_target)
                tally.add(*counts)
                out.append({**block, "text": new_text})
            elif isinstance(block, dict) and block.get("type") == "tool_result":
                # Tool outputs (file reads, command output, search results) are
                # where agents like Claude Code spend most tokens. They are
                # also what the model edits next, so code inside stays exact.
                inner, *counts = _compress_anthropic_content(block.get("content"), edit_target=True)
                tally.add(*counts)
                out.append({**block, "content": inner})
            else:
                out.append(block)
        return out, tally.before, tally.after, tally.saved, tally.blocks
    return content, 0, 0, 0, 0


def compress_anthropic_request(
    system: Any, messages: list[dict[str, Any]]
) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    """Compress an Anthropic Messages request (top-level ``system`` + messages)."""
    if not settings.compression_enabled:
        return system, messages, _no_savings()

    # Compression is deterministic: the same text always yields the same bytes.
    # The provider only ever sees the transformed request, so it caches *that*,
    # and next turn the same prefix transforms identically and the cache hits.
    # Compressing everything is therefore cache-safe, and measurably so — the
    # prefix hashes identical across two turns.
    #
    # What is not safe is a decision that depends on position. `preserve_cache`
    # compresses only the newest message, so a message compressed while it was
    # newest arrives uncompressed on the next turn: different bytes, cache miss.
    preserve = settings.gateway_preserve_cache
    tally = _Tally()
    new_system = system
    if system is not None and settings.gateway_compress_system and not preserve:
        new_system, *counts = _compress_anthropic_content(system)
        tally.add(*counts)

    new_messages = []
    last_idx = len(messages) - 1
    for idx, msg in enumerate(messages):
        if preserve and idx != last_idx:
            new_messages.append(msg)  # keep the cached prefix byte-exact
            continue
        new_content, *counts = _compress_anthropic_content(msg.get("content"))
        tally.add(*counts)
        new_messages.append({**msg, "content": new_content})

    return new_system, new_messages, tally.result()


# Responses API item types whose `output` is a tool result.
_TOOL_OUTPUT_ITEMS = (
    "function_call_output",
    "custom_tool_call_output",
    "local_shell_call_output",
    "mcp_call_output",
)
_TEXT_PART_TYPES = ("input_text", "output_text", "text")


def compress_responses_request(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compress an OpenAI Responses request (``instructions`` + ``input``).

    Text parts of messages and the ``output`` of tool calls are compressed.
    Everything else — function calls, reasoning items (often encrypted),
    images, file references, item ids — passes through untouched, because the
    API validates them and the model relies on them being exactly as it left
    them.
    """
    if not settings.compression_enabled:
        return body, _no_savings()

    tally = _Tally()
    out = dict(body)
    preserve = settings.gateway_preserve_cache

    instructions = body.get("instructions")
    if isinstance(instructions, str) and settings.gateway_compress_system and not preserve:
        out["instructions"], *counts = _compress_text(instructions)
        tally.add(*counts)

    items = body.get("input")
    if isinstance(items, str):
        out["input"], *counts = _compress_text(items)
        tally.add(*counts)
        return out, tally.result()
    if not isinstance(items, list):
        return out, tally.result()

    last_idx = len(items) - 1
    new_items: list[Any] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict) or (preserve and idx != last_idx):
            new_items.append(item)
            continue
        kind = item.get("type", "message" if "role" in item else "")
        if kind == "message":
            role = item.get("role")
            if role in ("system", "developer") and not settings.gateway_compress_system:
                new_items.append(item)
                continue
            content = item.get("content")
            if isinstance(content, str):
                new_content, *counts = _compress_text(content)
                tally.add(*counts)
            elif isinstance(content, list):
                new_content = _compress_part_list(
                    content, tally, edit_target=False, types=_TEXT_PART_TYPES
                )
            else:
                new_items.append(item)
                continue
            new_items.append({**item, "content": new_content})
        elif kind in _TOOL_OUTPUT_ITEMS:
            output = item.get("output")
            if isinstance(output, str):
                new_output, *counts = _compress_text(output, edit_target=True)
                tally.add(*counts)
            elif isinstance(output, list):
                new_output = _compress_part_list(
                    output, tally, edit_target=True, types=_TEXT_PART_TYPES
                )
            else:
                new_items.append(item)
                continue
            new_items.append({**item, "output": new_output})
        else:
            new_items.append(item)
    out["input"] = new_items
    return out, tally.result()


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
_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


def _pooled_client(base_url: str) -> httpx.AsyncClient:
    base = base_url.rstrip("/")
    client = _clients.get(base)
    if client is None or client.is_closed:
        try:
            client = httpx.AsyncClient(base_url=base, timeout=_TIMEOUT, limits=_LIMITS, http2=True)
        except ImportError:  # `h2` not installed — pooled HTTP/1.1 keep-alive
            client = httpx.AsyncClient(base_url=base, timeout=_TIMEOUT, limits=_LIMITS)
        _clients[base] = client
    return client


async def close_clients() -> None:
    for client in _clients.values():
        try:
            await client.aclose()
        except Exception as exc:
            logger.debug("upstream client did not close cleanly: %s", exc)
    _clients.clear()


def _error(status: int, message: str, etype: str, headers: dict[str, str]) -> JSONResponse:
    return JSONResponse(
        status_code=status, headers=headers, content={"error": {"message": message, "type": etype}}
    )


# 529 is Anthropic's "overloaded". 408/409 are not retried: a timeout already
# cost the client its patience, and a conflict will conflict again.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 529})
# Upstream response headers worth handing back: request ids for support
# tickets, and rate-limit state that Claude Code and the OpenAI SDK read to
# pace themselves. Hop-by-hop and encoding headers are never forwarded.
_PASS_HEADER_PREFIXES = ("anthropic-", "openai-", "x-ratelimit-", "x-request-id", "request-id")
_PASS_HEADERS = frozenset({"retry-after", "retry-after-ms"})


def _upstream_headers(resp: httpx.Response) -> dict[str, str]:
    out = {}
    for name, value in resp.headers.items():
        low = name.lower()
        if low in _PASS_HEADERS or low.startswith(_PASS_HEADER_PREFIXES):
            out[name] = value
    return out


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    cap = max(0.0, settings.upstream_retry_max_wait)
    if resp is not None:
        for header, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
            raw = resp.headers.get(header)
            if raw:
                try:
                    return min(cap, max(0.0, float(raw) * scale))
                except ValueError:
                    break
    # Exponential backoff with full jitter: up to 0.5s, 1s, 2s … randomised so
    # a dozen agents retrying at once do not all land in the same millisecond.
    return min(cap, random.uniform(0, 0.5 * 2**attempt))  # noqa: S311 — jitter, not crypto


async def _send(
    base_url: str, path: str, payload: dict[str, Any], headers: dict[str, str]
) -> tuple[httpx.Response | None, Exception | None]:
    """POST upstream with retries; the response is returned unread (streaming).

    Retries happen only here, before a single byte has reached the client, so
    a retried request is indistinguishable from a slow one.
    """
    client = _pooled_client(base_url)
    attempts = 1 + max(0, settings.upstream_retries)
    last_exc: Exception | None = None
    for attempt in range(attempts):
        resp: httpx.Response | None = None
        try:
            request = client.build_request("POST", path, json=payload, headers=headers)
            resp = await client.send(request, stream=True)
        except httpx.TransportError as exc:
            last_exc = exc
            logger.warning(
                "Upstream %s%s unreachable (attempt %d): %s", base_url, path, attempt + 1, exc
            )
        if resp is not None:
            if resp.status_code not in _RETRY_STATUSES or attempt == attempts - 1:
                return resp, None
            logger.info("Upstream %s%s answered %d, retrying", base_url, path, resp.status_code)
        if attempt < attempts - 1:
            delay = _retry_delay(resp, attempt)
            if resp is not None:
                await resp.aclose()
            await asyncio.sleep(delay)
    return None, last_exc


def _fallback_target(api: str) -> tuple[str, str] | None:
    """Base URL and path for the local fallback, or None when it is off."""
    if not settings.fallback_enabled or not settings.fallback_base_url:
        return None
    base = settings.fallback_base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    paths = {"anthropic": "/messages", "openai": "/chat/completions", "responses": "/responses"}
    return base, paths[api]


async def _try_fallback(
    api: str, payload: dict[str, Any], headers: dict[str, str]
) -> tuple[httpx.Response | None, str]:
    target = _fallback_target(api)
    if target is None:
        return None, ""
    base, path = target
    model = settings.fallback_model or settings.ollama_model
    local_payload = {**payload, "model": model}
    # Never hand the client's provider credential to another server.
    local_headers = {
        k: v for k, v in headers.items() if k.lower() not in ("authorization", "x-api-key")
    }
    local_headers["authorization"] = "Bearer sensei-fallback"
    try:
        client = _pooled_client(base)
        request = client.build_request("POST", path, json=local_payload, headers=local_headers)
        resp = await client.send(request, stream=True)
    except httpx.TransportError as exc:
        logger.warning("Local fallback %s unreachable: %s", base, exc)
        return None, ""
    if resp.status_code >= 400:
        await resp.aclose()
        logger.warning("Local fallback %s answered %d", base, resp.status_code)
        return None, ""
    logger.warning("Provider unavailable — answered by local fallback %s (%s)", base, model)
    return resp, model


async def _forward(
    *,
    base_url: str,
    path: str,
    payload: dict[str, Any],
    up_headers: dict[str, str],
    savings: dict[str, Any],
    stream: bool,
    api: str = "openai",
    meta: dict[str, Any] | None = None,
    redactions: int = 0,
    tool: str = "",
    shaped: int = -1,
    record: bool = True,
) -> Any:
    headers = _savings_headers(savings)
    if redactions:
        headers["X-Sensei-Redactions"] = str(redactions)
    if shaped >= 0:
        # Visible to the caller so a holdout assignment can be correlated with
        # what came back, without having to read the ledger.
        headers["X-Sensei-Output-Shaped"] = "true" if shaped else "false"

    tracker = get_savings_tracker()
    row_id = None
    if record:
        row_id = tracker.record(
            savings,
            tool=tool,
            provider=str((meta or {}).get("provider") or (meta or {}).get("api") or ""),
            model=str((meta or {}).get("model") or ""),
            shaped=shaped,
        )
        if meta is not None:
            from sensei.audit import get_audit_log

            if redactions:
                meta = {**meta, "redactions": redactions}
            get_audit_log().record("gateway.request", **meta)

    resp, exc = await _send(base_url, path, payload, up_headers)

    if record and (resp is None or resp.status_code in _RETRY_STATUSES):
        fallback, model = await _try_fallback(api, payload, up_headers)
        if fallback is not None:
            if resp is not None:
                await resp.aclose()
            resp = fallback
            headers["X-Sensei-Fallback"] = model

    if resp is None:
        logger.warning("Gateway upstream request failed: %s", exc)
        return _error(502, f"Upstream request failed: {exc}", "upstream_error", headers)

    headers.update(_upstream_headers(resp))
    content_type = resp.headers.get("content-type", "")

    # Errors go back as errors, with the provider's own status and body. A
    # streaming request that hit a 429 used to come back as `200 OK` with
    # `text/event-stream` and a JSON error inside, which clients parse as a
    # stream that ended early — the rate limit was invisible.
    if resp.status_code >= 400:
        body = await resp.aread()
        await resp.aclose()
        return Response(
            content=body,
            status_code=resp.status_code,
            media_type=content_type or "application/json",
            headers=headers,
        )

    if stream and "event-stream" in content_type:
        sniffer = UsageSniffer()
        upstream = resp

        async def event_stream():
            try:
                async for chunk in upstream.aiter_bytes():
                    sniffer.feed(chunk)
                    yield chunk
            except httpx.HTTPError as err:
                # Headers are already sent; all that is left is to stop cleanly
                # and let the client see a truncated stream.
                logger.warning("Upstream stream broke off: %s", err)
            finally:
                await upstream.aclose()
                tracker.ledger.set_usage(row_id, sniffer.close())

        return StreamingResponse(
            event_stream(), status_code=resp.status_code, media_type=content_type, headers=headers
        )

    raw = await resp.aread()
    await resp.aclose()
    if content_type.startswith("application/json"):
        try:
            data = resp.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            if record:
                data["sensei"] = savings
                tracker.ledger.set_usage(row_id, from_response(data))
            return JSONResponse(status_code=resp.status_code, content=data, headers=headers)
    return Response(
        content=raw, status_code=resp.status_code, media_type=content_type or None, headers=headers
    )


def _apply_policy(payload: dict[str, Any]) -> tuple[dict[str, Any], int, str | None]:
    """Redaction, then the block-list. Returns (payload, redactions, reason)."""
    redactions = 0
    if settings.redaction_enabled:
        payload, counts = redact_payload(payload)
        redactions = sum(counts.values())
    return payload, redactions, check_policy(payload)


async def _json_body(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body", "invalid_request_error", {})
    if not isinstance(body, dict):
        return _error(400, "Request body must be a JSON object", "invalid_request_error", {})
    return body


# ─── OpenAI-compatible endpoints ─────────────────────────────────────────────


@router.get("/v1/models")
async def list_models_openai() -> dict[str, Any]:
    """OpenAI-compatible model list (so clients that probe /v1/models work)."""
    provider = APIModelProvider()
    model_id = provider.model or settings.ollama_model
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


def _openai_auth(request: Request, provider: APIModelProvider) -> str | None:
    return _incoming_bearer(request) or provider.api_key or None


def _no_key(provider: APIModelProvider, savings: dict[str, Any]) -> JSONResponse:
    return _error(
        502,
        f"No API key. Send Authorization: Bearer <key> or set "
        f"SENSEI_{provider.provider_name.upper()}_API_KEY.",
        "upstream_not_configured",
        _savings_headers(savings),
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    """OpenAI-compatible chat completions with transparent prompt compression."""
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body

    messages = body.get("messages")
    if not isinstance(messages, list):
        return _error(400, "'messages' must be a list", "invalid_request_error", {})

    compressed, savings = compress_request_messages(messages)

    provider = APIModelProvider()
    api_key = _openai_auth(request, provider)
    if not api_key:
        return _no_key(provider, savings)

    # Shaping runs after compression, so the instruction is not itself
    # compressed away, and its cost shows up honestly as input tokens.
    shaped = -1
    if settings.output_shaper:
        shaped = int(output_shaping.assign())
        if shaped:
            compressed = output_shaping.shape_messages(compressed)
            savings = output_shaping.account_for_instruction(savings)

    payload = dict(body)
    payload["messages"] = compressed
    if not payload.get("model"):
        payload["model"] = provider.model

    payload, red_total, reason = _apply_policy(payload)
    if reason:
        return _error(403, reason, "blocked_by_policy", _savings_headers(savings))

    return await _forward(
        base_url=provider.base_url,
        path="/chat/completions",
        payload=payload,
        up_headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        savings=savings,
        stream=bool(payload.get("stream")),
        api="openai",
        redactions=red_total,
        tool=_client_name(request),
        shaped=shaped,
        meta={
            "api": "openai",
            "provider": provider.provider_name,
            "model": payload.get("model"),
            "tokens_saved": savings.get("tokens_saved", 0),
        },
    )


@router.post("/v1/responses")
async def responses(request: Request) -> Any:
    """OpenAI Responses API with transparent prompt compression.

    This is the API Codex speaks — its config accepts only
    ``wire_api = "responses"`` — and the one OpenAI requires for tool calling
    on its current models. Requests are compressed and forwarded to the
    configured provider's ``/responses``; Ollama, llama.cpp, LM Studio and vLLM
    serve it locally too.
    """
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    if "input" not in body:
        return _error(400, "'input' is required", "invalid_request_error", {})

    payload, savings = compress_responses_request(body)

    provider = APIModelProvider()
    api_key = _openai_auth(request, provider)
    if not api_key:
        return _no_key(provider, savings)
    if not payload.get("model"):
        payload["model"] = provider.model

    payload, red_total, reason = _apply_policy(payload)
    if reason:
        return _error(403, reason, "blocked_by_policy", _savings_headers(savings))

    return await _forward(
        base_url=provider.base_url,
        path="/responses",
        payload=payload,
        up_headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        savings=savings,
        stream=bool(payload.get("stream")),
        api="responses",
        redactions=red_total,
        tool=_client_name(request),
        meta={
            "api": "responses",
            "provider": provider.provider_name,
            "model": payload.get("model"),
            "tokens_saved": savings.get("tokens_saved", 0),
        },
    )


# The caller's path segment never reaches a log line or the upstream URL:
# it selects one of these fixed strings or gets a 404.
_RESPONSES_ACTIONS = {"compact": "compact", "input_tokens": "input_tokens"}


@router.post("/v1/responses/{action}")
async def responses_action(action: str, request: Request) -> Any:
    """``/responses/compact`` and ``/responses/input_tokens``.

    Codex calls ``compact`` with the whole conversation when its context fills
    up; the input is compressed exactly as for ``/responses``, so a token count
    taken here matches what a real turn would send.
    """
    endpoint = _RESPONSES_ACTIONS.get(action)
    if endpoint is None:
        return _error(404, "Unknown /v1/responses endpoint", "not_found", {})
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    provider = APIModelProvider()
    payload, savings = compress_responses_request(body)
    api_key = _openai_auth(request, provider)
    if not api_key:
        return _no_key(provider, savings)
    return await _forward(
        base_url=provider.base_url,
        path=f"/responses/{endpoint}",
        payload=payload,
        up_headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        savings=savings,
        stream=False,
        api="responses",
        tool=_client_name(request),
        record=endpoint == "compact",
        meta={"api": "responses", "provider": provider.provider_name, "model": body.get("model")},
    )


# ─── Anthropic-compatible endpoints (Claude Code) ────────────────────────────


def _anthropic_headers(request: Request) -> dict[str, str] | None:
    """Forward the client's auth verbatim so both API-key and OAuth (Claude
    subscription) modes work; fall back to a server-configured key."""
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
    return up_headers if has_auth else None


def _anthropic_no_key(savings: dict[str, Any]) -> JSONResponse:
    return _error(
        502,
        "No API key. Send x-api-key: <key> or set SENSEI_ANTHROPIC_API_KEY.",
        "upstream_not_configured",
        _savings_headers(savings),
    )


@router.post("/v1/messages")
async def messages_anthropic(request: Request) -> Any:
    """Anthropic Messages API with transparent prompt compression."""
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body

    messages = body.get("messages")
    if not isinstance(messages, list):
        return _error(400, "'messages' must be a list", "invalid_request_error", {})

    new_system, new_messages, savings = compress_anthropic_request(body.get("system"), messages)

    up_headers = _anthropic_headers(request)
    if up_headers is None:
        return _anthropic_no_key(savings)

    shaped = -1
    if settings.output_shaper:
        shaped = int(output_shaping.assign())
        if shaped:
            # `system` stays untouched: it is the cached prefix, which is the
            # whole reason CacheAligner exists.
            new_messages = output_shaping.shape_messages(new_messages)
            savings = output_shaping.account_for_instruction(savings)

    payload = dict(body)
    if new_system is not None:
        payload["system"] = new_system
    payload["messages"] = new_messages

    payload, red_total, reason = _apply_policy(payload)
    if reason:
        return _error(403, reason, "blocked_by_policy", _savings_headers(savings))

    return await _forward(
        base_url=settings.anthropic_api_base_url,
        path="/messages",
        payload=payload,
        up_headers=up_headers,
        savings=savings,
        stream=bool(payload.get("stream")),
        api="anthropic",
        redactions=red_total,
        tool=_client_name(request),
        shaped=shaped,
        meta={
            "api": "anthropic",
            "provider": "anthropic",
            "model": payload.get("model"),
            "tokens_saved": savings.get("tokens_saved", 0),
        },
    )


@router.post("/v1/messages/count_tokens")
async def count_tokens_anthropic(request: Request) -> Any:
    """Token counting, over the request as Sensei would actually send it.

    Claude Code calls this to decide when to compact. Without this route it got
    a 404 through the gateway; an uncompressed passthrough would count a prompt
    bigger than the one really sent, and compact too early.
    """
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    messages = body.get("messages")
    if not isinstance(messages, list):
        return _error(400, "'messages' must be a list", "invalid_request_error", {})
    new_system, new_messages, savings = compress_anthropic_request(body.get("system"), messages)
    up_headers = _anthropic_headers(request)
    if up_headers is None:
        return _anthropic_no_key(savings)
    payload = dict(body)
    if new_system is not None:
        payload["system"] = new_system
    payload["messages"] = new_messages
    return await _forward(
        base_url=settings.anthropic_api_base_url,
        path="/messages/count_tokens",
        payload=payload,
        up_headers=up_headers,
        savings=savings,
        stream=False,
        api="anthropic",
        record=False,
    )

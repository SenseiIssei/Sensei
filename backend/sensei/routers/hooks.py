"""Tool-output hooks — compression for tools that keep their own model connection.

Routing a tool's model traffic through the gateway is the strongest way to
compress it, and for some tools the wrong one: Claude Code disables Remote
Control behind a custom base URL, and its desktop app's Code tab ignores one.
Those tools offer something else — a hook that runs after every tool call and
may replace the output before the model sees it. That output (command logs,
search results, fetched pages, MCP responses) is where most of an agent's
context goes, and it is exactly what Sensei compresses best.

Endpoints, one per hook dialect:

    POST /hooks/claude/post-tool-use   Claude Code PostToolUse (type "http")
    POST /hooks/copilot/post-tool-use  Copilot CLI postToolUse (via curl)
    POST /hooks/gemini/after-tool      Gemini CLI AfterTool (via curl)
    POST /hooks/cursor/post-tool-use   Cursor postToolUse, MCP tools only
    POST /hooks/compress               {tool, text} → {text}; opencode/Kilo plugin

Three rules hold for all of them:

* **Fail open.** Every path answers 200 with valid JSON, and the empty answer
  (``{}``) means "leave the output alone". An exception inside Sensei is logged
  and becomes ``{}``; Sensei not running at all is handled by the tool, which
  treats a failed hook as non-blocking.
* **Never the file tools.** What Read returns is what Edit's ``old_string`` is
  matched against; a model that saw a compressed file writes edits that fail.
  Only command output, search results, fetched pages and MCP results are
  touched, and code inside them stays byte-exact (``edit_target``).
* **Recoverable.** A compressed output carries the id that ``sensei_retrieve``
  exchanges for the exact original.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sensei.compression.ccr import CCRStore
from sensei.compression.router import ContentRouter
from sensei.config import settings
from sensei.savings import get_savings_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hooks", tags=["hooks"])

# A hook payload is one tool result. Anything larger is not worth parsing in
# the request path of someone else's tool call.
_MAX_BODY = 32 * 1024 * 1024

_router: ContentRouter | None = None


def _pipeline() -> ContentRouter:
    """Built once — ContentRouter compiles patterns and may load the Rust core.

    Shares the on-disk CCR store with the gateway and with `sensei mcp`, so an
    id handed out here is retrievable from the MCP server the tool spawned.
    """
    global _router
    if _router is None:
        _router = ContentRouter(ccr_store=CCRStore(), enable_caching=True)
    return _router


def _reset_pipeline() -> None:
    """For tests that change the CCR location."""
    global _router
    _router = None


# ── The one compression step every dialect shares ───────────────────────────


@dataclass
class Shrunk:
    text: str
    before: int
    after: int


def _retrieve_hint(ccr_id: str, before: int, after: int, tool_prefix: str) -> str:
    return (
        f"\n[sensei: compressed {before:,} → {after:,} tokens. Exact original: "
        f'{tool_prefix}sensei_retrieve(ccr_id="{ccr_id}")]'
    )


def shrink(text: str, *, edit_target: bool = True, tool_prefix: str = "") -> Shrunk | None:
    """Compress one output, or None when it is not worth replacing.

    Small outputs, outputs that barely shrink, and anything compression could
    not store an original for are all left alone: a replacement the model
    cannot undo has to save a lot to be worth it, and here it never has to.
    """
    if not settings.hook_compression or len(text) < settings.hook_min_chars:
        return None
    result = _pipeline().compress(text, edit_target=edit_target)
    if result.ccr_id is None or result.original_tokens <= 0:
        return None
    hint = _retrieve_hint(
        result.ccr_id, result.original_tokens, result.compressed_tokens, tool_prefix
    )
    out = result.compressed + hint
    after = max(1, len(out) // 4)
    if after > result.original_tokens * (1 - settings.hook_min_saving):
        return None
    return Shrunk(out, result.original_tokens, after)


def _record(label: str, shrunk: list[Shrunk]) -> None:
    if not shrunk:
        return
    before = sum(s.before for s in shrunk)
    after = sum(s.after for s in shrunk)
    get_savings_tracker().record(
        {
            "prompt_tokens_before": before,
            "prompt_tokens_after": after,
            "tokens_saved": max(0, before - after),
            "blocks_compressed": len(shrunk),
        },
        tool=label,
    )


# ── Request plumbing ────────────────────────────────────────────────────────


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host in ("localhost", "testclient"):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _refuse(request: Request) -> bool:
    """Only this machine, and never a web page.

    The hooks are called by local processes. A browser page could reach a
    loopback port too, and would announce itself with an Origin header — which
    no hook runner sends.
    """
    client = request.client.host if request.client else None
    if not _is_loopback(client):
        return True
    origin = request.headers.get("origin")
    return bool(origin) and not _is_loopback(urlparse(origin).hostname)


async def _payload(request: Request) -> dict[str, Any] | None:
    raw = await request.body()
    if not raw or len(raw) > _MAX_BODY:
        return None
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _empty() -> JSONResponse:
    return JSONResponse({})


async def _guarded(request: Request, handler: Any) -> JSONResponse:
    """Run a dialect's handler; any failure is the empty, no-change answer."""
    if _refuse(request):
        return JSONResponse({}, status_code=403)
    payload = await _payload(request)
    if payload is None:
        return _empty()
    try:
        answer = await asyncio.to_thread(handler, payload, request.headers)
    except Exception as exc:
        logger.warning("Hook compression failed open: %s", exc)
        return _empty()
    return JSONResponse(answer or {})


# ── Claude Code ─────────────────────────────────────────────────────────────

# Read/Edit/Write/NotebookEdit and anything else not listed here pass through.
_CLAUDE_FIELDS: dict[str, tuple[tuple[str, bool], ...]] = {
    # tool: ((field, edit_target), ...)
    "Bash": (("stdout", True), ("stderr", True)),
    "Grep": (("content", True),),
    "WebFetch": (("result", False),),
}


def _walk_strings(value: Any, fn: Any) -> Any:
    """Apply ``fn`` to every string under ``text`` keys, or a bare string."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_walk_strings(v, fn) for v in value]
    if isinstance(value, dict):
        return {
            k: (fn(v) if k == "text" and isinstance(v, str) else _walk_strings(v, fn))
            if k in ("text", "content", "results", "result")
            else v
            for k, v in value.items()
        }
    return value


def _claude(payload: dict[str, Any], _headers: Any) -> dict[str, Any]:
    tool = str(payload.get("tool_name") or "")
    response = payload.get("tool_response")
    if payload.get("hook_event_name") not in (None, "PostToolUse") or response is None:
        return {}
    if tool.startswith("mcp__sensei__"):
        # Sensei's own tools: sensei_retrieve hands back an original on
        # purpose, and compressing it again would be a loop.
        return {}

    done: list[Shrunk] = []

    def squeeze(text: str, edit_target: bool = True) -> str:
        s = shrink(text, edit_target=edit_target, tool_prefix="mcp__sensei__")
        if s is None:
            return text
        done.append(s)
        return s.text

    updated: Any
    if tool in _CLAUDE_FIELDS and isinstance(response, dict):
        updated = dict(response)
        for field, edit_target in _CLAUDE_FIELDS[tool]:
            if isinstance(updated.get(field), str):
                updated[field] = squeeze(updated[field], edit_target)
    elif tool == "Glob" and isinstance(response, dict):
        updated = _claude_glob(response, done)
    elif tool == "WebSearch" or tool.startswith("mcp__"):
        updated = _walk_strings(response, lambda t: squeeze(t, tool.startswith("mcp__")))
    else:
        return {}

    if not done:
        return {}
    _record("Claude Code (hook)", done)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": updated,
        }
    }


def _claude_glob(response: dict[str, Any], done: list[Shrunk]) -> dict[str, Any]:
    """A long path list keeps its first entries; the rest is one retrievable id.

    The output keeps Glob's shape — the tool's schema is checked, and a
    rewrite that does not match it is thrown away by Claude Code.
    """
    names = response.get("filenames")
    limit = max(10, settings.hook_max_paths)
    if not isinstance(names, list) or len(names) <= limit:
        return response
    full = "\n".join(str(n) for n in names)
    store = _pipeline().ccr_store
    if store is None:  # pragma: no cover — the pipeline always has one
        return response
    kept = names[:limit]
    ccr_id = store.store(full, "\n".join(str(n) for n in kept), "text")
    before = max(1, len(full) // 4)
    note = (
        f"[sensei: {len(names) - limit:,} more paths not shown. Full list: "
        f'mcp__sensei__sensei_retrieve(ccr_id="{ccr_id}")]'
    )
    after = max(1, (len("\n".join(str(n) for n in kept)) + len(note)) // 4)
    done.append(Shrunk(note, before, after))
    return {**response, "filenames": [*kept, note], "truncated": True}


@router.post("/claude/post-tool-use")
async def claude_post_tool_use(request: Request) -> JSONResponse:
    return await _guarded(request, _claude)


# ── GitHub Copilot CLI ──────────────────────────────────────────────────────

_FILE_TOOLS = re.compile(
    r"(?i)^(view|read|read_file|read_many_files|edit|create|write|write_file|"
    r"str_replace|str_replace_editor|replace|apply_patch|patch|multi_?edit|notebook.*)$"
)


def _copilot(payload: dict[str, Any], _headers: Any) -> dict[str, Any]:
    tool = str(payload.get("toolName") or "")
    result = payload.get("toolResult")
    if _FILE_TOOLS.match(tool) or "sensei" in tool.lower() or not isinstance(result, dict):
        return {}
    if result.get("resultType") != "success" or not isinstance(result.get("textResultForLlm"), str):
        return {}
    s = shrink(result["textResultForLlm"])
    if s is None:
        return {}
    _record("Copilot CLI (hook)", [s])
    return {"modifiedResult": {"resultType": "success", "textResultForLlm": s.text}}


@router.post("/copilot/post-tool-use")
async def copilot_post_tool_use(request: Request) -> JSONResponse:
    return await _guarded(request, _copilot)


# ── Gemini CLI ──────────────────────────────────────────────────────────────


def _gemini(payload: dict[str, Any], _headers: Any) -> dict[str, Any]:
    tool = str(payload.get("tool_name") or "")
    response = payload.get("tool_response")
    if _FILE_TOOLS.match(tool) or "sensei" in tool.lower() or not isinstance(response, dict):
        return {}
    if response.get("error"):
        return {}
    content = response.get("llmContent")
    if isinstance(content, list):
        if not all(isinstance(p, dict) and isinstance(p.get("text"), str) for p in content):
            return {}  # images or other parts: not something to flatten
        content = "".join(p["text"] for p in content)
    if not isinstance(content, str):
        return {}
    s = shrink(content, edit_target=not tool.startswith("web"))
    if s is None:
        return {}
    _record("Gemini CLI (hook)", [s])
    # Gemini's documented way to replace what the model sees: the reason of a
    # "deny" decision stands in for the tool result.
    return {"decision": "deny", "reason": s.text}


@router.post("/gemini/after-tool")
async def gemini_after_tool(request: Request) -> JSONResponse:
    return await _guarded(request, _gemini)


# ── Cursor (MCP tools only) ─────────────────────────────────────────────────


def _cursor(payload: dict[str, Any], _headers: Any) -> dict[str, Any]:
    tool = str(payload.get("tool_name") or "")
    # Cursor can only replace the output of MCP tools; anything else would be
    # compressed, recorded as saved, and then ignored.
    if "mcp" not in tool.lower() or "sensei" in tool.lower():
        return {}
    raw = payload.get("tool_output")
    if not isinstance(raw, str):
        return {}
    done: list[Shrunk] = []

    def squeeze(text: str) -> str:
        s = shrink(text)
        if s is None:
            return text
        done.append(s)
        return s.text

    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    updated = _walk_strings(parsed, squeeze)
    if not done:
        return {}
    _record("Cursor (hook)", done)
    return {"updated_mcp_tool_output": updated}


@router.post("/cursor/post-tool-use")
async def cursor_post_tool_use(request: Request) -> JSONResponse:
    return await _guarded(request, _cursor)


# ── Generic: the opencode / Kilo plugin ─────────────────────────────────────


def _generic(payload: dict[str, Any], headers: Any) -> dict[str, Any]:
    tool = str(payload.get("tool") or "")
    text = payload.get("text")
    if not isinstance(text, str) or _FILE_TOOLS.match(tool) or "sensei" in tool.lower():
        return {}
    s = shrink(text, edit_target=not tool.lower().startswith("web"))
    if s is None:
        return {}
    label = str(headers.get("x-sensei-client") or "plugin (hook)")[:64]
    _record(label, [s])
    return {"text": s.text, "tokens_before": s.before, "tokens_after": s.after}


@router.post("/compress")
async def compress_text(request: Request) -> JSONResponse:
    return await _guarded(request, _generic)

"""Tool definitions: smaller, and on Anthropic optionally deferred.

Every request carries the full tool list. For an agent with MCP servers
attached that is thousands of tokens, re-sent every turn — cached, but still
written once per conversation and read on every request.

**Schema compaction (on by default).** JSON-schema annotation keywords that
describe a schema to a *human* — ``$schema``, ``$comment``, ``examples``,
``title``, ``markdownDescription``, ``readOnly``, ``writeOnly``,
``deprecated`` — are removed. They are only ever removed where they are schema
keywords: a *property* called ``title`` under ``properties`` is a parameter and
stays. The transform is deterministic and memoised, so the tool block is the
same bytes on every turn.

**Description shortening (opt-in).** Tool descriptions are cut to the first
paragraph, at a sentence boundary, within ``gateway_tool_description_max_chars``;
parameter descriptions to their first sentence. This changes what the model is
told, so it is off unless asked for.

**Tool search (opt-in, first-party Anthropic only).** With at least
``gateway_tool_search_min_tools`` tools, everything but the core tools is marked
``defer_loading`` and the regex tool-search tool is added, so deferred
definitions only enter the context once the model searches for them. A
``cache_control`` on a deferred tool is moved to the last resident one. Stands
down when the client already defers anything or brings its own search tool.

None of this touches a Claude-subscription (OAuth) request unless
``gateway_oauth_tool_changes`` is set.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from sensei.config import settings
from sensei.gateway.session import digest

ANNOTATIONS = frozenset(
    {
        "$schema",
        "$comment",
        "examples",
        "title",
        "markdownDescription",
        "readOnly",
        "writeOnly",
        "deprecated",
    }
)

# Keywords whose value is a map of name → subschema.
_SCHEMA_MAPS = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")
# Keywords whose value is a subschema or a list of them.
_SCHEMA_ONE = (
    "items",
    "additionalProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
    "contains",
    "propertyNames",
    "not",
    "if",
    "then",
    "else",
    "additionalItems",
)
_SCHEMA_LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")


def compact_schema(schema: Any, *, shorten: bool = False) -> Any:
    if isinstance(schema, list):  # `items: [..]` (draft-04 tuple form)
        return [compact_schema(s, shorten=shorten) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in ANNOTATIONS:
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            out[key] = {name: compact_schema(sub, shorten=shorten) for name, sub in value.items()}
        elif key in _SCHEMA_ONE or key in _SCHEMA_LISTS:
            out[key] = compact_schema(value, shorten=shorten)
        elif key == "description" and shorten and isinstance(value, str):
            out[key] = first_sentence(value)
        else:
            out[key] = value
    return out


_SENTENCE_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789`\"'([")


def split_sentences(text: str, maxsplit: int = 0) -> list[str]:
    """Split after ``.``/``!``/``?`` plus whitespace, before a capital or digit.

    A single left-to-right scan rather than a regex: tool descriptions come
    from whatever MCP server the client attached, and a backtracking pattern
    over a long whitespace run is a way to stall the gateway.
    """
    parts: list[str] = []
    start = i = 0
    n = len(text)
    while i < n:
        if text[i] in ".!?" and i + 1 < n and text[i + 1].isspace():
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] in _SENTENCE_START:
                parts.append(text[start : i + 1])
                start = j
                if maxsplit and len(parts) >= maxsplit:
                    break
            i = j
            continue
        i += 1
    parts.append(text[start:])
    return parts


def first_sentence(text: str) -> str:
    text = text.strip()
    para = text.split("\n\n", 1)[0].strip()
    return split_sentences(para, maxsplit=1)[0].strip()


def shorten_description(text: str, max_chars: int) -> str:
    """First paragraph, then whole sentences up to ``max_chars``."""
    para = text.strip().split("\n\n", 1)[0].strip()
    if len(para) <= max_chars:
        return para
    out = ""
    for sentence in split_sentences(para):
        candidate = f"{out} {sentence}".strip()
        if len(candidate) > max_chars:
            break
        out = candidate
    return out or para[:max_chars].rstrip()


_memo: OrderedDict[str, dict[str, Any]] = OrderedDict()
_memo_lock = threading.Lock()


def _schema_key(api: str, tool: dict[str, Any]) -> str | None:
    return {"anthropic": "input_schema", "responses": "parameters"}.get(api)


def compact_tool(api: str, tool: Any) -> Any:
    """One tool definition, compacted. Server tools pass through untouched."""
    if not isinstance(tool, dict):
        return tool
    shorten = settings.gateway_tool_description_max_chars > 0
    key = digest([api, shorten, settings.gateway_tool_description_max_chars, tool])
    with _memo_lock:
        hit = _memo.get(key)
        if hit is not None:
            _memo.move_to_end(key)
            return hit
    out = _compact_uncached(api, tool, shorten)
    with _memo_lock:
        _memo[key] = out
        while len(_memo) > 2048:
            _memo.popitem(last=False)
    return out


def _compact_uncached(api: str, tool: dict[str, Any], shorten: bool) -> dict[str, Any]:
    limit = settings.gateway_tool_description_max_chars
    if api == "openai":
        fn = tool.get("function")
        if tool.get("type", "function") != "function" or not isinstance(fn, dict):
            return tool
        new_fn = dict(fn)
        if isinstance(fn.get("parameters"), dict):
            new_fn["parameters"] = compact_schema(fn["parameters"], shorten=shorten)
        if shorten and isinstance(fn.get("description"), str):
            new_fn["description"] = shorten_description(fn["description"], limit)
        return {**tool, "function": new_fn}

    schema_key = _schema_key(api, tool)
    # Anthropic server tools (`type: web_search_20260209`, …) and Responses
    # built-ins (`web_search`, `file_search`, …) have no schema of ours.
    if api == "anthropic" and tool.get("type") not in (None, "custom"):
        return tool
    if api == "responses" and tool.get("type") != "function":
        return tool
    out = dict(tool)
    if schema_key and isinstance(tool.get(schema_key), dict):
        out[schema_key] = compact_schema(tool[schema_key], shorten=shorten)
    if shorten and isinstance(tool.get("description"), str):
        out["description"] = shorten_description(tool["description"], limit)
    return out


def compact_tools(api: str, tools: list[Any]) -> list[Any]:
    return [compact_tool(api, t) for t in tools]


# ── Anthropic tool search ───────────────────────────────────────────────────

SEARCH_TOOL = {"type": "tool_search_tool_regex_20251119", "name": "tool_search_tool_regex"}

# Tools an agent uses on almost every turn. Deferring them would add a search
# round-trip to the common path to save a few hundred cached tokens.
CORE_TOOLS = frozenset(
    {
        "bash",
        "read",
        "write",
        "edit",
        "multiedit",
        "glob",
        "grep",
        "ls",
        "task",
        "agent",
        "todowrite",
        "todo",
        "webfetch",
        "skill",
        "sensei_retrieve",
    }
)


def _is_custom(tool: Any) -> bool:
    return isinstance(tool, dict) and tool.get("type") in (None, "custom") and "name" in tool


def apply_tool_search(tools: list[Any], *, first_party: bool) -> tuple[list[Any], int]:
    """Defer non-core tools. Returns (tools, how many were deferred)."""
    if not settings.gateway_tool_search or not first_party:
        return tools, 0
    custom = [t for t in tools if _is_custom(t)]
    if len(custom) < max(2, settings.gateway_tool_search_min_tools):
        return tools, 0
    for t in tools:
        if not isinstance(t, dict):
            return tools, 0
        if t.get("defer_loading") or str(t.get("type", "")).startswith("tool_search_tool"):
            return tools, 0  # the client is already doing this

    out: list[Any] = []
    moved_mark: Any = None
    deferred = 0
    for t in tools:
        if _is_custom(t) and str(t["name"]).lower() not in CORE_TOOLS:
            new = {k: v for k, v in t.items() if k != "cache_control"}
            if "cache_control" in t:
                moved_mark = t["cache_control"]
            new["defer_loading"] = True
            out.append(new)
            deferred += 1
        else:
            out.append(t)
    if not deferred:
        return tools, 0
    out.append(dict(SEARCH_TOOL))
    if moved_mark is not None:
        for i in range(len(out) - 1, -1, -1):
            t = out[i]
            if _is_custom(t) and not t.get("defer_loading"):
                if "cache_control" not in t:
                    out[i] = {**t, "cache_control": moved_mark}
                break
    return out, deferred


def deferred_tokens(tools: list[Any]) -> int:
    """Approximate tokens of definitions the model will not see up front."""
    from sensei.gateway.session import canon

    return sum(len(canon(t)) // 4 for t in tools if isinstance(t, dict) and t.get("defer_loading"))

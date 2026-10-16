"""Where tool calls and tool results live in each wire format.

Three APIs, three shapes for the same two things:

==============  ====================================  ==============================
API             tool call                             tool result
==============  ====================================  ==============================
anthropic       assistant ``tool_use`` block          user ``tool_result`` block
openai (chat)   assistant ``tool_calls[]``            ``role: tool`` message
responses       ``function_call`` / ``custom_*`` item ``*_call_output`` item
==============  ====================================  ==============================

Everything cross-turn (dedup, stale reads, retrieve substitution) works on the
neutral records below, with a *path* to the string inside the message so the
caller can swap it without knowing the format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

Path = tuple[Any, ...]

RESPONSES_TOOL_OUTPUTS = (
    "function_call_output",
    "custom_tool_call_output",
    "local_shell_call_output",
    "mcp_call_output",
)


@dataclass
class ToolCall:
    call_id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolText:
    path: Path
    call_id: str
    text: str
    is_error: bool = False


def _json_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError:
            return {"input": raw}
        return value if isinstance(value, dict) else {}
    return {}


def tool_calls(api: str, message: Any) -> list[ToolCall]:
    if not isinstance(message, dict):
        return []
    out: list[ToolCall] = []
    if api == "anthropic":
        if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
            return []
        for block in message["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                out.append(
                    ToolCall(
                        str(block.get("id", "")),
                        str(block.get("name", "")),
                        _json_args(block.get("input")),
                    )
                )
    elif api == "openai":
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict) and isinstance(call.get("function"), dict):
                fn = call["function"]
                out.append(
                    ToolCall(
                        str(call.get("id", "")),
                        str(fn.get("name", "")),
                        _json_args(fn.get("arguments")),
                    )
                )
    else:
        kind = message.get("type")
        if kind == "function_call":
            out.append(
                ToolCall(
                    str(message.get("call_id", "")),
                    str(message.get("name", "")),
                    _json_args(message.get("arguments")),
                )
            )
        elif kind == "custom_tool_call":
            out.append(
                ToolCall(
                    str(message.get("call_id", "")),
                    str(message.get("name", "")),
                    {"input": message.get("input")},
                )
            )
    return out


def _texts_in(value: Any, base: Path, part_types: tuple[str, ...]) -> list[tuple[Path, str]]:
    if isinstance(value, str):
        return [(base, value)]
    if isinstance(value, list):
        return [
            ((*base, k, "text"), part["text"])
            for k, part in enumerate(value)
            if isinstance(part, dict)
            and part.get("type") in part_types
            and isinstance(part.get("text"), str)
        ]
    return []


def tool_texts(api: str, message: Any) -> list[ToolText]:
    if not isinstance(message, dict):
        return []
    out: list[ToolText] = []
    if api == "anthropic":
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            return []
        for j, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                for path, text in _texts_in(
                    block.get("content"), ("content", j, "content"), ("text",)
                ):
                    out.append(
                        ToolText(
                            path,
                            str(block.get("tool_use_id", "")),
                            text,
                            bool(block.get("is_error")),
                        )
                    )
    elif api == "openai":
        if message.get("role") not in ("tool", "function"):
            return []
        for path, text in _texts_in(message.get("content"), ("content",), ("text",)):
            out.append(ToolText(path, str(message.get("tool_call_id", "")), text))
    else:
        if message.get("type") not in RESPONSES_TOOL_OUTPUTS:
            return []
        types = ("input_text", "output_text", "text")
        for path, text in _texts_in(message.get("output"), ("output",), types):
            out.append(ToolText(path, str(message.get("call_id", "")), text))
    return out


def get_path(value: Any, path: Path) -> Any:
    for step in path:
        value = value[step]
    return value


def set_path(value: Any, path: Path, new: Any) -> Any:
    """A copy of ``value`` with ``path`` replaced; untouched branches shared."""
    if not path:
        return new
    head, rest = path[0], path[1:]
    if isinstance(value, dict):
        return {**value, head: set_path(value[head], rest, new)}
    out = list(value)
    out[head] = set_path(value[head], rest, new)
    return out


def result_message(api: str, call_id: str, text: str) -> dict[str, Any]:
    """A tool-result message answering ``call_id`` with ``text``."""
    if api == "anthropic":
        return {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": call_id, "content": text}],
        }
    if api == "openai":
        return {"role": "tool", "tool_call_id": call_id, "content": text}
    return {"type": "function_call_output", "call_id": call_id, "output": text}

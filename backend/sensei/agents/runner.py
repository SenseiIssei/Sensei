"""A bounded, provider-agnostic ReAct agent loop.

Works with any provider (no native function-calling needed): the model emits a
single JSON object per turn — either a tool call or a final answer. Tool results
are compressed before being fed back, so long file/search outputs stay cheap.
"""
from __future__ import annotations

import json
from typing import Any

from sensei.agents.toolbox import build_default_registry
from sensei.agents.tools import ToolRegistry
from sensei.compression.router import ContentRouter
from sensei.config import settings
from sensei.models.base import ChatMessage, Role
from sensei.models.registry import get_provider

_cr = ContentRouter(enable_caching=False)

_SYSTEM = """You are Sensei, an autonomous assistant that can use tools.

Available tools:
{tools}

On every turn, reply with EXACTLY ONE JSON object and nothing else:
- To use a tool:  {{"thought": "why", "tool": "<name>", "args": {{...}}}}
- To finish:      {{"thought": "why", "answer": "<final answer for the user>"}}

Gather what you need with tools, then give the final answer. Be concise."""


def _tool_docs(registry: ToolRegistry) -> str:
    lines = []
    for t in registry.list():
        args = ", ".join((t.parameters.get("properties") or {}).keys())
        lines.append(f"- {t.name}({args}): {t.description}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


async def run_agent(
    task: str,
    registry: ToolRegistry | None = None,
    max_steps: int | None = None,
    provider: Any = None,
) -> dict[str, Any]:
    registry = registry or build_default_registry()
    max_steps = max_steps or settings.agent_max_steps
    provider = provider or await get_provider()

    messages: list[ChatMessage] = [
        ChatMessage(role=Role.system, content=_SYSTEM.format(tools=_tool_docs(registry))),
        ChatMessage(role=Role.user, content=task),
    ]
    steps: list[dict[str, Any]] = []

    for _ in range(max_steps):
        completion = await provider.chat(messages=messages, max_tokens=1024)
        action = _extract_json(completion.content)
        if action is None:
            return {"answer": completion.content, "steps": steps, "stopped": "unparsable"}
        if "answer" in action:
            return {"answer": action["answer"], "steps": steps, "stopped": "done"}

        tool = action.get("tool")
        args = action.get("args") or {}
        result = await registry.execute(tool, args) if tool else {"error": "no tool specified"}
        steps.append({"tool": tool, "args": args, "result": result})

        result_str = json.dumps(result, ensure_ascii=False)[:8000]
        if settings.compression_enabled:
            result_str = _cr.compress(result_str).compressed
        messages.append(ChatMessage(role=Role.assistant, content=completion.content))
        messages.append(ChatMessage(role=Role.user, content=f"Tool result for {tool}: {result_str}"))

    return {"answer": "Reached the step limit before finishing.", "steps": steps, "stopped": "max_steps"}

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """Represents a tool that the AI model can call."""
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Awaitable[Any]] | None = None

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry of available tools for the AI model."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def to_openai_schemas(self) -> list[dict[str, Any]]:
        """Get all tools in OpenAI function-calling format."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool by name."""
        tool = self.get(name)
        if tool is None:
            return {"error": f"Tool '{name}' not found"}
        if tool.handler is None:
            return {"error": f"Tool '{name}' has no handler"}
        try:
            return await tool.handler(**arguments)
        except Exception as e:
            logger.error("Tool execution error (%s): %s", name, e)
            return {"error": str(e)}


# ── Built-in tools ──────────────────────────────────────────

async def retrieve_original_tool_handler(
    ccr_id: str,
    content_router: Any = None,
) -> dict[str, Any]:
    """Retrieve the original uncompressed content from CCR.

    This tool is exposed to the model so it can request full content
    when compressed versions are insufficient.
    """
    if content_router is None:
        return {"error": "Content router not available"}
    original = content_router.retrieve_original(ccr_id)
    if original is None:
        return {"error": f"CCR entry '{ccr_id}' not found or expired"}
    return {"content": original}


def retrieve_original_tool(content_router: Any) -> Tool:
    """Create the CCR retrieve tool bound to a content router."""
    async def handler(ccr_id: str) -> dict[str, Any]:
        return await retrieve_original_tool_handler(ccr_id, content_router)

    return Tool(
        name="sensei_retrieve",
        description=(
            "Retrieve the original uncompressed content for a given CCR ID. "
            "Use this when a compressed message doesn't have enough detail."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ccr_id": {
                    "type": "string",
                    "description": "The CCR ID from the compressed message metadata",
                }
            },
            "required": ["ccr_id"],
        },
        handler=handler,
    )

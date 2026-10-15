"""MCP proxy — other MCP servers behind two small tools, with compressed results.

Every MCP server an agent connects to puts its whole tool list into the
context window on every turn: names, descriptions, JSON schemas. Five servers
with twenty tools each is a few thousand tokens before the user has typed a
word, and reverse-engineering servers (REA, GhidraMCP, ida-pro-mcp, r2mcp) are
the worst case — dozens of tools, and results that are pages of disassembly.

Configure the servers here instead of in the agent, and the agent sees two
tools:

    sensei_find_tools   search the servers' tools by keyword; returns schemas
                        only for the handful that match
    sensei_call_tool    call one of them; the result comes back compressed,
                        and anything still too long arrives as a first page
                        plus a ccr_id that `sensei_retrieve` pages through

The config file uses the same shape as Claude Desktop's, so an existing
``mcpServers`` block can be pasted in as is::

    {
      "mcpServers": {
        "rea":    {"command": "npx", "args": ["-y", "rea-agents", "mcp"]},
        "ghidra": {"url": "http://127.0.0.1:8089/mcp"}
      }
    }

Default location: ``~/.sensei/mcp-servers.json`` (``SENSEI_MCP_SERVERS_FILE``).

Downstream servers are separate processes and stay that way — Sensei talks to
them over MCP, so a GPL-licensed server never becomes part of MIT-licensed
Sensei. And as with any tool an agent can call: point it at software you are
entitled to analyse.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sensei.config import settings

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class RemoteTool:
    server: str
    name: str
    description: str
    schema: dict[str, Any]

    def card(self, *, with_schema: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "server": self.server,
            "tool": self.name,
            "description": _shorten(self.description, 300),
        }
        if with_schema:
            out["input_schema"] = self.schema
        return out


def _shorten(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _words(text: str) -> list[str]:
    # snake_case and camelCase both split into words: `decompile_function`
    # and `decompileFunction` should both match "decompile".
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "").replace("_", " ")
    return _WORD.findall(spaced.lower())


def load_config(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """The ``mcpServers`` mapping, or ``{}`` when there is no usable file."""
    target = path or settings.mcp_servers_path
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring %s: %s", target, exc)
        return {}
    servers = data.get("mcpServers", data) if isinstance(data, dict) else {}
    return {
        str(name): spec
        for name, spec in servers.items()
        if isinstance(spec, dict)
        and (spec.get("command") or spec.get("url"))
        # A proxy that lists itself would recurse until something gave out.
        and not (spec.get("command") == "sensei" and "mcp" in (spec.get("args") or []))
    }


class _Connection:
    """One downstream server, owned by one long-lived task.

    `mcp.Client` is an async context manager built on anyio task groups, and
    those must be entered and exited by the same task. A tool call arrives on
    whichever task the MCP server handed it, so the client cannot live there:
    a worker task opens it once, and calls are posted to it through a queue.
    """

    def __init__(self, target: Any) -> None:
        self._target = target
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        from mcp import Client

        try:
            async with Client(self._target, read_timeout_seconds=120) as client:
                self._ready.set_result(None)
                while True:
                    job = await self._queue.get()
                    if job is None:
                        return
                    work, future = job
                    try:
                        result = await work(client)
                    except Exception as exc:
                        if not future.done():
                            future.set_exception(exc)
                    else:
                        if not future.done():
                            future.set_result(result)
        except Exception as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
            # Fail anything still waiting rather than leaving it hanging.
            while not self._queue.empty():
                job = self._queue.get_nowait()
                if job is not None and not job[1].done():
                    job[1].set_exception(exc)

    async def submit(self, work: Any) -> Any:
        await self._ready
        if self._task.done():
            raise ConnectionError("the server connection has closed")
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        await self._queue.put((work, future))
        return await future

    async def close(self) -> None:
        if not self._task.done():
            await self._queue.put(None)
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (TimeoutError, Exception):
                self._task.cancel()


@dataclass
class ProxyHub:
    """Lazily-connected MCP clients for every configured server."""

    servers: dict[str, Any] = field(default_factory=dict)
    _connections: dict[str, _Connection] = field(default_factory=dict)
    _tools: list[RemoteTool] | None = None
    _errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_config(cls, path: Path | None = None) -> ProxyHub:
        return cls(servers=load_config(path))

    def _target(self, spec: Any) -> Any:
        """What `mcp.Client` should connect to for one config entry.

        Tests pass an in-process server object directly.
        """
        if not isinstance(spec, dict):
            return spec
        if spec.get("url"):
            return spec["url"]
        from mcp.client.stdio import StdioServerParameters

        return StdioServerParameters(
            command=spec["command"],
            args=[str(a) for a in spec.get("args") or []],
            env={str(k): str(v) for k, v in (spec.get("env") or {}).items()} or None,
            cwd=spec.get("cwd"),
        )

    async def _submit(self, name: str, work: Any) -> Any:
        conn = self._connections.get(name)
        if conn is None or conn._task.done():
            conn = _Connection(self._target(self.servers[name]))
            self._connections[name] = conn
        try:
            result = await conn.submit(work)
        except Exception as exc:
            self._errors[name] = str(exc) or type(exc).__name__
            raise
        self._errors.pop(name, None)
        return result

    async def tools(self, *, refresh: bool = False) -> list[RemoteTool]:
        if self._tools is not None and not refresh:
            return self._tools
        found: list[RemoteTool] = []
        for name in self.servers:
            try:
                listed = await self._submit(name, lambda client: client.list_tools())
            except Exception as exc:
                self._errors[name] = str(exc) or type(exc).__name__
                logger.warning("MCP server %r unavailable: %s", name, exc)
                continue
            for tool in listed.tools:
                found.append(
                    RemoteTool(
                        server=name,
                        name=tool.name,
                        description=tool.description or "",
                        schema=dict(_field(tool, "input_schema", "inputSchema") or {}),
                    )
                )
        self._tools = found
        return found

    async def find(self, query: str, server: str | None, limit: int) -> dict[str, Any]:
        tools = [t for t in await self.tools() if server in (None, "", t.server)]
        terms = _words(query)
        if not terms:
            # No query: a compact table of contents, no schemas.
            return {
                "servers": sorted(self.servers),
                "unavailable": self._errors,
                "tools": [t.card(with_schema=False) for t in tools],
            }

        # BM25-flavoured scoring over name + description, name matches doubled.
        docs = [(t, _words(t.name) * 2 + _words(t.description)) for t in tools]
        n = len(docs) or 1
        df: dict[str, int] = {}
        for _, words in docs:
            for w in set(words):
                df[w] = df.get(w, 0) + 1
        scored = []
        for tool, words in docs:
            score = 0.0
            for term in terms:
                tf = sum(1 for w in words if w == term or w.startswith(term))
                if tf:
                    idf = math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
                    score += idf * tf / (tf + 1.2)
            if score > 0:
                scored.append((score, tool))
        scored.sort(key=lambda pair: -pair[0])
        return {
            "query": query,
            "matches": [t.card(with_schema=True) for _, t in scored[: max(1, limit)]],
            "unavailable": self._errors,
        }

    async def call(self, server: str, tool: str, arguments: dict[str, Any]) -> Any:
        if server not in self.servers:
            raise KeyError(server)
        return await self._submit(server, lambda client: client.call_tool(tool, arguments))

    async def close(self) -> None:
        for conn in self._connections.values():
            await conn.close()
        self._connections.clear()
        self._tools = None


def _field(obj: Any, snake: str, camel: str) -> Any:
    """mcp 2.x types are snake_case; 1.x and raw dicts are camelCase."""
    value = getattr(obj, snake, None)
    return value if value is not None else getattr(obj, camel, None)


def result_text(result: Any) -> tuple[str, bool]:
    """Flatten a CallToolResult to text. Returns (text, is_error).

    Images and audio are described rather than inlined: base64 is the least
    compressible thing an agent can put in its context, and a model that needs
    to see the picture should be given it by a tool that can show it.
    """
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        kind = getattr(block, "type", "")
        if kind == "text":
            parts.append(block.text)
        elif kind in ("image", "audio"):
            parts.append(f"[{kind}: {_field(block, 'mime_type', 'mimeType') or 'binary'} omitted]")
        elif kind == "resource":
            resource = getattr(block, "resource", None)
            text = getattr(resource, "text", None)
            parts.append(text if text is not None else f"[resource {getattr(resource, 'uri', '')}]")
        else:
            parts.append(f"[{kind or 'content'} omitted]")
    structured = _field(result, "structured_content", "structuredContent")
    if not parts and structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False))
    return "\n".join(parts), bool(_field(result, "is_error", "isError"))

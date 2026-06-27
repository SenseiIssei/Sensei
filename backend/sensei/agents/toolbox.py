"""Safe, read-only tools for the agent, sandboxed to ``agent_root``.

All file paths are resolved relative to the configured root and rejected if they
escape it (no traversal). No write or code-execution tools by default — keeping
the agent safe to expose. Plus a ``rag_search`` over the indexed knowledge base.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sensei.agents.tools import Tool, ToolRegistry
from sensei.config import settings

_MAX_READ = 20_000
_MAX_HITS = 50
_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "target", ".hf-cache"}


def _root() -> Path:
    return Path(settings.agent_root).resolve()


def _safe(path: str) -> Path | None:
    """Resolve `path` under the root; None if it escapes the sandbox."""
    p = (_root() / path).resolve()
    try:
        p.relative_to(_root())
    except ValueError:
        return None
    return p


async def list_files(path: str = ".") -> dict[str, Any]:
    p = _safe(path)
    if p is None or not p.exists():
        return {"error": "path not found or outside the sandbox"}
    if p.is_file():
        return {"path": path, "entries": [p.name]}
    entries = []
    for c in sorted(p.iterdir(), key=lambda x: x.name):
        if c.name in _SKIP_DIRS:
            continue
        entries.append(c.name + ("/" if c.is_dir() else ""))
        if len(entries) >= 200:
            break
    return {"path": path, "entries": entries}


async def read_file(path: str) -> dict[str, Any]:
    p = _safe(path)
    if p is None or not p.is_file():
        return {"error": "file not found or outside the sandbox"}
    try:
        data = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": str(e)}
    truncated = len(data) > _MAX_READ
    return {"path": path, "content": data[:_MAX_READ], "truncated": truncated}


async def search_files(query: str, glob: str = "**/*") -> dict[str, Any]:
    root = _root()
    hits: list[dict[str, Any]] = []
    q = query.lower()
    for f in root.glob(glob):
        if len(hits) >= _MAX_HITS:
            break
        if not f.is_file() or any(part in _SKIP_DIRS for part in f.parts):
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if q in line.lower():
                    hits.append({"file": str(f.relative_to(root)), "line": i, "text": line.strip()[:160]})
                    if len(hits) >= _MAX_HITS:
                        break
        except OSError:
            continue
    return {"query": query, "matches": hits}


async def rag_search(query: str) -> dict[str, Any]:
    from sensei.rag.store import get_store

    return {"results": get_store().search(query, 4)}


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool(
        name="list_files",
        description="List files and directories under a path (relative to the workspace root).",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": []},
        handler=list_files,
    ))
    reg.register(Tool(
        name="read_file",
        description="Read a UTF-8 text file (relative to the workspace root).",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=read_file,
    ))
    reg.register(Tool(
        name="search_files",
        description="Search file contents for a substring; returns file/line matches.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}, "glob": {"type": "string"}},
            "required": ["query"],
        },
        handler=search_files,
    ))
    reg.register(Tool(
        name="rag_search",
        description="Search the indexed knowledge base (RAG) for relevant chunks.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        handler=rag_search,
    ))

    from sensei.agents.webtools import fetch_url, run_python, web_search

    reg.register(Tool(
        name="fetch_url",
        description="Fetch an http(s) URL and return its text content (SSRF-guarded).",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        handler=fetch_url,
    ))
    reg.register(Tool(
        name="web_search",
        description="Search the web (needs a Brave API key); returns title/url/snippet results.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        handler=web_search,
    ))
    if settings.code_exec_enabled:
        reg.register(Tool(
            name="run_python",
            description="Execute a short Python snippet and return stdout/stderr (host, not sandboxed).",
            parameters={"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
            handler=run_python,
        ))
    return reg

"""`sensei wrap <tool>` — run a coding agent with its traffic routed through Sensei.

The gateway already speaks both the OpenAI and Anthropic wire formats, so
routing a tool through it is only ever a matter of setting the right base-URL
environment variable. Doing that by hand means knowing which of six variable
names a given tool reads; this table knows for you.

Nothing is written to your shell profile — the variables live for exactly as
long as the wrapped process does.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from sensei.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    """A coding agent Sensei knows how to route."""

    command: str
    # Env vars set to the OpenAI-compatible endpoint (`<base>/v1`).
    openai_vars: tuple[str, ...] = ()
    # Env vars set to the Anthropic-compatible endpoint (`<base>`).
    anthropic_vars: tuple[str, ...] = ()
    note: str = ""


TOOLS: dict[str, Tool] = {
    "claude": Tool(
        command="claude",
        anthropic_vars=("ANTHROPIC_BASE_URL",),
        note="Claude Code. Keeps using your own Anthropic key — Sensei only compresses.",
    ),
    "codex": Tool(
        command="codex",
        openai_vars=("OPENAI_BASE_URL",),
        note="OpenAI Codex CLI.",
    ),
    "aider": Tool(
        command="aider",
        openai_vars=("OPENAI_API_BASE", "OPENAI_BASE_URL"),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
        note="Aider reads OPENAI_API_BASE rather than OPENAI_BASE_URL.",
    ),
    "cursor-agent": Tool(
        command="cursor-agent",
        openai_vars=("OPENAI_BASE_URL",),
        note="Cursor's CLI agent. The Cursor GUI is configured in its own settings.",
    ),
    "opencode": Tool(
        command="opencode",
        openai_vars=("OPENAI_BASE_URL",),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
    ),
    "goose": Tool(
        command="goose",
        openai_vars=("OPENAI_BASE_URL", "OPENAI_HOST"),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
    ),
    "cline": Tool(
        command="cline",
        openai_vars=("OPENAI_BASE_URL",),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
    ),
    "continue": Tool(
        command="continue",
        openai_vars=("OPENAI_BASE_URL",),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
    ),
    "crush": Tool(
        command="crush",
        openai_vars=("OPENAI_BASE_URL",),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
    ),
}


def gateway_base(host: str | None = None, port: int | None = None) -> str:
    """The URL a wrapped tool should point at.

    0.0.0.0 is a bind address, not a destination — a client told to connect
    there will fail on Windows and macOS, so it maps to localhost.
    """
    h = host or settings.host
    if h in ("0.0.0.0", "::", ""):  # noqa: S104 — comparison, not a bind
        h = "localhost"
    return f"http://{h}:{port or settings.port}"


def routing_env(tool: Tool, base: str | None = None) -> dict[str, str]:
    """The environment overlay that routes this tool through Sensei."""
    base = base or gateway_base()
    env: dict[str, str] = {}
    for var in tool.openai_vars:
        env[var] = f"{base}/v1"
    for var in tool.anthropic_vars:
        env[var] = base
    return env


def run(tool_name: str, argv: list[str]) -> int:
    tool = TOOLS.get(tool_name)
    if tool is None:
        known = ", ".join(sorted(TOOLS))
        print(f"Unknown tool: {tool_name}", file=sys.stderr)
        print(f"Known tools: {known}", file=sys.stderr)
        return 2

    if shutil.which(tool.command) is None:
        print(f"'{tool.command}' is not on your PATH.", file=sys.stderr)
        print(
            f"Install it first, then run: sensei wrap {tool_name}",
            file=sys.stderr,
        )
        return 127

    overlay = routing_env(tool)
    env = {**os.environ, **overlay}

    print(f"Routing {tool.command} through Sensei at {gateway_base()}")
    for k, v in sorted(overlay.items()):
        print(f"  {k}={v}")
    if tool.note:
        print(f"  {tool.note}")
    print()

    try:
        return subprocess.call([tool.command, *argv], env=env)  # noqa: S603
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"Failed to launch {tool.command}: {exc}", file=sys.stderr)
        return 1

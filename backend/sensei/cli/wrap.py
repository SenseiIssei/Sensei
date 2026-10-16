"""`sensei wrap <tool>` — run a coding agent with its traffic routed through Sensei.

The gateway already speaks both the OpenAI and Anthropic wire formats, so
routing a tool through it is almost always a matter of setting the right
base-URL environment variable. Doing that by hand means knowing which of a dozen
variable names a given tool reads — and, for the few that ignore the
environment, which command-line flag to pass instead. This table knows.

Nothing is written to your shell profile — the variables live for exactly as
long as the wrapped process does.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

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
    # Env vars set to the bare origin, for tools that append the API path
    # themselves (Goose: OPENAI_HOST + OPENAI_BASE_PATH = v1/chat/completions).
    host_vars: tuple[str, ...] = ()
    # Fixed values, set only when the user has not set them already.
    defaults: dict[str, str] = field(default_factory=dict)
    # Arguments placed before the user's own, for tools that ignore the
    # environment: Codex reads `openai_base_url` from config or `-c` only.
    args: Callable[[str], list[str]] | None = None
    note: str = ""


TOOLS: dict[str, Tool] = {
    "claude": Tool(
        command="claude",
        anthropic_vars=("ANTHROPIC_BASE_URL",),
        note="Claude Code. Keeps your own sign-in. Remote Control is off while routed; "
        "`sensei connect` compresses through a hook instead and keeps it.",
    ),
    "codex": Tool(
        command="codex",
        # OPENAI_BASE_URL is not read by Codex; the config key is.
        args=lambda base: ["-c", f'openai_base_url="{base}/v1"'],
        note="Codex reads its base URL from config, so it is passed as -c openai_base_url. "
        "API-key sign-in only until the gateway forwards ChatGPT sign-ins.",
    ),
    "aider": Tool(
        command="aider",
        openai_vars=("OPENAI_API_BASE", "OPENAI_BASE_URL"),
        anthropic_vars=("ANTHROPIC_BASE_URL", "ANTHROPIC_API_BASE"),
        note="Aider reads OPENAI_API_BASE rather than OPENAI_BASE_URL.",
    ),
    "copilot": Tool(
        command="copilot",
        openai_vars=("COPILOT_PROVIDER_BASE_URL",),
        defaults={"COPILOT_PROVIDER_TYPE": "openai"},
        note="GitHub Copilot CLI, bring-your-own-key mode. Needs COPILOT_MODEL (and your "
        "provider key in COPILOT_PROVIDER_API_KEY unless Sensei has one).",
    ),
    "opencode": Tool(
        command="opencode",
        openai_vars=("OPENAI_BASE_URL",),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
    ),
    "goose": Tool(
        command="goose",
        # OPENAI_HOST is a host: Goose appends OPENAI_BASE_PATH (v1/chat/
        # completions) itself, so `<base>/v1` here meant /v1/v1/chat/completions.
        host_vars=("OPENAI_HOST", "ANTHROPIC_HOST"),
    ),
    "qwen": Tool(
        command="qwen",
        openai_vars=("OPENAI_BASE_URL",),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
        note="Qwen Code, with an OpenAI- or Anthropic-compatible API key.",
    ),
    "openhands": Tool(
        command="openhands",
        openai_vars=("LLM_BASE_URL",),
        note="OpenHands CLI (LiteLLM): use an openai/… model name.",
    ),
    "cline": Tool(
        command="cline",
        openai_vars=("OPENAI_BASE_URL",),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
    ),
    "continue": Tool(
        command="cn",
        openai_vars=("OPENAI_BASE_URL",),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
        note="Continue's CLI (`cn`).",
    ),
    "crush": Tool(
        command="crush",
        openai_vars=("OPENAI_BASE_URL",),
        anthropic_vars=("ANTHROPIC_BASE_URL",),
    ),
}

# Asked for often enough to deserve an answer rather than "unknown tool".
NOT_ROUTABLE = {
    "cursor-agent": "cursor-agent has no base-URL setting: its model calls are made from "
    "Cursor's servers. `sensei connect` gives it Sensei's MCP tools instead.",
    "cursor": "Cursor's model calls are made from Cursor's servers and cannot reach a local "
    "gateway. `sensei connect` gives it Sensei's MCP tools instead.",
    "gemini": "Gemini CLI speaks Google's wire format. `sensei connect` adds a compression "
    "hook and the MCP tools instead.",
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


def routing_env(
    tool: Tool, base: str | None = None, environ: dict[str, str] | None = None
) -> dict[str, str]:
    """The environment overlay that routes this tool through Sensei."""
    base = base or gateway_base()
    current = os.environ if environ is None else environ
    env: dict[str, str] = {}
    for var in tool.openai_vars:
        env[var] = f"{base}/v1"
    for var in tool.anthropic_vars:
        env[var] = base
    for var in tool.host_vars:
        env[var] = base
    for var, value in tool.defaults.items():
        if not current.get(var):
            env[var] = value
    if tool.command == "copilot" and current.get("COPILOT_PROVIDER_TYPE") == "anthropic":
        env["COPILOT_PROVIDER_BASE_URL"] = base
    return env


def routing_args(tool: Tool, base: str | None = None) -> list[str]:
    return tool.args(base or gateway_base()) if tool.args else []


def run(tool_name: str, argv: list[str]) -> int:
    if tool_name in NOT_ROUTABLE:
        print(NOT_ROUTABLE[tool_name], file=sys.stderr)
        return 2
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
    extra = routing_args(tool)
    env = {**os.environ, **overlay}

    print(f"Routing {tool.command} through Sensei at {gateway_base()}")
    for k, v in sorted(overlay.items()):
        print(f"  {k}={v}")
    if extra:
        print(f"  {tool.command} {' '.join(extra)}")
    if tool.note:
        print(f"  {tool.note}")
    print()

    try:
        return subprocess.call([tool.command, *extra, *argv], env=env)  # noqa: S603
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"Failed to launch {tool.command}: {exc}", file=sys.stderr)
        return 1

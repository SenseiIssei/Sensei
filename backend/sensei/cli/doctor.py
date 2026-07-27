"""`sensei doctor` — tell the user exactly why Sensei isn't working.

Every check returns a status and, when something is wrong, the specific command
that fixes it. "Something went wrong" is not an acceptable output here.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from sensei import __version__
from sensei.config import ENV_PATH, settings

OK = "ok"
WARN = "warn"
FAIL = "fail"

_ICON = {OK: "+", WARN: "!", FAIL: "x"}
_COLOR = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}
_RESET = "\033[0m"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _port_free(host: str, port: int) -> bool:
    target = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host  # noqa: S104
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((target, port)) != 0


def _configured_providers() -> list[str]:
    found = []
    for name in (
        "openrouter",
        "zai",
        "openai",
        "anthropic",
        "google",
        "groq",
        "mistral",
        "together",
        "deepseek",
        "cohere",
        "fireworks",
        "perplexity",
        "huggingface",
    ):
        if getattr(settings, f"{name}_api_key", ""):
            found.append(name)
    return found


def _web_ui_built() -> bool:
    return (Path(__file__).resolve().parents[3] / "frontend" / "dist").exists()


async def _ollama_running() -> bool:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{settings.ollama_host}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def collect() -> list[Check]:
    checks: list[Check] = []

    # ── Runtime ────────────────────────────────────────────────
    py = sys.version_info
    checks.append(
        Check(
            "Python",
            OK if py >= (3, 11) else FAIL,
            f"{py.major}.{py.minor}.{py.micro} on {platform.system()} {platform.machine()}",
            "" if py >= (3, 11) else "Sensei needs Python 3.11 or newer.",
        )
    )
    checks.append(Check("Sensei", OK, f"v{__version__}"))

    # ── Configuration ──────────────────────────────────────────
    if ENV_PATH.exists():
        checks.append(Check("Config file", OK, str(ENV_PATH)))
    else:
        checks.append(
            Check(
                "Config file",
                WARN,
                f"no .env at {ENV_PATH}",
                "That's fine — defaults apply. Run 'sensei up' and use the setup wizard, "
                "or copy .env.example to .env.",
            )
        )

    # ── A model to talk to ─────────────────────────────────────
    ollama_up = await _ollama_running()
    providers = _configured_providers()
    if ollama_up:
        checks.append(Check("Ollama", OK, f"running at {settings.ollama_host}"))
    elif shutil.which("ollama"):
        checks.append(
            Check(
                "Ollama",
                WARN,
                "installed but not responding",
                "Start it with: ollama serve",
            )
        )
    else:
        checks.append(
            Check(
                "Ollama",
                WARN,
                "not installed",
                "Optional. For free local inference: https://ollama.com",
            )
        )

    if providers:
        checks.append(Check("API keys", OK, f"configured: {', '.join(providers)}"))
    else:
        checks.append(Check("API keys", WARN, "none configured"))

    if ollama_up or providers:
        checks.append(Check("Model access", OK, "at least one way to reach a model"))
    else:
        checks.append(
            Check(
                "Model access",
                FAIL,
                "no local model and no API key — Sensei cannot answer anything",
                "Either install Ollama (free, local) or run 'sensei up' and paste an "
                "API key into the setup wizard.",
            )
        )

    # ── Network ────────────────────────────────────────────────
    free = _port_free(settings.host, settings.port)
    checks.append(
        Check(
            "Port",
            OK if free else WARN,
            f"{settings.host}:{settings.port} {'is free' if free else 'is already in use'}",
            ""
            if free
            else f"Sensei may already be running, or pick another: sensei up --port {settings.port + 1}",
        )
    )

    exposed = settings.host not in ("127.0.0.1", "localhost", "::1")
    checks.append(
        Check(
            "Bind address",
            WARN if exposed else OK,
            settings.host,
            "Sensei is reachable from your network. Put it behind a reverse proxy with "
            "TLS and set SENSEI_AUTH_ENABLED=true — see deploy/README.md."
            if exposed
            else "",
        )
    )

    # ── Security posture ───────────────────────────────────────
    if exposed and not settings.auth_enabled:
        checks.append(
            Check(
                "Auth",
                FAIL,
                "disabled while bound to a non-loopback address",
                "Set SENSEI_AUTH_ENABLED=true and SENSEI_AUTH_TOKEN before exposing Sensei.",
            )
        )
    else:
        checks.append(
            Check("Auth", OK, "enabled" if settings.auth_enabled else "disabled (loopback only)")
        )

    if settings.code_exec_enabled:
        checks.append(
            Check(
                "Code execution",
                WARN,
                "enabled — run_python executes on this host, not in a container",
                "Only leave this on for machines you control.",
            )
        )

    # ── Optional accelerator ───────────────────────────────────
    try:
        import sensei_core  # noqa: F401

        checks.append(Check("Rust accelerator", OK, "installed — CSV hot path ~2x faster"))
    except ImportError:
        checks.append(
            Check(
                "Rust accelerator",
                OK,
                "not installed (optional)",
                "Compression works without it. To install: pip install sensei-core",
            )
        )

    # ── Bundled web UI ─────────────────────────────────────────
    if await asyncio.to_thread(_web_ui_built):
        checks.append(Check("Web UI", OK, "built"))
    else:
        checks.append(
            Check(
                "Web UI",
                WARN,
                "not built — only the API and /docs are available",
                "Build it with: cd frontend && npm ci && npm run build",
            )
        )

    # ── Disk ───────────────────────────────────────────────────
    try:
        usage = shutil.disk_usage(os.getcwd())
        free_gb = usage.free / (1024**3)
        checks.append(
            Check(
                "Disk space",
                OK if free_gb > 5 else WARN,
                f"{free_gb:.1f} GB free",
                "" if free_gb > 5 else "Local models need tens of GB. Free some space first.",
            )
        )
    except OSError:
        pass

    return checks


def render(checks: list[Check], color: bool = True) -> str:
    lines = []
    for c in checks:
        icon = _ICON[c.status]
        if color:
            icon = f"{_COLOR[c.status]}{icon}{_RESET}"
        lines.append(f"  [{icon}] {c.name:<18} {c.detail}")
        if c.fix:
            lines.append(f"        -> {c.fix}")
    return "\n".join(lines)


def run() -> int:
    checks = asyncio.run(collect())
    print("\nSensei doctor\n")
    print(render(checks))

    failed = [c for c in checks if c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]
    print()
    if failed:
        print(f"{len(failed)} problem(s) will stop Sensei from working. See the arrows above.")
        return 1
    if warned:
        print(f"Everything essential works. {len(warned)} thing(s) worth a look.")
        return 0
    print("Everything looks good.")
    return 0

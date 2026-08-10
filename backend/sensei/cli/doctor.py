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
    """Is there a web UI to serve?

    This looked only for `frontend/dist` at the repo root, which is one of the
    three places a build can live. A PyInstaller binary carries the UI inside
    the bundle and a wheel carries it as package data, so the downloadable
    installer reported "the web UI isn't built — cd frontend && npm ci" while
    it was serving that UI perfectly well on the next port over.

    `cli.serve` already knows how to find it in all three cases; asking it is
    both correct and impossible to drift from what actually gets mounted.
    """
    from sensei.cli.serve import _frontend_dist

    return _frontend_dist() is not None


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


# ── End-to-end verification ─────────────────────────────────────────────────
#
# Everything above is a static check: a file exists, a port is free, a key is
# set. None of it proves a request actually reaches the gateway and comes back
# compressed, which is the only thing the user cares about. `setup-tools` in
# particular writes configuration files and then nobody confirms they worked —
# the most common way for that to be wrong is the port changing afterwards,
# which no static check can see.

# Deliberately an array of near-identical records: SmartCrusher rewrites it to
# a header plus rows, so a gateway that is compressing at all cannot report
# zero. A single short sentence would legitimately compress to nothing and make
# a working setup look broken.
_PROBE = [
    {"id": i, "name": f"item {i}", "state": "ready", "url": f"https://example.com/i/{i}"}
    for i in range(30)
]


async def verify() -> list[Check]:
    """Send one real request through the gateway and report what came back."""
    import httpx

    from sensei.cli.wrap import gateway_base

    base = gateway_base()
    checks: list[Check] = []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{base}/v1/chat/completions",
                headers={"X-Sensei-Client": "sensei doctor"},
                json={
                    "model": "probe",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": str(_PROBE)}],
                },
            )
    except httpx.HTTPError as exc:
        return [
            Check(
                "Gateway",
                FAIL,
                f"nothing answering at {base} ({exc.__class__.__name__})",
                "Start it first: sensei up",
            )
        ]

    checks.append(Check("Gateway", OK, f"reachable at {base}"))

    # The static section reports the port as "already in use" and suggests
    # picking another one, which is unhelpful when the thing using it is the
    # Sensei the user just started. Once the gateway has answered with our own
    # headers, we know exactly who is on that port.
    if resp.headers.get("X-Sensei-Tokens-Saved") is not None:
        checks.append(Check("Port", OK, f"{settings.host}:{settings.port} is this server"))

    # The savings headers are attached before the request is forwarded, so they
    # are present even when there is no upstream configured. That is what makes
    # this check useful on a machine that has not finished setup: it separates
    # "compression is not working" from "you have not added a key yet".
    saved = resp.headers.get("X-Sensei-Tokens-Saved")
    enabled = resp.headers.get("X-Sensei-Compression-Enabled")

    if saved is None:
        checks.append(
            Check(
                "Compression",
                FAIL,
                "the gateway answered but reported no savings headers",
                "This is a bug — please open an issue with the output of 'sensei doctor -v'.",
            )
        )
    elif enabled == "false":
        checks.append(
            Check(
                "Compression",
                WARN,
                "turned off (SENSEI_COMPRESSION_ENABLED=false)",
                "Traffic is proxied untouched. Set it to true to actually save anything.",
            )
        )
    elif int(saved or 0) <= 0:
        checks.append(
            Check(
                "Compression",
                FAIL,
                "ran, but saved nothing on a payload that should compress ~70%",
                "Something is wrong with the compression pipeline, not your setup.",
            )
        )
    else:
        ratio = resp.headers.get("X-Sensei-Compression-Ratio", "?")
        checks.append(
            Check("Compression", OK, f"{saved} tokens saved on the probe (ratio {ratio})")
        )

    # Upstream is reported separately: a 502 here means the compression half
    # works and only the provider is missing, which is a different problem with
    # a different fix.
    if resp.status_code == 200:
        checks.append(Check("Upstream", OK, "the provider answered"))
    else:
        body = resp.text[:120].replace("\n", " ")
        checks.append(
            Check(
                "Upstream",
                WARN,
                f"HTTP {resp.status_code} — compression works, the model call did not",
                f"{body}  ->  run 'sensei up' and add a key, or install Ollama.",
            )
        )

    checks.extend(_wired_tool_checks(base))
    return checks


def _wired_tool_checks(base: str) -> list[Check]:
    """Do the tools `setup-tools` configured still point at this server?

    Changing SENSEI_PORT after running `setup-tools` leaves every tool pointing
    at a port with nothing on it, and the tool's own error message for that is
    usually "connection refused" with no mention of Sensei.
    """
    from sensei import integrations

    checks: list[Check] = []
    manifest = integrations._read_manifest()
    entries = manifest.get("entries", [])
    command = integrations.endpoints().mcp_command

    if not entries:
        checks.append(
            Check(
                "Wired tools",
                WARN,
                "none — no tool on this machine is routed through Sensei",
                "Connect the ones you have: sensei setup-tools",
            )
        )
        return checks

    stale: list[str] = []
    for entry in entries:
        path = Path(str(entry.get("path", "")))
        if not path.exists():
            stale.append(f"{entry.get('tool_id')} (config gone)")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Two kinds of wiring, and checking for only one of them was a bug that
        # reported every healthy MCP-only tool as broken:
        #
        #   base URL   the tool talks HTTP to the gateway (Claude Code, Codex,
        #              Continue, Aider) — the file names the address
        #   MCP        the tool spawns `sensei mcp` as a subprocess (Claude
        #              Desktop, Cursor, Windsurf, Cline, Roo, Kilo, Zed) — the
        #              file names the *command*, and there is no URL in it at
        #              all, correctly
        #
        # Both still catch real staleness: change the port and the URL-based
        # tools no longer match; move the executable and the MCP ones don't.
        wired = base in text or f"{base}/v1" in text or command in text
        if not wired:
            # Distinguish the two reasons, because the fixes differ. A file
            # that names *a* Sensei, just not this one, means two installations
            # exist and doctor is being run from the wrong one — telling that
            # user "the server moved, re-run setup-tools" would have them
            # rewire away from a working setup.
            other = "sensei" in text.lower()
            stale.append(f"{entry.get('tool_id')}{' (a different Sensei)' if other else ''}")

    if stale:
        elsewhere = any("different Sensei" in s for s in stale)
        checks.append(
            Check(
                "Wired tools",
                # Pointing at another installation is not broken, it is just
                # not this one — a warning, not a failure.
                WARN if elsewhere else FAIL,
                f"{len(entries)} configured, but these do not point here: {', '.join(stale)}",
                "Those tools are wired to a different Sensei on this machine. Run "
                "`doctor --verify` from that one, or re-run `setup-tools` here to "
                "take them over."
                if elsewhere
                else f"The server moved to {base}. Re-run: sensei setup-tools",
            )
        )
    else:
        names = ", ".join(str(e.get("tool_id")) for e in entries)
        checks.append(Check("Wired tools", OK, f"{len(entries)} pointing here: {names}"))
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


def run(verify_routing: bool = False) -> int:
    checks = asyncio.run(collect())
    live: list[Check] = []

    if verify_routing:
        live = asyncio.run(verify())
        # The static pass can only see that *something* holds the port; the
        # live pass knows it is us. Drop the guess rather than printing both,
        # which would leave a warning in the summary count for a healthy setup.
        if any(c.name == "Port" and c.status == OK for c in live):
            checks = [c for c in checks if c.name != "Port"]

    print("\nSensei doctor\n")
    print(render(checks))
    if live:
        print("\nEnd-to-end\n")
        print(render(live))
        checks = checks + live

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

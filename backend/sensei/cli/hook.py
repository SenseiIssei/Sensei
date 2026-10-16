"""`sensei hook <name>` — command hooks that a tool runs, not a person.

Only one exists so far, because only one hook has to be a command: Claude Code
does not run HTTP hooks for SessionStart.

    sensei hook claude-session-start

Installed only when Claude Code's base-URL routing is opted into. With
``ANTHROPIC_BASE_URL`` pointing at Sensei, a Sensei that is not running means
every request of the session fails with "connection refused" and nothing says
why. At session start this hook checks, tries to start Sensei, and if that does
not work removes the base URL so the next session talks to Anthropic directly.
The background watcher puts it back the next time Sensei starts.

A hook must never be the thing that breaks the tool: whatever happens in here,
the exit code is 0 and stdout is either empty or one JSON object.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
import urllib.request
from typing import Any


def _settings_path() -> Any:
    from sensei import integrations

    return next(i for i in integrations.REGISTRY if i.id == "claude-code").path()


def _routed_base() -> str | None:
    """The Sensei base URL Claude Code is configured with, if it is one.

    The URL in the file, not the one this process would compute: a Sensei
    started with `--port 7100` wrote 7100 there, while this process — spawned
    by Claude Code with no such flag — reads the default port from settings.
    Probing that would find nothing and start a second Sensei beside the first.
    """
    from sensei import integrations

    doc = integrations._load_json(_settings_path())
    if not isinstance(doc, dict) or not integrations.claude_code_routed(doc):
        return None
    return str(doc["env"]["ANTHROPIC_BASE_URL"]).rstrip("/")


def _alive(base: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=timeout) as resp:  # noqa: S310
            return resp.status == 200
    except Exception:
        return False


def _start_detached(port: int | None) -> bool:
    """Launch the tray (or a headless server) without tying it to this process."""
    from sensei.cli import system

    argv = system.launch_command(headless=not system._tray_available())
    if port is not None:
        argv = [*argv, "--port", str(port)]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(argv, **kwargs)  # noqa: S603
    except OSError:
        return False
    return True


def _clear_base_url() -> bool:
    """Remove a Sensei base URL from Claude Code's settings. True if removed."""
    from sensei import integrations

    path = _settings_path()
    doc = integrations._load_json(path)
    if not isinstance(doc, dict) or not integrations.claude_code_routed(doc):
        return False
    integrations._deep_unset(doc, ("env", "ANTHROPIC_BASE_URL"), prune=True)
    integrations._atomic_write(path, integrations._dump_json(doc))
    return True


def claude_session_start(*, wait_seconds: float = 8.0) -> dict[str, Any]:
    """Make sure the base URL Claude Code was given leads somewhere."""
    from sensei import integrations

    base = _routed_base()
    if base is None or _alive(base):
        return {}
    if _start_detached(integrations._url_port(base)):
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            time.sleep(0.4)
            if _alive(base, timeout=0.5):
                return {"systemMessage": "Sensei was not running — started it."}
    if _clear_base_url():
        return {
            "systemMessage": (
                f"Sensei is not answering at {base}, so Claude Code's base URL led "
                "nowhere. Removed it from Claude Code's settings: restart this session "
                "to talk to Anthropic directly. It comes back when Sensei starts."
            )
        }
    return {}


def run(name: str) -> int:
    with contextlib.suppress(Exception):
        sys.stdin.read()  # the hook payload; not needed, but drain the pipe
    answer: dict[str, Any] = {}
    try:
        if name == "claude-session-start":
            answer = claude_session_start()
        else:
            print(f"Unknown hook: {name}", file=sys.stderr)
    except Exception as exc:  # a hook must not fail the tool
        print(f"sensei hook {name}: {exc}", file=sys.stderr)
    if answer:
        print(json.dumps(answer))
    return 0

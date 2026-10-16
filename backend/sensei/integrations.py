"""Wiring Sensei into the tools that keep their configuration on disk.

`sensei wrap <tool>` covers the tools you launch from a terminal: it sets a base
URL for exactly one process and forgets it again. That does not help a tool you
start by clicking an icon — VS Code, Cursor, Devin — or a CLI that reads a
config file rather than the environment. Those need a file edited, and editing
them by hand means knowing which of a dozen formats a given tool uses and where
it hides the file on three operating systems.

This module knows. It detects what is installed, writes the smallest change that
connects the tool to Sensei, and records precisely what it did so that
``sensei setup-tools --undo`` can put it back.

What "connected" means depends on what the tool allows, and the registry says so
per tool rather than pretending every tool can do everything:

* **hook** — the tool runs a hook after every tool call and lets the hook
  replace the output. Sensei compresses the output before the model sees it.
  This is how Claude Code is connected by default: it keeps its own sign-in,
  Remote Control and the desktop app's Code tab all keep working, and if Sensei
  is not running the hook fails open and the tool's output goes through as is.
* **route** — the tool's model traffic is pointed at the gateway. Strongest, but
  it puts Sensei in the request path: some tools disable features behind a
  custom base URL (Claude Code turns Remote Control off), so for those it is an
  explicit opt-in.
* **mcp** — Sensei's MCP tools (``sensei_compress``, ``sensei_retrieve``, and the
  proxy for other MCP servers) are registered. The only option for tools whose
  model traffic leaves from the vendor's servers.

Three rules, because a program that edits other programs' config files has to be
more careful than one that doesn't:

1. **Never write blind.** Every file is backed up first, under
   ``~/.sensei/backups/<timestamp>/``, and the manifest records where.
2. **Never clobber a later edit.** Undo restores a backup only if the file still
   hashes to what Sensei wrote. If you edited it afterwards, undo removes
   Sensei's own keys and leaves the rest alone.
3. **Never guess at a format.** JSON files are parsed, modified and re-serialised;
   a JSON file with comments is reported as a manual step rather than rewritten
   without them. TOML is edited table by table, so it survives an app that
   rewrites the file in its own order. YAML gets a marker-delimited block, and
   only when the keys involved are not already set.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sensei.config import settings

# ── Where Sensei keeps its own bookkeeping ──────────────────────────────────

SENSEI_HOME = Path.home() / ".sensei"
MANIFEST_PATH = SENSEI_HOME / "integrations.json"
BACKUP_ROOT = SENSEI_HOME / "backups"

# Marker lines that delimit an appended block in a file we cannot parse. Undo
# deletes exactly what lies between them, so they have to be stable forever.
BLOCK_BEGIN = "# >>> sensei >>>"
BLOCK_END = "# <<< sensei <<<"

# The paths of the hook endpoints (routers/hooks.py). Matched by substring when
# recognising Sensei's own hook entries, so a port change still finds them.
CLAUDE_HOOK_PATH = "/hooks/claude/post-tool-use"
COPILOT_HOOK_PATH = "/hooks/copilot/post-tool-use"
GENERIC_HOOK_PATH = "/hooks/compress"

# The tools whose output the Claude Code hook may compress. Read, Edit, Write
# and friends are deliberately absent: what Read returns is what Edit's
# `old_string` is matched against, and the model must see it byte for byte.
CLAUDE_HOOK_MATCHER = "Bash|Grep|Glob|WebFetch|WebSearch|mcp__.*"


# ── The endpoints a tool is pointed at ──────────────────────────────────────


@dataclass(frozen=True)
class Endpoints:
    """The ways a tool can talk to Sensei."""

    anthropic: str  # http://127.0.0.1:7000
    openai: str  # http://127.0.0.1:7000/v1
    mcp_command: str  # "sensei"
    mcp_args: tuple[str, ...] = ("mcp",)
    # Whether `sensei mcp` can actually start. False means the optional `mcp`
    # extra is missing, and writing a server entry anyway produces exactly one
    # symptom in every editor that reads it: "Server disconnected", with no
    # hint that a Python package is the reason.
    mcp_ready: bool = True
    # Opt-in features, as "<tool-id>:<feature>" (e.g. "claude-code:route").
    # Carried here so every apply function sees them without a second argument.
    opt_in: frozenset[str] = frozenset()
    # Where hooks call in. Always loopback: the hook endpoints answer only
    # loopback callers, and Claude Code refuses HTTP hooks to private (LAN)
    # addresses outright. A Sensei bound to a LAN address only cannot serve
    # hooks; docs/integrations/claude-code.md says to bind 0.0.0.0 or loopback.
    hook_base: str = ""

    def hook_url(self, path: str) -> str:
        return f"{self.hook_base or self.anthropic}{path}"

    def wants(self, tool_id: str, feature: str) -> bool:
        return f"{tool_id}:{feature}" in self.opt_in

    def refuses(self, tool_id: str, feature: str) -> bool:
        """Explicitly switched off — as opposed to never switched on."""
        return f"{tool_id}:!{feature}" in self.opt_in


def _console_binary(executable: str) -> str:
    """The binary an MCP client should spawn, given the one we are running as.

    MCP speaks JSON-RPC over stdin and stdout, and `senseiw.exe` is built
    without a console precisely so it has neither. When the tray writes a config
    it writes `sys.executable`, which is itself — so every tool got pointed at
    the one binary whose whole purpose is having nowhere to write.

    Returns the original string untouched unless a sibling actually exists —
    both so an unexpected name is not turned into a path to nothing, and so the
    path is not silently rewritten by a round trip through Path, which
    normalises separators.
    """
    path = Path(executable)
    stem = path.stem
    if stem.lower().endswith("w"):
        console = path.with_name(stem[:-1] + path.suffix)
        if console.exists():
            return str(console)
    return executable


def endpoints(host: str | None = None, port: int | None = None) -> Endpoints:
    """Build the endpoint set for the running configuration.

    0.0.0.0 is a bind address, not a destination. A tool told to connect there
    fails on Windows and macOS, so it maps to loopback — same reasoning as
    ``cli.wrap.gateway_base``.
    """
    h = host or settings.host
    if h in ("0.0.0.0", "::", ""):  # noqa: S104 — comparison, not a bind
        h = "127.0.0.1"
    base = f"http://{h}:{port or settings.port}"
    command: str
    args: tuple[str, ...]
    # How an MCP client should spawn Sensei. Three cases, and getting the third
    # wrong writes a broken server entry into someone's editor config:
    #
    #   frozen binary  the executable *is* sensei — `-m sensei.cli` is not a
    #                  thing it can do, and PyInstaller's sys.executable points
    #                  at the bundle, so the module form produces
    #                  `sensei.exe -m sensei.cli mcp`, which fails at startup
    #   own script     the console script installed next to this interpreter,
    #                  by absolute path
    #   otherwise      this interpreter plus the module, which always resolves
    #
    # Never the bare name `sensei`. Whatever answers to it first on PATH is
    # what every editor will spawn, and on the machine this was tested on that
    # was another program's `sensei.cmd` — Copilot CLI, opencode and Kilo all
    # reported the server "exited before the handshake" until the entry named
    # this installation's own file.
    if getattr(sys, "frozen", False):
        command, args = _console_binary(sys.executable), ("mcp",)
    elif (script := _own_script()) is not None:
        command, args = str(script), ("mcp",)
    else:
        command, args = sys.executable, ("-m", "sensei.cli", "mcp")
    return Endpoints(
        anthropic=base,
        openai=f"{base}/v1",
        mcp_command=command,
        mcp_args=args,
        mcp_ready=mcp_available(),
        opt_in=_opt_ins(),
        hook_base=f"http://127.0.0.1:{port or settings.port}",
    )


def _own_script() -> Path | None:
    """The `sensei` console script that belongs to this interpreter, if any."""
    import sysconfig

    name = "sensei.exe" if sys.platform == "win32" else "sensei"
    candidates = [Path(sys.executable).with_name(name)]
    with contextlib.suppress(KeyError, OSError):
        candidates.append(Path(sysconfig.get_path("scripts")) / name)
    return next((c for c in candidates if c.is_file()), None)


def mcp_available() -> bool:
    """Can this build actually serve MCP?

    `sensei mcp` needs the optional `mcp` extra. A PyInstaller binary built
    without it starts, reports its version, wires up base URLs — and then dies
    with ModuleNotFoundError the moment an editor spawns it. Checked here so a
    server entry is never written for a command that cannot run.
    """
    return importlib.util.find_spec("mcp") is not None


def _sensei_command(ep: Endpoints, *args: str) -> list[str]:
    """`sensei <args>` in the form this installation can be spawned as."""
    if ep.mcp_args and ep.mcp_args[-1] == "mcp":
        return [ep.mcp_command, *ep.mcp_args[:-1], *args]
    return [ep.mcp_command, *args]  # pragma: no cover — every builder ends in "mcp"


def _shell_command(argv: list[str]) -> str:
    """One command line for a hook runner that takes a string.

    Forward slashes, because Claude Code runs command hooks through Git Bash on
    Windows, where a backslash is an escape character; double quotes around
    anything with a space, because that is the one quoting rule bash, cmd and
    PowerShell agree on.
    """
    parts = []
    for raw in argv:
        arg = raw.replace("\\", "/")
        parts.append(f'"{arg}"' if (" " in arg or not arg) else arg)
    return " ".join(parts)


# ── Result of touching one tool ─────────────────────────────────────────────


@dataclass
class Outcome:
    """What happened to one integration on one run."""

    tool_id: str
    name: str
    status: str  # applied | unchanged | not-found | manual | failed
    detail: str = ""
    path: Path | None = None
    manual_snippet: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("applied", "unchanged", "not-found")


# ── Small filesystem helpers ────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    """Write via a sibling temp file and replace.

    A half-written config file is worse than no change at all: the tool that
    reads it will not start, and the user has no idea why.

    Two properties of the file survive the replace. Its *mode*: ~/.claude.json
    holds OAuth tokens and is 0600, and a temp file created with the default
    umask turned it world-readable. And its *identity*: a dotfile that is a
    symlink into a dotfiles repository is written through, not replaced by a
    plain file. The temp file is owner-only from its first byte.
    """
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o600
    with contextlib.suppress(OSError):
        mode = stat.S_IMODE(target.stat().st_mode)
    tmp = target.with_name(target.name + ".sensei-tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    with contextlib.suppress(OSError):
        os.chmod(tmp, mode)
    os.replace(tmp, target)


def _backup(path: Path, stamp: str) -> Path | None:
    """Copy a file into the run's backup directory. Returns where it went."""
    if not path.exists():
        return None
    dest_dir = BACKUP_ROOT / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Flatten the absolute path into a filename so two tools with the same
    # basename (several of them use `settings.json`) cannot overwrite each other.
    flat = re.sub(r"[^A-Za-z0-9._-]", "_", str(path))
    dest = dest_dir / flat
    shutil.copy2(path, dest)
    return dest


def _load_json(path: Path, root: type = dict) -> Any:
    """Parse a JSON config, or return None if it is not strict JSON of that shape.

    Several editors accept comments in their JSON. Sensei will not rewrite a
    file it cannot round-trip, because doing so silently deletes the user's
    comments — so a parse failure means "hands off", not "start fresh".
    """
    if not path.exists():
        return root()
    raw = path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        return root()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, root) else None


def _dump_json(doc: Any) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _deep_set(doc: dict[str, Any], keys: tuple[str, ...], value: Any) -> bool:
    """Set a nested key. Returns True if the document actually changed."""
    cursor = doc
    for key in keys[:-1]:
        nxt = cursor.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[key] = nxt
        cursor = nxt
    if cursor.get(keys[-1]) == value:
        return False
    cursor[keys[-1]] = value
    return True


def _deep_get(doc: Any, keys: tuple[str, ...]) -> Any:
    cursor = doc
    for key in keys:
        if not isinstance(cursor, dict) or key not in cursor:
            return None
        cursor = cursor[key]
    return cursor


def _deep_unset(doc: dict[str, Any], keys: tuple[str, ...], *, prune: bool = False) -> bool:
    """Remove a nested key. With ``prune``, also drop parents it left empty."""
    trail: list[tuple[dict[str, Any], str]] = []
    cursor: Any = doc
    for key in keys[:-1]:
        if not isinstance(cursor, dict) or key not in cursor:
            return False
        trail.append((cursor, key))
        cursor = cursor[key]
    if not isinstance(cursor, dict) or keys[-1] not in cursor:
        return False
    del cursor[keys[-1]]
    if prune:
        for parent, key in reversed(trail):
            if parent[key] == {}:
                del parent[key]
            else:
                break
    return True


_LOOPBACK_URL = re.compile(r"^(https?)://(127\.0\.0\.1|localhost|\[::1\])(?::(\d+))?(/|$)")


def _url_port(value: str) -> int | None:
    match = _LOOPBACK_URL.match(value)
    if not match:
        return None
    if match.group(3):
        return int(match.group(3))
    return 443 if match.group(1) == "https" else 80


def _sensei_ports() -> set[int]:
    """The ports a Sensei on this machine has been wired at: the configured
    one, plus every one Sensei recorded writing into a tool's config."""
    ports = {int(settings.port)}
    raw = _read_manifest().get("ports", [])
    if isinstance(raw, list):
        ports |= {p for p in raw if isinstance(p, int)}
    return ports


def _points_here(value: Any) -> bool:
    """Is this URL *Sensei* on this machine?

    Used before removing a base URL: one the user set to their own local
    proxy — Ollama or LiteLLM on :11434, claude-code-router on :3456 — is
    theirs and stays. Loopback alone is not enough; the port has to be one
    Sensei itself wrote.
    """
    if not isinstance(value, str):
        return False
    port = _url_port(value)
    return port is not None and port in _sensei_ports()


# ── Platform directories ────────────────────────────────────────────────────


def _appdata() -> Path:
    """Roaming app data on Windows, Application Support on macOS, XDG elsewhere."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _localappdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def _xdg_config() -> Path:
    """Where an Electron/native app keeps config: %APPDATA% on Windows."""
    if sys.platform == "win32":
        return _appdata()
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _dot_config() -> Path:
    """`~/.config`, on every platform — including Windows.

    Node CLIs that use xdg-basedir (opencode, Kilo, Crush) resolve to
    `%USERPROFILE%\\.config` on Windows, not `%APPDATA%`. Sensei 0.2 wrote
    opencode's entry into `%APPDATA%\\opencode`, which opencode never reads.
    """
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


# VS Code and the forks that share its extension storage layout. Extensions such
# as Cline and Roo keep their MCP settings per editor, so a user running Cline
# in Cursor has it under Cursor's directory, not Code's.
_VSCODE_HOSTS = ("Code", "Code - Insiders", "VSCodium", "Cursor", "Windsurf", "devin")


def _vscode_user(host: str = "Code") -> Path:
    return _appdata() / host / "User"


def _vscode_global_storage(host: str = "Code") -> Path:
    """VS Code's per-extension storage, where Cline keeps its MCP settings."""
    return _vscode_user(host) / "globalStorage"


def _extension_settings(extension: str, filename: str) -> tuple[Callable[[], Path], ...]:
    """The same extension file under every VS Code host."""
    return tuple(
        (lambda h=host: _vscode_global_storage(h) / extension / "settings" / filename)
        for host in _VSCODE_HOSTS
    )


def _devin_config() -> Path:
    """Devin Desktop's (formerly Windsurf's) MCP config.

    The extension computes it from the home directory: `AppData/Roaming/devin`
    on Windows, and `$XDG_CONFIG_HOME/devin` or `~/.config/devin` everywhere
    else — macOS included, which Sensei 0.2 got wrong.
    """
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Roaming" / "devin" / "mcp_config.json"
    return _dot_config() / "devin" / "mcp_config.json"


def _claude_desktop_config() -> Path:
    """Claude Desktop's config, which is in a different place on all three."""
    return _appdata() / "Claude" / "claude_desktop_config.json"


def _claude_desktop_msix() -> Path:
    """The Store/MSIX build reads a virtualised copy under its package dir."""
    packages = _localappdata() / "Packages"
    with contextlib.suppress(OSError):
        for package in sorted(packages.glob("Claude_*")):
            return package / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
    return (
        packages
        / "Claude_pzs8sxrjxfjjc"
        / "LocalCache"
        / "Roaming"
        / "Claude"
        / ("claude_desktop_config.json")
    )


def _goose_dir() -> Path:
    if sys.platform == "win32":
        return _appdata() / "Block" / "goose" / "config"
    return _dot_config() / "goose"


# ── MCP entry shapes ────────────────────────────────────────────────────────


def _mcp_entry(ep: Endpoints) -> dict[str, Any]:
    return {"command": ep.mcp_command, "args": list(ep.mcp_args)}


def _mcp_entry_typed(kind: str) -> Callable[[Endpoints], dict[str, Any]]:
    def build(ep: Endpoints) -> dict[str, Any]:
        return {"type": kind, **_mcp_entry(ep)}

    return build


def _mcp_entry_copilot(ep: Endpoints) -> dict[str, Any]:
    return {"type": "local", **_mcp_entry(ep), "tools": ["*"]}


def _mcp_entry_opencode(ep: Endpoints) -> dict[str, Any]:
    # opencode validates its config and wants the command as one array.
    return {"type": "local", "command": [ep.mcp_command, *ep.mcp_args], "enabled": True}


def _mcp_apply(
    root: tuple[str, ...],
    entry: Callable[[Endpoints], dict[str, Any]] = _mcp_entry,
) -> Callable[[dict[str, Any], Endpoints], bool]:
    def apply(doc: dict[str, Any], ep: Endpoints) -> bool:
        if not ep.mcp_ready:
            # Better to write nothing than a server the editor will fail to
            # start on every launch.
            return False
        return _deep_set(doc, (*root, "sensei"), entry(ep))

    return apply


def _mcp_revert(root: tuple[str, ...]) -> Callable[[dict[str, Any]], bool]:
    def revert(doc: dict[str, Any]) -> bool:
        return _deep_unset(doc, (*root, "sensei"), prune=True)

    return revert


# ── Hook entries (Claude-Code-style settings: event → [{matcher, hooks}]) ────


def _is_sensei_hook(hook: Any, marker: str) -> bool:
    if not isinstance(hook, dict):
        return False
    return any(isinstance(hook.get(k), str) and marker in hook[k] for k in ("url", "command"))


def _set_hook_group(
    doc: dict[str, Any], event: str, group: dict[str, Any], marker: str, root: str = "hooks"
) -> bool:
    """Make Sensei's hook group for one event exactly ``group``.

    Every other group — the user's own hooks — stays where it is. A Sensei hook
    found inside a group that also holds the user's hooks is removed from that
    group rather than taking the group with it.
    """
    hooks = doc.get(root)
    if hooks is not None and not isinstance(hooks, dict):
        return False
    groups = (hooks or {}).get(event, [])
    if not isinstance(groups, list):
        return False
    kept: list[Any] = []
    ours: list[Any] = []
    for g in groups:
        inner = g.get("hooks") if isinstance(g, dict) else None
        if isinstance(inner, list) and any(_is_sensei_hook(h, marker) for h in inner):
            rest = [h for h in inner if not _is_sensei_hook(h, marker)]
            ours.append(g)
            if rest:
                kept.append({**g, "hooks": rest})
        else:
            kept.append(g)
    if ours == [group] and len(kept) == len(groups) - 1:
        return False
    doc.setdefault(root, {})[event] = [*kept, group]
    return True


def _drop_hook_groups(doc: dict[str, Any], event: str, marker: str, root: str = "hooks") -> bool:
    hooks = doc.get(root)
    if not isinstance(hooks, dict) or not isinstance(hooks.get(event), list):
        return False
    changed = False
    kept: list[Any] = []
    for g in hooks[event]:
        inner = g.get("hooks") if isinstance(g, dict) else None
        if isinstance(inner, list) and any(_is_sensei_hook(h, marker) for h in inner):
            changed = True
            rest = [h for h in inner if not _is_sensei_hook(h, marker)]
            if rest:
                kept.append({**g, "hooks": rest})
        else:
            kept.append(g)
    if not changed:
        return False
    if kept:
        hooks[event] = kept
    else:
        del hooks[event]
        if not hooks:
            del doc[root]
    return True


# ── Claude Code ─────────────────────────────────────────────────────────────

_SELF_HEAL_MARKER = "hook claude-session-start"


def _claude_dir() -> Path:
    """Claude Code's config directory: $CLAUDE_CONFIG_DIR, else ~/.claude."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def _claude_state() -> Path:
    """Where Claude Code keeps user-scope MCP servers.

    `~/.claude.json` normally — but with CLAUDE_CONFIG_DIR set it is the
    `.claude.json` *inside* that directory, and the one in the home directory
    is never read (checked against Claude Code 2.1.299).
    """
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser() / ".claude.json"
    return Path.home() / ".claude.json"


def _claude_post_tool_group(ep: Endpoints) -> dict[str, Any]:
    return {
        "matcher": CLAUDE_HOOK_MATCHER,
        "hooks": [
            {
                # An HTTP hook, not a command: no process is spawned per tool
                # call, and if nothing answers Claude Code logs the failure and
                # carries on with the original output. A hook that cannot
                # reach Sensei must never be the reason a tool call fails.
                "type": "http",
                "url": ep.hook_url(CLAUDE_HOOK_PATH),
                "timeout": 15,
            }
        ],
    }


def _claude_session_start_group(ep: Endpoints) -> dict[str, Any]:
    return {
        "hooks": [
            {
                # HTTP hooks are not run for SessionStart, and when Sensei is
                # down there would be nothing to answer one anyway.
                "type": "command",
                "command": _shell_command(_sensei_command(ep, "hook", "claude-session-start")),
                "timeout": 20,
            }
        ]
    }


def _claude_code_apply(doc: dict[str, Any], ep: Endpoints) -> bool:
    """Compression hook by default; base-URL routing only when opted in.

    Routing Claude Code through a custom ANTHROPIC_BASE_URL works, but Claude
    Code ≥ 2.1.196 disables Remote Control behind one, and the desktop app's
    Code tab reads its gateway from elsewhere and ignores it. The PostToolUse
    hook has neither problem: Claude Code talks to Anthropic exactly as before,
    and only the tool output it is about to send is compressed.
    """
    changed = _set_hook_group(doc, "PostToolUse", _claude_post_tool_group(ep), CLAUDE_HOOK_PATH)
    # `mcpServers` in settings.json is not a key Claude Code reads (user-scope
    # MCP lives in ~/.claude.json). Sensei 0.2 wrote one; tidy it away.
    if _deep_get(doc, ("mcpServers", "sensei")) is not None:
        changed = _deep_unset(doc, ("mcpServers", "sensei"), prune=True) or changed
    if ep.wants("claude-code", "route"):
        changed = _deep_set(doc, ("env", "ANTHROPIC_BASE_URL"), ep.anthropic) or changed
        changed = (
            _set_hook_group(doc, "SessionStart", _claude_session_start_group(ep), _SELF_HEAL_MARKER)
            or changed
        )
    else:
        # Routing off means off: a stale self-heal hook with nothing to heal
        # would just spawn a process at every session start. A base URL is
        # removed only on an explicit `--no-route`; one that was there before
        # (Sensei 0.2 wrote it by default) is the user's current setup.
        changed = _drop_hook_groups(doc, "SessionStart", _SELF_HEAL_MARKER) or changed
        if ep.refuses("claude-code", "route") and claude_code_routed(doc):
            changed = _deep_unset(doc, ("env", "ANTHROPIC_BASE_URL"), prune=True) or changed
    return changed


def _claude_code_revert(doc: dict[str, Any]) -> bool:
    changed = _drop_hook_groups(doc, "PostToolUse", CLAUDE_HOOK_PATH)
    changed = _drop_hook_groups(doc, "SessionStart", _SELF_HEAL_MARKER) or changed
    if _points_here(_deep_get(doc, ("env", "ANTHROPIC_BASE_URL"))):
        changed = _deep_unset(doc, ("env", "ANTHROPIC_BASE_URL"), prune=True) or changed
    return _deep_unset(doc, ("mcpServers", "sensei"), prune=True) or changed


def claude_code_routed(doc: dict[str, Any]) -> bool:
    """Does this Claude Code settings document route through a local Sensei?"""
    return _points_here(_deep_get(doc, ("env", "ANTHROPIC_BASE_URL")))


def _vscode_claude_env_apply(doc: dict[str, Any], ep: Endpoints) -> bool:
    """The Claude Code VS Code extension takes env from its own setting.

    Only written when routing is opted into; the hook needs nothing here,
    because the extension's sessions read ~/.claude/settings.json like the CLI.
    """
    if not ep.wants("claude-code", "route"):
        return _vscode_claude_env_revert(doc)
    current = doc.get("claudeCode.environmentVariables")
    entries = [e for e in current if isinstance(e, dict)] if isinstance(current, list) else []
    rest = [e for e in entries if e.get("name") != "ANTHROPIC_BASE_URL"]
    desired = [*rest, {"name": "ANTHROPIC_BASE_URL", "value": ep.anthropic}]
    if current == desired:
        return False
    doc["claudeCode.environmentVariables"] = desired
    return True


def _vscode_claude_env_revert(doc: dict[str, Any]) -> bool:
    current = doc.get("claudeCode.environmentVariables")
    if not isinstance(current, list):
        return False
    rest = [
        e
        for e in current
        if not (
            isinstance(e, dict)
            and e.get("name") == "ANTHROPIC_BASE_URL"
            and _points_here(e.get("value"))
        )
    ]
    if rest == current:
        return False
    if rest:
        doc["claudeCode.environmentVariables"] = rest
    else:
        del doc["claudeCode.environmentVariables"]
    return True


# ── Copilot CLI hook ────────────────────────────────────────────────────────


def _curl_hook(ep: Endpoints, path: str, exe: str | None = None) -> str:
    """A command hook that pipes its stdin to a Sensei endpoint.

    curl ships with Windows 10+, macOS and every mainstream Linux, starts in
    milliseconds, and when Sensei is not running exits non-zero with nothing on
    stdout — which Copilot CLI treats as a failed, non-blocking hook.
    `curl.exe` by name, because in Windows PowerShell `curl` is an alias for
    Invoke-WebRequest.

    The body is read with `-T -`, not `--data-binary @-`: Copilot CLI runs the
    `powershell` variant on Windows, where `@-` is a parse error ("Unbekanntes
    Token") — found by running the real CLI. `-T -` means the same in every
    shell; `-X POST` keeps the method and the empty `Expect:` header stops curl
    from waiting for a 100-continue on large outputs.
    """
    exe = exe or ("curl.exe" if sys.platform == "win32" else "curl")
    return (
        f'{exe} -s -m 10 -X POST -H "Content-Type: application/json" -H "Expect:" '
        f"-T - {ep.hook_url(path)}"
    )


def _copilot_hooks_apply(doc: dict[str, Any], ep: Endpoints) -> bool:
    """A file of Sensei's own under ~/.copilot/hooks/.

    Copilot CLI hooks are fail-open for postToolUse: a non-zero exit or a
    timeout is logged and the original result is used.
    """
    desired = {
        "version": 1,
        "hooks": {
            "postToolUse": [
                {
                    "type": "command",
                    "bash": _curl_hook(ep, COPILOT_HOOK_PATH, "curl"),
                    "powershell": _curl_hook(ep, COPILOT_HOOK_PATH, "curl.exe"),
                    "timeoutSec": 15,
                }
            ]
        },
    }
    if doc == desired:
        return False
    doc.clear()
    doc.update(desired)
    return True


def _owned_revert(doc: dict[str, Any]) -> bool:
    """A file Sensei created whole: emptying it lets undo delete it."""
    if not doc:
        return False
    doc.clear()
    return True


# ── opencode / Kilo plugin ──────────────────────────────────────────────────

_PLUGIN_SIGNATURE = "// sensei-plugin v1"


def _plugin_source(ep: Endpoints, client: str, kilo: bool) -> str:
    """A plugin that hands tool output to Sensei after each tool call.

    Fail-open by construction: any error — Sensei not running, a timeout, a
    response it does not understand — leaves the output exactly as it was.
    File reads and edits are never sent, for the same reason as Claude Code's.
    opencode loads named exports of plugin functions; Kilo wants a default
    export of ``{id, server}`` wrapping the same function.
    """
    url = json.dumps(ep.hook_url(GENERIC_HOOK_PATH))
    export = 'export default { id: "sensei", server: SenseiPlugin };\n' if kilo else ""
    return f"""{_PLUGIN_SIGNATURE} — written by `sensei setup-tools`; removed by `--undo`.
// Compresses large tool output (shell, grep, web fetch, MCP) through the local
// Sensei gateway before the model sees it. If Sensei is not running, nothing
// changes. Edit at will; Sensei will not overwrite a modified copy.
const SENSEI = {url};
const SKIP = new Set(["read", "edit", "write", "patch", "multiedit", "apply_patch", "todowrite", "todoread"]);

export const SenseiPlugin = async () => ({{
  "tool.execute.after": async (input, output) => {{
    try {{
      if (!output || typeof output.output !== "string") return;
      const tool = String(input?.tool ?? "");
      if (SKIP.has(tool.toLowerCase()) || tool.startsWith("sensei")) return;
      if (output.output.length < 2000) return;
      const res = await fetch(SENSEI, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json", "X-Sensei-Client": "{client}" }},
        body: JSON.stringify({{ tool, text: output.output }}),
        signal: AbortSignal.timeout(10000),
      }});
      if (!res.ok) return;
      const data = await res.json();
      if (typeof data?.text === "string" && data.text.length < output.output.length) {{
        output.output = data.text;
      }}
    }} catch {{
      // Sensei unavailable: keep the original output.
    }}
  }},
}});
{export}"""


def _opencode_plugin(ep: Endpoints) -> str:
    return _plugin_source(ep, "opencode (plugin)", kilo=False)


def _kilo_plugin(ep: Endpoints) -> str:
    return _plugin_source(ep, "Kilo Code (plugin)", kilo=True)


def _owned_text_apply(render: Callable[[Endpoints], str]) -> Callable[[str, Endpoints], str | None]:
    def apply(text: str, ep: Endpoints) -> str | None:
        if text and not text.startswith(_PLUGIN_SIGNATURE):
            return None  # someone else's file under our name: hands off
        return render(ep)

    return apply


def _owned_text_revert(text: str) -> str:
    return "" if text.startswith(_PLUGIN_SIGNATURE) else text


# ── Continue ────────────────────────────────────────────────────────────────


def _continue_apply(doc: dict[str, Any], ep: Endpoints) -> bool:
    """Continue's legacy config.json keeps a list of models, each with an apiBase.

    Rather than adding a model — which would mean choosing one on the user's
    behalf — this rewrites the apiBase of every OpenAI/Anthropic model already
    configured. Only read by Continue when no config.yaml exists.
    """
    models = doc.get("models")
    if not isinstance(models, list):
        return False
    changed = False
    for model in models:
        if not isinstance(model, dict):
            continue
        provider = str(model.get("provider", "")).lower()
        if provider in ("openai", "openai-compatible", "azure"):
            changed = model.get("apiBase") != ep.openai or changed
            model["apiBase"] = ep.openai
        elif provider == "anthropic":
            changed = model.get("apiBase") != ep.anthropic or changed
            model["apiBase"] = ep.anthropic
    return changed


def _continue_revert(doc: dict[str, Any]) -> bool:
    models = doc.get("models")
    if not isinstance(models, list):
        return False
    changed = False
    for model in models:
        # Only strip the ones pointing at us. A user's own proxy stays.
        if isinstance(model, dict) and _points_here(model.get("apiBase")):
            del model["apiBase"]
            changed = True
    return changed


def _continue_mcp_yaml(ep: Endpoints) -> str:
    args = ", ".join(json.dumps(a) for a in ep.mcp_args)
    return (
        f"{_PLUGIN_SIGNATURE.replace('//', '#')} — written by `sensei setup-tools`\n"
        "name: Sensei\n"
        "version: 0.0.1\n"
        "schema: v1\n"
        "mcpServers:\n"
        "  - name: sensei\n"
        f"    command: {json.dumps(ep.mcp_command)}\n"
        f"    args: [{args}]\n"
    )


def _continue_yaml_apply(text: str, ep: Endpoints) -> str | None:
    if not ep.mcp_ready:
        return text
    marker = _PLUGIN_SIGNATURE.replace("//", "#")
    if text and not text.startswith(marker):
        return None
    return _continue_mcp_yaml(ep)


def _continue_yaml_revert(text: str) -> str:
    return "" if text.startswith(_PLUGIN_SIGNATURE.replace("//", "#")) else text


# ── Codex: table-aware TOML editing ─────────────────────────────────────────

_TOML_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(?:#.*)?$")


def _toml_name(raw: str) -> str:
    """`mcp_servers."sensei"` and `mcp_servers.sensei` are the same table."""
    return ".".join(p.strip().strip('"').strip("'") for p in raw.split("."))


def _toml_sections(text: str) -> list[tuple[str | None, list[str]]]:
    """Split TOML into (table name, lines) runs; the root run has name None.

    A line that looks like a header inside a multi-line string is not one:
    triple-double and triple-single quotes toggle a string state that is
    tracked line by line.
    """
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    open_quote: str | None = None
    for line in text.splitlines(keepends=True):
        match = None if open_quote else _TOML_HEADER.match(line)
        if match:
            sections.append((_toml_name(match.group(1)), [line]))
        else:
            sections[-1][1].append(line)
        open_quote = _toml_quote_state(line, open_quote)
    return sections


def _toml_quote_state(line: str, open_quote: str | None) -> str | None:
    """Which multi-line string delimiter is still open after this line."""
    i = 0
    while i < len(line):
        if open_quote:
            end = line.find(open_quote, i)
            if end < 0:
                return open_quote
            i, open_quote = end + 3, None
            continue
        if line[i] == "#":
            return None
        for quote in ('"""', "'''"):
            if line.startswith(quote, i):
                open_quote = quote
                i += 3
                break
        else:
            if line[i] in "\"'":  # a single-line string: skip to its end
                close = line.find(line[i], i + 1)
                i = len(line) if close < 0 else close + 1
            else:
                i += 1
    return open_quote


def _toml_join(sections: list[tuple[str | None, list[str]]]) -> str:
    """Reassemble sections exactly — the user's text is never reformatted."""
    return "".join("".join(lines) for _, lines in sections)


def _toml_strip_markers(text: str) -> str:
    """Remove Sensei 0.2's block markers; the tables between them are handled
    table by table like any other."""
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if line.strip() not in (BLOCK_BEGIN, BLOCK_END)
    )


def _toml_set_table(text: str, name: str, body: str) -> str:
    """Make table ``name`` (and nothing under it) hold exactly ``body``."""
    sections = _toml_sections(text)
    out: list[tuple[str | None, list[str]]] = []
    placed = False
    for index, (table, lines) in enumerate(sections):
        if table == name or (table is not None and table.startswith(name + ".")):
            if not placed:
                more = any(
                    t != name and not (t or "").startswith(name + ".")
                    for t, _ in sections[index + 1 :]
                )
                spacer = ["\n"] if more else []
                out.append((name, [f"[{name}]\n", *body.splitlines(keepends=True), *spacer]))
                placed = True
            continue
        out.append((table, lines))
    if not placed:
        tail = out[-1][1]
        if tail and not tail[-1].endswith("\n"):
            tail[-1] += "\n"
        if tail and tail[-1].strip():
            tail.append("\n")
        out.append((name, [f"[{name}]\n", *body.splitlines(keepends=True)]))
    return _toml_join(out)


def _toml_drop_table(text: str, name: str) -> str:
    sections = _toml_sections(text)
    kept = [
        (t, lines)
        for t, lines in sections
        if not (t == name or (t is not None and t.startswith(name + ".")))
    ]
    return _toml_join(kept)


def _toml_root_key(text: str, key: str, value: str | None) -> str:
    """Set (or with None, remove) a key in the root table — before any header.

    A top-level key cannot be appended at the end of a file: it would land
    inside whatever table happens to be last.
    """
    sections = _toml_sections(text)
    root = sections[0][1]
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    found = [i for i, line in enumerate(root) if pattern.match(line)]
    if value is None:
        for i in reversed(found):
            del root[i]
    elif found:
        root[found[0]] = f"{key} = {value}\n"
    else:
        insert = len(root)
        while insert > 0 and not root[insert - 1].strip():
            insert -= 1
        root.insert(insert, f"{key} = {value}\n")
        if len(sections) > 1 and (insert + 1 >= len(root) or root[insert + 1].strip()):
            root.insert(insert + 1, "\n")
    return _toml_join(sections)


def _toml_root_value(text: str, key: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.+?)\s*$")
    for line in _toml_sections(text)[0][1]:
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None


def _codex_body_mcp(ep: Endpoints) -> str:
    return f"command = {json.dumps(ep.mcp_command)}\nargs = {json.dumps(list(ep.mcp_args))}\n"


def _codex_body_provider(ep: Endpoints) -> str:
    return (
        'name = "Sensei"\n'
        f'base_url = "{ep.openai}"\n'
        # Codex removed the chat wire API in 2026: "responses" is the only
        # value it accepts, and a provider still set to "chat" stops it from
        # starting at all. Sensei serves /v1/responses for it.
        'wire_api = "responses"\n'
        'env_key = "OPENAI_API_KEY"\n'
    )


def _codex_conflict(text: str) -> bool:
    """`sensei = {…}` inline inside a `[mcp_servers]` table the user wrote."""
    for table, lines in _toml_sections(text):
        if table in ("mcp_servers", "model_providers") and any(
            re.match(r"^\s*\"?sensei\"?\s*=", line) for line in lines
        ):
            return True
    return False


def _codex_apply(text: str, ep: Endpoints) -> str | None:
    """Edit ~/.codex/config.toml table by table.

    The Codex desktop app rewrites config.toml in its own key order, and does
    not promise to keep comments. So nothing here depends on marker comments:
    Sensei's tables are found by name, and undo removes them by name.

    * ``[mcp_servers.sensei]`` — the part that works for everyone, ChatGPT
      sign-in included.
    * ``[model_providers.sensei]`` — selectable by API-key users with
      ``codex -c model_provider=sensei``; unused otherwise.
    * ``openai_base_url`` — only with the ``codex:route`` opt-in. It routes the
      built-in provider, ChatGPT sign-in included, which needs a Sensei whose
      gateway forwards ChatGPT tokens to the Codex backend.
    """
    if _codex_conflict(text):
        return None
    out = _toml_strip_markers(text)
    if ep.mcp_ready:
        out = _toml_set_table(out, "mcp_servers.sensei", _codex_body_mcp(ep))
    out = _toml_set_table(out, "model_providers.sensei", _codex_body_provider(ep))
    if ep.wants("codex", "route"):
        out = _toml_root_key(out, "openai_base_url", json.dumps(ep.openai))
    elif _points_here(_toml_value_str(_toml_root_value(out, "openai_base_url"))):
        out = _toml_root_key(out, "openai_base_url", None)
    return out


def _toml_value_str(raw: str | None) -> str | None:
    if raw is None:
        return None
    with contextlib.suppress(json.JSONDecodeError):
        value = json.loads(raw.split("#", 1)[0].strip())
        return value if isinstance(value, str) else None
    return raw.strip().strip("'\"")


def _codex_revert(text: str) -> str:
    out = _toml_strip_markers(text)
    out = _toml_drop_table(out, "mcp_servers.sensei")
    out = _toml_drop_table(out, "model_providers.sensei")
    if _points_here(_toml_value_str(_toml_root_value(out, "openai_base_url"))):
        out = _toml_root_key(out, "openai_base_url", None)
    return out.rstrip("\n") + "\n" if out.strip() else ""


# ── The registry ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Part:
    """One file a tool reads, and what Sensei puts in it.

    ``fmt`` decides what ``apply`` and ``revert`` receive:

    * ``json`` — a parsed object; apply mutates it and returns whether it did.
    * ``json-list`` — the same, for a file whose top level is an array.
    * ``text`` — the file's text; apply returns the new text (or None when it
      cannot be changed safely), revert returns the text without Sensei.
    """

    key: str
    path: Callable[[], Path]
    apply: Callable[..., Any]
    revert: Callable[..., Any]
    fmt: str = "json"
    legacy_paths: tuple[Callable[[], Path], ...] = ()
    project_path: Callable[[Path], Path] | None = None
    # Write only where the tool already has a directory. For the second, third
    # and later homes of a tool (other editors, older layouts): writing one the
    # tool does not use would create a directory tree for nothing.
    only_if_present: bool = False
    # Whether this part decides "connected". Opt-in parts do not: a tool whose
    # optional routing is off is still connected.
    counts: bool = True

    def targets(self) -> list[Path]:
        seen: list[Path] = []
        for path in (self.path(), *(p() for p in self.legacy_paths)):
            if path not in seen:
                seen.append(path)
        return seen

    def write_targets(self, *, force: bool = False) -> list[Path]:
        """The targets worth writing: those the tool has a directory for.

        If none has one, the primary location only (when ``force`` or the tool
        was detected some other way) — a tool must be connectable before it has
        created its own config directory.
        """
        all_targets = self.targets()
        present = [t for t in all_targets if t.exists() or _is_tool_dir(t.parent)]
        if self.only_if_present:
            return present
        return present or ([all_targets[0]] if all_targets else [])


@dataclass(frozen=True)
class Integration:
    """One tool Sensei knows how to wire up.

    ``detect`` is deliberately generous: a tool counts as present if either its
    binary is on PATH or its config directory exists. Someone who uninstalled
    the CLI but kept the directory still wants the setting to be correct when
    they reinstall, and writing an entry for a tool that is not there costs
    nothing and breaks nothing.

    The constructor's ``path``/``apply``/``revert`` describe the main file;
    ``parts`` adds any further files the same tool reads.
    """

    id: str
    name: str
    path: Callable[[], Path]
    apply: Callable[..., Any]
    revert: Callable[..., Any]
    binaries: tuple[str, ...] = ()
    extra_dirs: tuple[Callable[[], Path], ...] = ()
    # Where the tool used to keep its configuration, or other places it reads
    # the same file from. All of them get written where the tool has a
    # directory: a tool mid-migration reads one and will read the other after
    # its next update, and there is no way from here to know which.
    legacy_paths: tuple[Callable[[], Path], ...] = ()
    # Where this tool reads per-repository configuration, if it does.
    project_path: Callable[[Path], Path] | None = None
    note: str = ""
    # False when the format is documented but Sensei has not been able to verify
    # it end to end against the real tool.
    verified: bool = True
    fmt: str = "json"
    parts: tuple[Part, ...] = ()
    # What connecting does: "hook", "route", "mcp", or a combination like
    # "hook+mcp". Shown in the status table so nobody expects more than this.
    support: str = "mcp"
    # Why a capability is missing — e.g. why routing is impossible.
    why: str = ""
    # Opt-in features this tool offers (see Endpoints.opt_in).
    options: tuple[str, ...] = ()
    # Process image names. A running process older than Sensei's last write to
    # its config has not read the change yet: "needs restart".
    processes: tuple[str, ...] = ()

    def all_parts(self) -> list[Part]:
        main = Part(
            key="main",
            path=self.path,
            apply=self.apply,
            revert=self.revert,
            fmt=self.fmt,
            legacy_paths=self.legacy_paths,
            project_path=self.project_path,
        )
        return [main, *self.parts]

    def part(self, key: str) -> Part | None:
        return next((p for p in self.all_parts() if p.key == key), None)

    def targets(self) -> list[Path]:
        """Every config file the main part might be reading, current one first."""
        return self.all_parts()[0].targets()

    def detect(self) -> bool:
        if any(shutil.which(b) for b in self.binaries):
            return True
        for part in self.all_parts():
            if part.only_if_present:
                continue
            for target in part.targets():
                if target.exists() or _is_tool_dir(target.parent):
                    return True
        if any(d().exists() for d in self.extra_dirs):
            return True
        # A tool found only at an alternate home (Cline inside Cursor, say).
        return any(p.write_targets() for p in self.all_parts() if p.only_if_present)


def _is_tool_dir(path: Path) -> bool:
    """Does this directory exist *and* belong to a specific tool?

    Detection treats "the config directory is there" as evidence the tool is
    installed. That inference only holds for a directory the tool created:
    `~/.aider.conf.yml` lives directly in the home directory, and the home
    directory always exists, so without this check Aider — and every other tool
    with a dotfile rather than a dotdir — reports as installed on every machine.
    The same goes for the shared roots `~/.config` and `%APPDATA%`.
    """
    try:
        if not path.is_dir():
            return False
        resolved = path.resolve()
        shared = {Path.home().resolve(), Path(path.anchor)}
        with contextlib.suppress(OSError):
            shared |= {_appdata().resolve(), _dot_config().resolve(), _localappdata().resolve()}
        return resolved not in shared
    except OSError:  # pragma: no cover — unreadable path
        return False


def _mcp_tool(
    tool_id: str,
    name: str,
    path: Callable[[], Path],
    *,
    root: tuple[str, ...] = ("mcpServers",),
    entry: Callable[[Endpoints], dict[str, Any]] = _mcp_entry,
    why: str = "",
    **kw: Any,
) -> Integration:
    """The common case: one JSON file, one `sensei` server entry."""
    return Integration(
        id=tool_id,
        name=name,
        path=path,
        apply=_mcp_apply(root, entry),
        revert=_mcp_revert(root),
        support=kw.pop("support", "mcp"),
        why=why,
        **kw,
    )


_NO_LOCAL_ROUTE = (
    "its model requests are sent from the vendor's servers, which cannot reach a local gateway"
)

REGISTRY: tuple[Integration, ...] = (
    Integration(
        id="claude-code",
        name="Claude Code",
        binaries=("claude",),
        path=lambda: _claude_dir() / "settings.json",
        project_path=lambda root: root / ".claude" / "settings.local.json",
        apply=_claude_code_apply,
        revert=_claude_code_revert,
        parts=(
            Part(
                key="mcp",
                # User-scope MCP servers live here, not in settings.json.
                path=_claude_state,
                project_path=lambda root: root / ".mcp.json",
                apply=_mcp_apply(("mcpServers",), _mcp_entry_typed("stdio")),
                revert=_mcp_revert(("mcpServers",)),
            ),
            Part(
                key="vscode-env",
                path=lambda: _vscode_user("Code") / "settings.json",
                legacy_paths=(lambda: _vscode_user("Code - Insiders") / "settings.json",),
                apply=_vscode_claude_env_apply,
                revert=_vscode_claude_env_revert,
                only_if_present=True,
                counts=False,
            ),
        ),
        support="hook+mcp",
        options=("route",),
        note="Compresses Bash, Grep, Glob, WebFetch and MCP output through a "
        "PostToolUse hook (never Read/Edit/Write) and registers sensei_retrieve. "
        "Sign-in, Remote Control and the desktop Code tab are unaffected. "
        "Base-URL routing is opt-in: `sensei setup-tools --only claude-code --route` "
        "(turns Remote Control off).",
    ),
    _mcp_tool(
        "claude-desktop",
        "Claude Desktop",
        _claude_desktop_config,
        legacy_paths=(_claude_desktop_msix,),
        why="chat traffic goes to Anthropic directly; routing it means third-party "
        "mode, which drops the claude.ai sign-in",
        note="MCP server. Store (MSIX) installs read their own copy, which is written too.",
        processes=("claude.exe", "Claude"),
    ),
    Integration(
        id="cursor",
        name="Cursor",
        path=lambda: Path.home() / ".cursor" / "mcp.json",
        project_path=lambda root: root / ".cursor" / "mcp.json",
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        why=_NO_LOCAL_ROUTE,
        note="MCP server, shared by the editor and cursor-agent.",
        processes=("cursor.exe", "Cursor"),
    ),
    Integration(
        id="vscode-copilot",
        name="VS Code (GitHub Copilot)",
        binaries=("code",),
        path=lambda: _vscode_user("Code") / "mcp.json",
        legacy_paths=(lambda: _vscode_user("Code - Insiders") / "mcp.json",),
        project_path=lambda root: root / ".vscode" / "mcp.json",
        apply=_mcp_apply(("servers",), _mcp_entry_typed("stdio")),
        revert=_mcp_revert(("servers",)),
        # No routing part. VS Code 1.142 never uses a literal `apiKey` from
        # chatLanguageModels.json: secret fields are always read as an
        # `${input:…}` reference into SecretStorage, which no other program can
        # write. A group Sensei wrote there would load with no key at all.
        why="Copilot-hosted models go to GitHub; a bring-your-own-key model can be pointed "
        "at Sensei by hand (Language Models view → Custom Endpoint), not from a file",
        note="MCP server for Copilot agent mode.",
        verified=False,
    ),
    Integration(
        id="copilot-cli",
        name="GitHub Copilot CLI",
        binaries=("copilot",),
        path=lambda: (
            Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot") / "mcp-config.json"
        ),
        apply=_mcp_apply(("mcpServers",), _mcp_entry_copilot),
        revert=_mcp_revert(("mcpServers",)),
        parts=(
            Part(
                key="hooks",
                path=lambda: (
                    Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot")
                    / "hooks"
                    / "sensei.json"
                ),
                apply=_copilot_hooks_apply,
                revert=_owned_revert,
            ),
        ),
        support="hook+mcp",
        note="MCP server plus a postToolUse hook that compresses tool output. Copilot "
        "itself already swaps outputs over ~25 KB for a short preview before hooks run, "
        "so the hook pays off on the mid-sized ones. Model routing (bring your own key) "
        "is per launch: `sensei wrap copilot`.",
    ),
    Integration(
        id="windsurf",
        name="Devin Desktop / Windsurf",
        binaries=("windsurf", "devin"),
        path=_devin_config,
        legacy_paths=(
            lambda: Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
            lambda: Path.home() / ".codeium" / "windsurf-next" / "mcp_config.json",
            lambda: Path.home() / ".codeium" / "windsurf-insiders" / "mcp_config.json",
        ),
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        why=_NO_LOCAL_ROUTE,
        note="MCP server, for the editor and the Devin CLI. Also reads Claude Code's "
        "hooks, but cannot replace tool output with them.",
    ),
    Integration(
        id="cline",
        name="Cline",
        binaries=("cline",),
        path=lambda: (
            Path(os.environ.get("CLINE_DIR") or Path.home() / ".cline")
            / "data"
            / "settings"
            / "cline_mcp_settings.json"
        ),
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        parts=(
            Part(
                key="extension",
                path=lambda: (
                    _vscode_global_storage("Code")
                    / "saoudrizwan.claude-dev"
                    / "settings"
                    / "cline_mcp_settings.json"
                ),
                legacy_paths=_extension_settings(
                    "saoudrizwan.claude-dev", "cline_mcp_settings.json"
                )[1:],
                apply=_mcp_apply(("mcpServers",)),
                revert=_mcp_revert(("mcpServers",)),
                only_if_present=True,
            ),
        ),
        why="provider settings are kept in the editor's secret storage",
        note="MCP server, for the CLI/SDK and the extension in every editor it is installed in.",
    ),
    Integration(
        id="roo",
        name="Roo Code / Zoo Code",
        path=lambda: (
            _vscode_global_storage("Code")
            / "rooveterinaryinc.roo-cline"
            / "settings"
            / "mcp_settings.json"
        ),
        legacy_paths=(
            *_extension_settings("rooveterinaryinc.roo-cline", "mcp_settings.json")[1:],
            *_extension_settings("zoocodeorganization.zoo-code", "mcp_settings.json"),
        ),
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        why="provider settings are kept in the editor's secret storage",
        note="MCP server. Roo Code shut down in May 2026; Zoo Code is its fork.",
        verified=False,
    ),
    Integration(
        id="kilo",
        name="Kilo Code",
        binaries=("kilo",),
        path=lambda: _dot_config() / "kilo" / "kilo.jsonc",
        apply=_mcp_apply(("mcp",), _mcp_entry_opencode),
        revert=_mcp_revert(("mcp",)),
        parts=(
            Part(
                key="legacy",
                path=lambda: (
                    _vscode_global_storage("Code")
                    / "kilocode.kilo-code"
                    / "settings"
                    / "mcp_settings.json"
                ),
                legacy_paths=_extension_settings("kilocode.kilo-code", "mcp_settings.json")[1:],
                apply=_mcp_apply(("mcpServers",)),
                revert=_mcp_revert(("mcpServers",)),
                only_if_present=True,
                counts=False,
            ),
            Part(
                key="plugin",
                fmt="text",
                path=lambda: _dot_config() / "kilo" / "plugin" / "sensei.js",
                apply=_owned_text_apply(_kilo_plugin),
                revert=_owned_text_revert,
            ),
        ),
        support="hook+mcp",
        note="MCP server plus a tool.execute.after plugin that compresses tool output. "
        "A kilo.jsonc with comments is a manual step.",
    ),
    Integration(
        id="opencode",
        name="opencode",
        binaries=("opencode",),
        path=lambda: _dot_config() / "opencode" / "opencode.json",
        project_path=lambda root: root / "opencode.json",
        apply=_mcp_apply(("mcp",), _mcp_entry_opencode),
        revert=_mcp_revert(("mcp",)),
        parts=(
            Part(
                key="plugin",
                fmt="text",
                path=lambda: _dot_config() / "opencode" / "plugins" / "sensei.js",
                apply=_owned_text_apply(_opencode_plugin),
                revert=_owned_text_revert,
            ),
        ),
        support="hook+mcp",
        note="MCP server plus a tool.execute.after plugin that compresses tool output.",
    ),
    Integration(
        id="zed",
        name="Zed",
        binaries=("zed",),
        path=lambda: _xdg_config() / "zed" / "settings.json",
        apply=_mcp_apply(("context_servers",)),
        revert=_mcp_revert(("context_servers",)),
        note="Zed calls them context servers. Its settings file allows comments, "
        "and a file with any is reported as a manual step rather than rewritten.",
        why="routing needs your API key in Zed's keychain; see docs/integrations/zed.md",
        verified=False,
    ),
    Integration(
        id="continue",
        name="Continue",
        binaries=("cn",),
        path=lambda: Path.home() / ".continue" / "config.json",
        apply=_continue_apply,
        revert=_continue_revert,
        parts=(
            Part(
                key="mcp",
                fmt="text",
                path=lambda: Path.home() / ".continue" / "mcpServers" / "sensei.yaml",
                apply=_continue_yaml_apply,
                revert=_continue_yaml_revert,
            ),
        ),
        support="route+mcp",
        note="MCP server via ~/.continue/mcpServers/. The legacy config.json's model "
        "apiBase is repointed when present; config.yaml models are a manual step.",
        verified=False,
    ),
    Integration(
        id="gemini-cli",
        name="Gemini CLI",
        binaries=("gemini",),
        path=lambda: Path.home() / ".gemini" / "settings.json",
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        # No AfterTool hook. Gemini CLI 0.64 can only block a result ("Tool
        # result blocked: …", flagged execution_failed) or append to it; a
        # compressed output delivered as a failure makes the model retry.
        why="Gemini speaks its own wire format, Google sign-in cannot be redirected, and "
        "its hooks can block a tool result but not replace it",
        note="MCP server.",
    ),
    _mcp_tool(
        "antigravity",
        "Antigravity CLI",
        lambda: Path.home() / ".gemini" / "config" / "mcp_config.json",
        binaries=("agy",),
        legacy_paths=(lambda: Path.home() / ".gemini" / "antigravity-cli" / "mcp_config.json",),
        why="Gemini wire format; Google sign-in cannot be redirected",
        verified=False,
    ),
    _mcp_tool(
        "qwen-code",
        "Qwen Code",
        lambda: Path.home() / ".qwen" / "settings.json",
        binaries=("qwen",),
        why="routing needs an API key provider entry; use `sensei wrap qwen`",
        verified=False,
    ),
    _mcp_tool(
        "crush",
        "Crush",
        lambda: _dot_config() / "crush" / "crush.json",
        root=("mcp",),
        entry=_mcp_entry_typed("stdio"),
        binaries=("crush",),
        verified=False,
    ),
    _mcp_tool(
        "factory-droid",
        "Factory Droid",
        lambda: Path.home() / ".factory" / "mcp.json",
        entry=_mcp_entry_typed("stdio"),
        binaries=("droid",),
        verified=False,
    ),
    _mcp_tool(
        "junie",
        "JetBrains Junie",
        lambda: Path.home() / ".junie" / "mcp" / "mcp.json",
        binaries=("junie",),
        verified=False,
    ),
    _mcp_tool(
        "kimi",
        "Kimi Code CLI",
        lambda: Path.home() / ".kimi-code" / "mcp.json",
        binaries=("kimi",),
        verified=False,
    ),
    _mcp_tool(
        "amp",
        "Amp",
        lambda: _dot_config() / "amp" / "settings.json",
        root=("amp.mcpServers",),
        binaries=("amp",),
        why=_NO_LOCAL_ROUTE,
        verified=False,
    ),
    _mcp_tool(
        "kiro",
        "Kiro",
        lambda: Path.home() / ".kiro" / "settings" / "mcp.json",
        binaries=("kiro",),
        why="no bring-your-own-model support",
        verified=False,
    ),
    _mcp_tool(
        "warp",
        "Warp",
        lambda: Path.home() / ".warp" / ".mcp.json",
        why=_NO_LOCAL_ROUTE,
        verified=False,
    ),
    _mcp_tool(
        "augment",
        "Augment (Auggie)",
        lambda: Path.home() / ".augment" / "settings.json",
        binaries=("auggie",),
        why="no bring-your-own-model support",
        verified=False,
    ),
    _mcp_tool(
        "lmstudio",
        "LM Studio",
        lambda: Path.home() / ".lmstudio" / "mcp.json",
        why="LM Studio is a model server — use it as Sensei's upstream instead",
        verified=False,
    ),
    Integration(
        id="codex",
        name="Codex (CLI, IDE, app)",
        binaries=("codex",),
        fmt="text",
        path=lambda: Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml",
        apply=_codex_apply,
        revert=_codex_revert,
        support="mcp",
        options=("route",),
        why="Codex hooks cannot replace tool output; routing a ChatGPT sign-in needs "
        "`--route` and a gateway that forwards it",
        note="Adds the `sensei` MCP tools, which work on a ChatGPT subscription, and a "
        "`sensei` provider for API-key users (`codex -c model_provider=sensei`). "
        "`--route` sets openai_base_url for the built-in provider.",
        processes=("codex.exe", "Codex.exe", "codex"),
    ),
)


# ── Formats with no standard-library writer ─────────────────────────────────


@dataclass(frozen=True)
class BlockIntegration:
    """A tool whose config Sensei appends to rather than parses.

    YAML has no writer in the standard library, and this project keeps its
    dependency list short on purpose. Appending a marker-delimited block is the
    honest middle ground: it is valid as long as the keys are not already set,
    it is trivially reversible by deleting the block, and when the keys *are*
    already set the tool reports a manual step instead of guessing which value
    the user meant to keep.
    """

    id: str
    name: str
    path: Callable[[], Path]
    body: Callable[[Endpoints], str]
    # If any of these match the existing file, appending would create a
    # duplicate key — which YAML resolves silently in the wrong direction.
    conflicts: tuple[str, ...]
    binaries: tuple[str, ...] = ()
    note: str = ""
    verified: bool = False
    support: str = "route"
    why: str = ""
    options: tuple[str, ...] = ()
    processes: tuple[str, ...] = ()

    def detect(self) -> bool:
        if any(shutil.which(b) for b in self.binaries):
            return True
        target = self.path()
        return target.exists() or _is_tool_dir(target.parent)


def _goose_body(ep: Endpoints) -> str:
    args = "".join(f"\n      - {json.dumps(a)}" for a in ep.mcp_args)
    return (
        "extensions:\n"
        "  sensei:\n"
        "    type: stdio\n"
        "    name: sensei\n"
        f"    cmd: {json.dumps(ep.mcp_command)}\n"
        f"    args:{args}\n"
        "    enabled: true\n"
        "    timeout: 300\n"
    )


BLOCK_REGISTRY: tuple[BlockIntegration, ...] = (
    BlockIntegration(
        id="aider",
        name="Aider",
        binaries=("aider",),
        path=lambda: Path.home() / ".aider.conf.yml",
        body=lambda ep: f"openai-api-base: {ep.openai}\n",
        conflicts=(r"^\s*openai-api-base\s*:",),
        note="Aider reads OPENAI_API_BASE, not OPENAI_BASE_URL — this is the "
        "config-file equivalent. Aider has no MCP.",
    ),
    BlockIntegration(
        id="goose",
        name="Goose",
        binaries=("goose",),
        path=lambda: _goose_dir() / "config.yaml",
        body=_goose_body,
        conflicts=(r"^extensions\s*:",),
        support="mcp",
        note="MCP extension. A config.yaml that already has an `extensions:` key is a "
        "manual step. Routing per launch: `sensei wrap goose`.",
    ),
)


# Tools Sensei knows about but cannot connect from this machine, and why.
# Shown in the status table so "not listed" never has to be guessed at.
@dataclass(frozen=True)
class Unsupported:
    id: str
    name: str
    why: str
    docs: str = ""
    detect: Callable[[], bool] = lambda: False


UNSUPPORTED: tuple[Unsupported, ...] = (
    Unsupported(
        "jetbrains-ai",
        "JetBrains AI Assistant",
        "model and MCP settings live only in the IDE's UI; it can import Claude "
        "Desktop's MCP servers, which Sensei does wire",
        docs="docs/integrations/jetbrains.md",
        detect=lambda: (_appdata() / "JetBrains").is_dir(),  # noqa: PLW0108
    ),
    Unsupported(
        "chatgpt",
        "ChatGPT (web and desktop)",
        "remote MCP only — needs a tunnel and a token",
        docs="docs/remote-mcp.md",
    ),
    Unsupported(
        "claude-ai",
        "claude.ai connectors",
        "called from Anthropic's cloud — needs a tunnel and a token",
        docs="docs/remote-mcp.md",
    ),
    Unsupported(
        "devin-cloud",
        "Devin (cloud)",
        "runs in Devin's VM — needs a tunnel and a token",
        docs="docs/remote-mcp.md",
    ),
)


# ── Manifest ────────────────────────────────────────────────────────────────


def _read_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"version": 1, "entries": []}
    try:
        doc = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "entries": []}
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), list):
        return {"version": 1, "entries": []}
    return doc


def _write_manifest(doc: dict[str, Any]) -> None:
    SENSEI_HOME.mkdir(parents=True, exist_ok=True)
    _atomic_write(MANIFEST_PATH, _dump_json(doc))


def declined() -> set[str]:
    """Tools the user has actively disconnected.

    Without this there is no difference between "not wired yet" and "wired, and
    then deliberately unwired", and the background watcher cannot tell them
    apart either — it would reconnect a tool seconds after `setup-tools --undo`
    removed it, forever.
    """
    raw = _read_manifest().get("declined", [])
    return {str(x) for x in raw} if isinstance(raw, list) else set()


def _set_declined(manifest: dict[str, Any], ids: set[str]) -> None:
    manifest["declined"] = sorted(ids)


def auto_connect_choice() -> bool | None:
    """What the user said about connecting tools automatically.

    True: yes. False: no — set by the installer's "don't connect my tools" and by
    "Disconnect everything", and it has to outlive the process that set it, or
    the background watcher wires everything thirty seconds after the installer
    was told not to. None: never asked, which means the default (connect).
    """
    value = _read_manifest().get("auto_connect")
    return value if isinstance(value, bool) else None


def auto_connect_allowed() -> bool:
    return bool(settings.auto_connect) and auto_connect_choice() is not False


def set_auto_connect(value: bool | None, *, only_if_unset: bool = False) -> bool | None:
    """Record the choice. Returns the value now in effect."""
    manifest = _read_manifest()
    current = manifest.get("auto_connect")
    if only_if_unset and isinstance(current, bool):
        return current
    if value is None:
        manifest.pop("auto_connect", None)
    else:
        manifest["auto_connect"] = value
    _write_manifest(manifest)
    return value


def forget_choices() -> None:
    """Drop every recorded decision: refusals, the auto-connect choice, opt-ins.

    For the uninstaller, after it has undone every edit: uninstalling is not a
    decision about any one tool, and a reinstall should start fresh.
    """
    manifest = _read_manifest()
    for key in ("declined", "auto_connect", "options"):
        manifest.pop(key, None)
    _write_manifest(manifest)


def _opt_ins() -> frozenset[str]:
    options = _read_manifest().get("options", {})
    if not isinstance(options, dict):
        return frozenset()
    out = set()
    for tool_id, features in options.items():
        if isinstance(features, dict):
            # An explicit "off" is recorded as "!feature": different from never
            # having been asked, because only an explicit off removes a setting
            # that an older Sensei (or the user) put there.
            out |= {
                f"{tool_id}:{name}" if on is True else f"{tool_id}:!{name}"
                for name, on in features.items()
                if isinstance(on, bool)
            }
    return frozenset(out)


def set_option(tool_id: str, feature: str, enabled: bool) -> None:
    """Turn an opt-in feature (e.g. Claude Code base-URL routing) on or off."""
    manifest = _read_manifest()
    options = manifest.get("options")
    if not isinstance(options, dict):
        options = {}
    features = options.get(tool_id)
    if not isinstance(features, dict):
        features = {}
    features[feature] = bool(enabled)
    if features:
        options[tool_id] = features
    else:
        options.pop(tool_id, None)
    manifest["options"] = options
    _write_manifest(manifest)


def _record(
    manifest: dict[str, Any],
    *,
    tool_id: str,
    path: Path,
    backup: Path | None,
    kind: str,
    part: str = "main",
) -> None:
    """Remember one edit, replacing any earlier record for the same file.

    Keyed by (tool_id, path) rather than tool_id alone: the same tool can be
    wired machine-wide and again inside a checkout, and undoing one must not
    make Sensei forget it ever touched the other. An earlier record's backup is
    kept — it holds the file as it was before Sensei ever touched it, which is
    the one undo has to restore.
    """
    earlier = next(
        (
            e
            for e in manifest["entries"]
            if e.get("tool_id") == tool_id and e.get("path") == str(path)
        ),
        None,
    )
    manifest["entries"] = [e for e in manifest["entries"] if e is not earlier]
    first_backup: Any = str(backup) if backup else None
    created = backup is None
    # "Pristine": nothing but Sensei has ever written this file since Sensei
    # first touched it. Only then may undo restore the first backup (or delete
    # a file Sensei created) wholesale. The backup taken just before this
    # write is the file as it stood; if that differs from what Sensei left
    # last time, someone else wrote in between — the user adding permissions,
    # Claude Code rewriting ~/.claude.json — and restoring the oldest copy
    # would silently throw their work away.
    pristine = True
    if earlier is not None:
        first_backup = earlier.get("backup")
        created = bool(earlier.get("created", earlier.get("backup") is None))
        before = _sha256(backup) if backup is not None and backup.exists() else None
        pristine = bool(earlier.get("pristine", True)) and earlier.get("hash_after") == before
    manifest["entries"].append(
        {
            "tool_id": tool_id,
            "kind": kind,
            "part": part,
            "path": str(path),
            "backup": first_backup,
            "created": created,
            "pristine": pristine,
            "hash_after": _sha256(path) if path.exists() else None,
            "written_at": time.time(),
        }
    )


# ── Apply ───────────────────────────────────────────────────────────────────


def _snippet(part: Part, ep: Endpoints) -> str:
    """What to paste by hand, in the file's own format."""
    if part.fmt == "text":
        result = part.apply("", ep)
        return result or ""
    empty: Any = [] if part.fmt == "json-list" else {}
    part.apply(empty, ep)
    return _dump_json(empty)


def _apply_part(
    integration: Integration,
    part: Part,
    path: Path,
    ep: Endpoints,
    manifest: dict[str, Any],
    stamp: str,
    *,
    dry_run: bool,
) -> Outcome:
    name = integration.name
    label = "" if part.key == "main" else f"{part.key}: "

    if part.fmt == "text":
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        desired = part.apply(existing, ep)
        if desired is None:
            return Outcome(
                integration.id,
                name,
                "manual",
                detail=f"{label}Sensei's entry conflicts with one already there — not overwriting it",
                path=path,
                manual_snippet=_snippet(part, ep),
            )
        if desired == existing or (not desired and not existing):
            return Outcome(integration.id, name, "unchanged", detail=label.rstrip(": "), path=path)
        if dry_run:
            return Outcome(integration.id, name, "applied", detail=f"{label}dry run", path=path)
        backup = _backup(path, stamp)
        _atomic_write(path, desired)
        _record(
            manifest, tool_id=integration.id, path=path, backup=backup, kind="text", part=part.key
        )
        return Outcome(integration.id, name, "applied", detail=label.rstrip(": "), path=path)

    root: type = list if part.fmt == "json-list" else dict
    doc = _load_json(path, root)
    if doc is None:
        snippet = _snippet(part, ep)
        if not snippet.strip() or snippet.strip() in ("{}", "[]"):
            return Outcome(integration.id, name, "unchanged", path=path)
        return Outcome(
            integration.id,
            name,
            "manual",
            detail=f"{label}config file is not strict JSON (comments?) — not rewriting it",
            path=path,
            manual_snippet=snippet,
        )

    before = json.dumps(doc, sort_keys=True)
    if not part.apply(doc, ep):
        return Outcome(integration.id, name, "unchanged", detail=label.rstrip(": "), path=path)
    if json.dumps(doc, sort_keys=True) == before:  # pragma: no cover — belt and braces
        return Outcome(integration.id, name, "unchanged", path=path)

    if dry_run:
        return Outcome(integration.id, name, "applied", detail=f"{label}dry run", path=path)

    backup = _backup(path, stamp)
    _atomic_write(path, _dump_json(doc))
    _record(manifest, tool_id=integration.id, path=path, backup=backup, kind="json", part=part.key)
    return Outcome(integration.id, name, "applied", detail=label.rstrip(": "), path=path)


def _apply_json(
    integration: Integration,
    ep: Endpoints,
    manifest: dict[str, Any],
    stamp: str,
    *,
    dry_run: bool,
    project: Path | None = None,
    path: Path | None = None,
) -> Outcome:
    """The main part of one integration, at one path. Kept for callers of 0.2."""
    part = integration.all_parts()[0]
    target = path or (part.project_path(project) if project and part.project_path else part.path())
    return _apply_part(integration, part, target, ep, manifest, stamp, dry_run=dry_run)


def _apply_block(
    integration: BlockIntegration,
    ep: Endpoints,
    manifest: dict[str, Any],
    stamp: str,
    *,
    dry_run: bool,
) -> Outcome:
    path = integration.path()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    desired = integration.body(ep)

    if BLOCK_BEGIN in existing:
        # Sensei's own region, delimited by its own markers, so rewriting it is
        # safe — and necessary, or a block written by an older version (or for
        # an older port) would never change again.
        current = re.search(
            rf"{re.escape(BLOCK_BEGIN)}\n(.*?){re.escape(BLOCK_END)}",
            existing,
            flags=re.DOTALL,
        )
        if current is not None and current.group(1) == desired:
            return Outcome(integration.id, integration.name, "unchanged", path=path)
        if dry_run:
            return Outcome(
                integration.id, integration.name, "applied", detail="dry run — update", path=path
            )
        backup = _backup(path, stamp)
        updated = re.sub(
            rf"{re.escape(BLOCK_BEGIN)}\n.*?{re.escape(BLOCK_END)}",
            lambda _: f"{BLOCK_BEGIN}\n{desired}{BLOCK_END}",
            existing,
            flags=re.DOTALL,
        )
        _atomic_write(path, updated)
        _record(manifest, tool_id=integration.id, path=path, backup=backup, kind="block")
        return Outcome(integration.id, integration.name, "applied", detail="updated", path=path)

    for pattern in integration.conflicts:
        if re.search(pattern, existing, re.MULTILINE):
            return Outcome(
                integration.id,
                integration.name,
                "manual",
                detail="that key is already set — Sensei will not overwrite it",
                path=path,
                manual_snippet=integration.body(ep),
            )

    if dry_run:
        return Outcome(integration.id, integration.name, "applied", detail="dry run", path=path)

    backup = _backup(path, stamp)
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    block = f"{prefix}\n{BLOCK_BEGIN}\n{desired}{BLOCK_END}\n"
    _atomic_write(path, existing + block)
    _record(manifest, tool_id=integration.id, path=path, backup=backup, kind="block")
    return Outcome(integration.id, integration.name, "applied", path=path)


def known_ids() -> set[str]:
    return {i.id for i in (*REGISTRY, *BLOCK_REGISTRY)}


def apply_all(
    *,
    only: set[str] | None = None,
    include_undetected: bool = False,
    dry_run: bool = False,
    host: str | None = None,
    port: int | None = None,
    project: Path | None = None,
    automatic: bool = False,
) -> list[Outcome]:
    """Wire up every detected tool. Returns one Outcome per file considered.

    With ``project`` set, only tools that read per-repository configuration are
    touched, and only inside that directory. Detection is skipped in that mode:
    committing a `.cursor/mcp.json` for a teammate who has Cursor and you do not
    is a legitimate thing to want.

    ``automatic`` marks the call as coming from the background watcher (or an
    installer re-run) rather than from a person. The two must not behave the
    same: an automatic run respects an earlier disconnect and the global
    "don't connect automatically", while someone typing `setup-tools` is asking
    for exactly this right now and that supersedes whatever they decided last
    week.
    """
    ep = endpoints(host, port)
    manifest = _read_manifest()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results: list[Outcome] = []
    opted_out = declined()

    if automatic and not auto_connect_allowed():
        return results

    candidates: list[Integration | BlockIntegration] = [*REGISTRY, *BLOCK_REGISTRY]
    for integration in candidates:
        if only is not None and integration.id not in only:
            continue

        if automatic and integration.id in opted_out:
            results.append(
                Outcome(
                    integration.id,
                    integration.name,
                    "unchanged",
                    detail="disconnected by hand — run `sensei setup-tools` to reconnect",
                )
            )
            continue

        if project is not None:
            if not isinstance(integration, Integration):
                continue
            parts = [p for p in integration.all_parts() if p.project_path is not None]
            if not parts:
                continue
        elif not include_undetected and not integration.detect():
            results.append(
                Outcome(integration.id, integration.name, "not-found", detail="not installed")
            )
            continue

        try:
            if isinstance(integration, Integration):
                if project is not None:
                    for part in parts:
                        results.append(
                            _apply_part(
                                integration,
                                part,
                                part.project_path(project),  # type: ignore[misc]
                                ep,
                                manifest,
                                stamp,
                                dry_run=dry_run,
                            )
                        )
                else:
                    # One outcome per file, so a tool with several shows each
                    # location rather than one line that hides the rest.
                    for part in integration.all_parts():
                        for target in part.write_targets(force=include_undetected):
                            results.append(
                                _apply_part(
                                    integration, part, target, ep, manifest, stamp, dry_run=dry_run
                                )
                            )
            else:
                results.append(_apply_block(integration, ep, manifest, stamp, dry_run=dry_run))
        except OSError as exc:
            results.append(Outcome(integration.id, integration.name, "failed", detail=str(exc)))

    if not dry_run:
        if not automatic:
            # An explicit request is the newest statement of intent, so it
            # clears the earlier refusal for the tools it actually touched.
            touched = {r.tool_id for r in results if r.status in ("applied", "unchanged")}
            _set_declined(manifest, opted_out - touched)
        # Remember the port, so a later revert recognises this Sensei's URLs —
        # and only those — even after SENSEI_PORT has changed.
        written_port = _url_port(ep.anthropic)
        ports = manifest.get("ports") if isinstance(manifest.get("ports"), list) else []
        if written_port is not None and written_port not in ports:
            manifest["ports"] = [*ports, written_port]
        _write_manifest(manifest)
    return results


# ── Undo ────────────────────────────────────────────────────────────────────


def _lookup_part(tool_id: str, entry: dict[str, Any]) -> Part | None:
    integration = next((i for i in REGISTRY if i.id == tool_id), None)
    if integration is None:
        return None
    key = str(entry.get("part") or "main")
    return integration.part(key) or integration.part("main")


def undo_all(*, only: set[str] | None = None, dry_run: bool = False) -> list[Outcome]:
    """Reverse every edit this module recorded.

    A backup is restored only when the file still hashes to what Sensei wrote.
    If it does not, the user (or the tool itself) changed it afterwards and the
    honest thing is to remove Sensei's own keys surgically — or, when even that
    is ambiguous, to say so and change nothing.
    """
    manifest = _read_manifest()
    by_id: dict[str, Integration | BlockIntegration] = {
        i.id: i for i in (*REGISTRY, *BLOCK_REGISTRY)
    }
    results: list[Outcome] = []
    kept: list[dict[str, Any]] = []

    for entry in manifest["entries"]:
        tool_id = str(entry.get("tool_id", ""))
        if only is not None and tool_id not in only:
            kept.append(entry)
            continue

        known = by_id.get(tool_id)
        display = known.name if known else tool_id
        path = Path(str(entry.get("path", "")))

        if not path.exists():
            results.append(Outcome(tool_id, display, "unchanged", detail="file is gone"))
            continue

        # Wholesale restore only when the file is exactly as Sensei last left
        # it *and* nobody else ever wrote it in between Sensei's writes.
        # Anything else is a surgical removal of Sensei's own keys.
        untouched = entry.get("hash_after") == _sha256(path) and bool(entry.get("pristine", True))
        backup = Path(str(entry["backup"])) if entry.get("backup") else None
        created = bool(entry.get("created", backup is None))

        if dry_run:
            how = "restore backup" if untouched else "remove Sensei's keys in place"
            results.append(
                Outcome(tool_id, display, "applied", detail=f"dry run — {how}", path=path)
            )
            kept.append(entry)
            continue

        try:
            if untouched and backup is not None and backup.exists():
                shutil.copy2(backup, path)
                results.append(Outcome(tool_id, display, "applied", detail="restored", path=path))
            elif untouched and created:
                # There was no file before Sensei created one.
                path.unlink()
                results.append(Outcome(tool_id, display, "applied", detail="removed", path=path))
            elif entry.get("kind") == "block":
                text = path.read_text(encoding="utf-8")
                stripped = re.sub(
                    rf"\n?{re.escape(BLOCK_BEGIN)}.*?{re.escape(BLOCK_END)}\n?",
                    "",
                    text,
                    flags=re.DOTALL,
                )
                if stripped == text and tool_id == "codex":
                    # A 0.2 block whose markers the Codex app dropped on rewrite.
                    stripped = _codex_revert(text)
                if stripped == text:
                    results.append(
                        Outcome(tool_id, display, "manual", detail="block not found", path=path)
                    )
                    continue
                _atomic_write(path, stripped)
                results.append(
                    Outcome(tool_id, display, "applied", detail="block removed", path=path)
                )
            else:
                results.append(_undo_in_place(tool_id, display, entry, path, created, kept))
        except OSError as exc:
            results.append(Outcome(tool_id, display, "failed", detail=str(exc)))
            kept.append(entry)

    if not dry_run:
        manifest["entries"] = kept
        # Remember the refusal, not just the removal. The files are back to how
        # they were, but the background watcher still sees an installed tool
        # that is not wired, and that is indistinguishable from a fresh install
        # unless the decision is written down.
        _set_declined(manifest, declined() | {r.tool_id for r in results if r.status == "applied"})
        _write_manifest(manifest)
    return results


def _undo_in_place(
    tool_id: str,
    display: str,
    entry: dict[str, Any],
    path: Path,
    created: bool,
    kept: list[dict[str, Any]],
) -> Outcome:
    """Remove Sensei's keys from a file that changed since Sensei wrote it."""
    part = _lookup_part(tool_id, entry)
    if part is None:
        kept.append(entry)
        return Outcome(
            tool_id, display, "manual", detail="Sensei no longer knows this tool", path=path
        )

    if part.fmt == "text" or entry.get("kind") == "text":
        text = path.read_text(encoding="utf-8")
        stripped = part.revert(text)
        if stripped == text:
            return Outcome(tool_id, display, "unchanged", path=path)
        if not stripped.strip() and created:
            path.unlink()
            return Outcome(tool_id, display, "applied", detail="removed", path=path)
        _atomic_write(path, stripped)
        return Outcome(tool_id, display, "applied", detail="entries removed", path=path)

    doc = _load_json(path, list if part.fmt == "json-list" else dict)
    if doc is None:
        kept.append(entry)
        return Outcome(
            tool_id,
            display,
            "manual",
            detail="file changed since Sensei wrote it and cannot be parsed",
            path=path,
        )
    if not part.revert(doc):
        return Outcome(tool_id, display, "unchanged", path=path)
    if not doc and created:
        path.unlink()
        return Outcome(tool_id, display, "applied", detail="removed", path=path)
    _atomic_write(path, _dump_json(doc))
    return Outcome(tool_id, display, "applied", detail="keys removed", path=path)


# ── Status ──────────────────────────────────────────────────────────────────


def _part_state(part: Part, ep: Endpoints) -> bool | None:
    """True wired, False not, None when the part has nothing to say.

    Asked of the file, not of the manifest. The manifest records what Sensei
    wrote, which is a different question and gives the wrong answer twice: a
    config the user wired by hand reads as disconnected forever, and so does one
    Sensei wrote before the manifest was reset.

    Implemented by asking the part's own `apply` whether it would change
    anything, on a copy — the same code path that does the wiring, so the two
    cannot drift apart. A part that would not touch an empty document either
    (the MCP writers when the `mcp` extra is missing) cannot tell us anything.
    """
    if part.fmt == "text":
        probe = part.apply("", ep)
        if not probe:
            return None
        for target in part.targets():
            if not target.exists():
                continue
            text = target.read_text(encoding="utf-8")
            if part.apply(text, ep) == text:
                return True
        return False
    root: type = list if part.fmt == "json-list" else dict
    if not part.apply(root(), ep):
        return None
    for target in part.targets():
        if not target.exists():
            continue
        doc = _load_json(target, root)
        if doc is not None and not part.apply(copy.deepcopy(doc), ep):
            return True
    return False


def _is_wired(integration: Integration | BlockIntegration, ep: Endpoints) -> bool:
    """Does this tool's configuration already point at Sensei?"""
    try:
        if isinstance(integration, Integration):
            states = [_part_state(p, ep) for p in integration.all_parts() if p.counts]
            meaningful = [s for s in states if s is not None]
            return bool(meaningful) and all(meaningful)
        target = integration.path()
        return target.exists() and BLOCK_BEGIN in target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def status(
    host: str | None = None, port: int | None = None
) -> list[tuple[Integration | BlockIntegration, bool, bool]]:
    """(integration, installed, wired) for everything in both registries."""
    ep = endpoints(host, port)
    out: list[tuple[Integration | BlockIntegration, bool, bool]] = []
    for integration in (*REGISTRY, *BLOCK_REGISTRY):
        out.append((integration, integration.detect(), _is_wired(integration, ep)))
    return out


# ── "Needs restart" ─────────────────────────────────────────────────────────


def _etime_seconds(text: str) -> float | None:
    """`ps -o etime` → seconds. Format: [[dd-]hh:]mm:ss."""
    text = text.strip()
    days = 0
    if "-" in text:
        d, text = text.split("-", 1)
        if not d.isdigit():
            return None
        days = int(d)
    pieces = text.split(":")
    if not all(p.isdigit() for p in pieces) or not 2 <= len(pieces) <= 3:
        return None
    nums = [int(p) for p in pieces]
    while len(nums) < 3:
        nums.insert(0, 0)
    h, m, s = nums
    return float(days * 86400 + h * 3600 + m * 60 + s)


def _windows_processes() -> list[tuple[str, float]]:  # pragma: no cover — Windows only
    import ctypes
    from ctypes import wintypes

    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        *([ctypes.POINTER(wintypes.FILETIME)] * 4),
    )

    pids = (wintypes.DWORD * 8192)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(needed)):
        return []
    out: list[tuple[str, float]] = []
    for pid in pids[: needed.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                continue
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                continue
            ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            out.append((Path(buf.value).name.lower(), ticks / 1e7 - 11644473600))
        finally:
            kernel32.CloseHandle(handle)
    return out


def _posix_processes() -> list[tuple[str, float]]:
    try:
        result = subprocess.run(
            ["ps", "-A", "-o", "etime=,comm="],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    now = time.time()
    out: list[tuple[str, float]] = []
    for line in result.stdout.splitlines():
        bits = line.strip().split(None, 1)
        if len(bits) != 2:
            continue
        elapsed = _etime_seconds(bits[0])
        if elapsed is not None:
            out.append((Path(bits[1]).name.lower(), now - elapsed))
    return out


def running_processes() -> list[tuple[str, float]]:
    """(image name, start time) for every process we may look at. Best effort."""
    try:
        return _windows_processes() if sys.platform == "win32" else _posix_processes()
    except Exception:  # pragma: no cover — a diagnostic must not raise
        return []


def needs_restart(
    integration: Integration | BlockIntegration,
    manifest: dict[str, Any],
    processes: list[tuple[str, float]],
) -> bool:
    """Is a process of this tool running that started before Sensei's last write?"""
    if not integration.processes:
        return False
    written = [
        float(e.get("written_at") or 0)
        for e in manifest.get("entries", [])
        if e.get("tool_id") == integration.id
    ]
    if not written:
        return False
    last = max(written)
    names = {p.lower() for p in integration.processes}
    return any(name in names and started < last for name, started in processes)


def describe(host: str | None = None, port: int | None = None) -> list[dict[str, Any]]:
    """Everything a status table needs, one dict per tool."""
    ep = endpoints(host, port)
    manifest = _read_manifest()
    opted_out = declined()
    procs = running_processes()
    rows: list[dict[str, Any]] = []
    for integration in (*REGISTRY, *BLOCK_REGISTRY):
        installed = integration.detect()
        wired = _is_wired(integration, ep)
        routed = False
        if integration.id == "claude-code":
            doc = _load_json(integration.path())
            routed = isinstance(doc, dict) and claude_code_routed(doc)
        rows.append(
            {
                "id": integration.id,
                "name": integration.name,
                "installed": installed,
                "connected": wired,
                "declined": integration.id in opted_out,
                "support": integration.support,
                "why": integration.why,
                "note": integration.note,
                "verified": integration.verified,
                "options": list(integration.options),
                "enabled_options": [o for o in integration.options if ep.wants(integration.id, o)]
                or (["route"] if routed else []),
                "needs_restart": wired and needs_restart(integration, manifest, procs),
                "state": _state(installed, wired, integration.id in opted_out),
            }
        )
    for item in UNSUPPORTED:
        detected = False
        with contextlib.suppress(Exception):
            detected = bool(item.detect())
        rows.append(
            {
                "id": item.id,
                "name": item.name,
                "installed": detected,
                "connected": False,
                "declined": False,
                "support": "none",
                "why": item.why,
                "note": item.docs,
                "verified": True,
                "options": [],
                "enabled_options": [],
                "needs_restart": False,
                "state": "unsupported",
            }
        )
    return rows


def _state(installed: bool, wired: bool, declined_: bool) -> str:
    if wired:
        return "connected"
    if declined_:
        return "declined"
    return "not-connected" if installed else "not-installed"


# ── One switch ──────────────────────────────────────────────────────────────


def connect_everything(*, dry_run: bool = False) -> list[Outcome]:
    """ "Connect everything": every detected tool, now and as they appear."""
    if not dry_run:
        set_auto_connect(True)
        manifest = _read_manifest()
        _set_declined(manifest, set())
        _write_manifest(manifest)
    return apply_all(dry_run=dry_run)


def disconnect_everything(*, dry_run: bool = False) -> list[Outcome]:
    """ "Disconnect everything": undo every edit and stop connecting new tools."""
    outcomes = undo_all(dry_run=dry_run)
    if not dry_run:
        set_auto_connect(False)
    return outcomes

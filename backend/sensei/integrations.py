"""Wiring Sensei into the tools that keep their configuration on disk.

`sensei wrap <tool>` covers the tools you launch from a terminal: it sets a base
URL for exactly one process and forgets it again. That does not help a tool you
start by clicking an icon — VS Code, Cursor, Windsurf — or a CLI that reads a
config file rather than the environment. Those need a file edited, and editing
them by hand means knowing which of nine formats a given tool uses and where it
hides the file on three operating systems.

This module knows. It detects what is installed, writes the smallest change that
routes the tool through Sensei, and records precisely what it did so that
``sensei setup-tools --undo`` can put it back.

Three rules, because a program that edits other programs' config files has to be
more careful than one that doesn't:

1. **Never write blind.** Every file is backed up first, under
   ``~/.sensei/backups/<timestamp>/``, and the manifest records where.
2. **Never clobber a later edit.** Undo restores a backup only if the file still
   hashes to what Sensei wrote. If you edited it afterwards, undo says so and
   leaves it alone.
3. **Never guess at a format.** JSON files are parsed, modified and re-serialised.
   TOML and YAML files — which have no writer in the standard library, and which
   this project will not take a dependency for — get a marker-delimited block
   appended, and only when the keys involved are not already set. Anything that
   cannot be done safely is reported as a manual step with the exact snippet,
   rather than attempted.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
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


# ── The endpoints a tool is pointed at ──────────────────────────────────────


@dataclass(frozen=True)
class Endpoints:
    """The three ways a tool can talk to Sensei."""

    anthropic: str  # http://127.0.0.1:7000
    openai: str  # http://127.0.0.1:7000/v1
    mcp_command: str  # "sensei"
    mcp_args: tuple[str, ...] = ("mcp",)
    # Whether `sensei mcp` can actually start. False means the optional `mcp`
    # extra is missing, and writing a server entry anyway produces exactly one
    # symptom in every editor that reads it: "Server disconnected", with no
    # hint that a Python package is the reason.
    mcp_ready: bool = True


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
    #   on PATH        the console script, which is stable across venv changes
    #   otherwise      this interpreter plus the module, which always resolves
    if getattr(sys, "frozen", False):
        command, args = sys.executable, ("mcp",)
    elif shutil.which("sensei"):
        command, args = "sensei", ("mcp",)
    else:
        command, args = sys.executable, ("-m", "sensei.cli", "mcp")
    return Endpoints(
        anthropic=base,
        openai=f"{base}/v1",
        mcp_command=command,
        mcp_args=args,
        mcp_ready=mcp_available(),
    )


def mcp_available() -> bool:
    """Can this build actually serve MCP?

    `sensei mcp` needs the optional `mcp` extra. A PyInstaller binary built
    without it starts, reports its version, wires up base URLs — and then dies
    with ModuleNotFoundError the moment an editor spawns it. Checked here so a
    server entry is never written for a command that cannot run.
    """
    return importlib.util.find_spec("mcp") is not None


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
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".sensei-tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _backup(path: Path, stamp: str) -> Path | None:
    """Copy a file into the run's backup directory. Returns where it went."""
    if not path.exists():
        return None
    dest_dir = BACKUP_ROOT / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Flatten the absolute path into a filename so two tools with the same
    # basename (three of them use `settings.json`) cannot overwrite each other.
    flat = re.sub(r"[^A-Za-z0-9._-]", "_", str(path))
    dest = dest_dir / flat
    shutil.copy2(path, dest)
    return dest


def _load_json(path: Path) -> dict[str, Any] | None:
    """Parse a JSON config, or return None if it is absent or not strict JSON.

    Several editors accept comments in their JSON. Sensei will not rewrite a
    file it cannot round-trip, because doing so silently deletes the user's
    comments — so a parse failure means "hands off", not "start fresh".
    """
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _dump_json(doc: dict[str, Any]) -> str:
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


def _deep_unset(doc: dict[str, Any], keys: tuple[str, ...]) -> bool:
    cursor: Any = doc
    for key in keys[:-1]:
        if not isinstance(cursor, dict) or key not in cursor:
            return False
        cursor = cursor[key]
    if not isinstance(cursor, dict) or keys[-1] not in cursor:
        return False
    del cursor[keys[-1]]
    return True


# ── The registry ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Integration:
    """One tool Sensei knows how to wire up.

    ``detect`` is deliberately generous: a tool counts as present if either its
    binary is on PATH or its config directory exists. Someone who uninstalled
    the CLI but kept the directory still wants the setting to be correct when
    they reinstall, and writing a base URL for a tool that is not there costs
    nothing and breaks nothing.
    """

    id: str
    name: str
    path: Callable[[], Path]
    apply: Callable[[dict[str, Any], Endpoints], bool]
    revert: Callable[[dict[str, Any]], bool]
    binaries: tuple[str, ...] = ()
    extra_dirs: tuple[Callable[[], Path], ...] = ()
    # Where the tool used to keep its configuration. Editors move these: Devin
    # relocated Windsurf's from `~/.codeium/windsurf/` to `%APPDATA%/devin/` and
    # now prompts to copy it across. Writing only to the current location leaves
    # an existing install unwired until the user notices; writing only to the
    # old one wires a directory the tool has stopped reading.
    legacy_paths: tuple[Callable[[], Path], ...] = ()
    # Where this tool reads per-repository configuration, if it does. Set means
    # `--project` can scope the change to one checkout instead of the machine —
    # which is what someone wants when only some of their work should route
    # through a local gateway.
    project_path: Callable[[Path], Path] | None = None
    note: str = ""
    # False when the format is documented but Sensei has not been able to verify
    # it end to end against the real tool. Surfaced in the output, because a
    # confident claim that turns out to be wrong is worse than a hedged one.
    verified: bool = True

    def targets(self) -> list[Path]:
        """Every config file this tool might be reading, current one first.

        All of them get written, not just the first. A tool mid-migration reads
        one and will read the other after its next update, and there is no way
        from here to know which side of that the user is on — Devin asks about
        it in a dialog box. Writing both costs a few hundred bytes and removes
        the question.
        """
        paths = [self.path(), *(p() for p in self.legacy_paths)]
        seen: list[Path] = []
        for path in paths:
            if path not in seen:
                seen.append(path)
        return seen

    def detect(self) -> bool:
        if any(shutil.which(b) for b in self.binaries):
            return True
        for target in self.targets():
            if target.exists() or _is_tool_dir(target.parent):
                return True
        return any(d().exists() for d in self.extra_dirs)


def _is_tool_dir(path: Path) -> bool:
    """Does this directory exist *and* belong to a specific tool?

    Detection treats "the config directory is there" as evidence the tool is
    installed. That inference only holds for a directory the tool created:
    `~/.aider.conf.yml` lives directly in the home directory, and the home
    directory always exists, so without this check Aider — and every other tool
    with a dotfile rather than a dotdir — reports as installed on every machine.
    """
    try:
        return path.is_dir() and path.resolve() not in (Path.home().resolve(), Path(path.anchor))
    except OSError:  # pragma: no cover — unreadable path
        return False


def _vscode_global_storage() -> Path:
    """VS Code's per-extension storage, where Cline keeps its MCP settings."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Code" / "User" / "globalStorage"


def _xdg_config() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _devin_config() -> Path:
    """Devin's current MCP config, which used to live under `.codeium`."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = _xdg_config()
    return base / "devin" / "mcp_config.json"


def _claude_desktop_config() -> Path:
    """Claude Desktop's config, which is in a different place on all three."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = _xdg_config()
    return base / "Claude" / "claude_desktop_config.json"


def _mcp_entry(ep: Endpoints) -> dict[str, Any]:
    return {"command": ep.mcp_command, "args": list(ep.mcp_args)}


def _mcp_apply(root: tuple[str, ...]) -> Callable[[dict[str, Any], Endpoints], bool]:
    def apply(doc: dict[str, Any], ep: Endpoints) -> bool:
        if not ep.mcp_ready:
            # Better to write nothing than a server the editor will fail to
            # start on every launch.
            return False
        return _deep_set(doc, (*root, "sensei"), _mcp_entry(ep))

    return apply


def _mcp_revert(root: tuple[str, ...]) -> Callable[[dict[str, Any]], bool]:
    def revert(doc: dict[str, Any]) -> bool:
        return _deep_unset(doc, (*root, "sensei"))

    return revert


def _claude_code_apply(doc: dict[str, Any], ep: Endpoints) -> bool:
    # Claude Code reads ANTHROPIC_BASE_URL from the `env` block of its settings
    # file and injects it into every session. The API key is deliberately left
    # alone: Sensei forwards the user's own key, it does not replace it.
    changed = _deep_set(doc, ("env", "ANTHROPIC_BASE_URL"), ep.anthropic)
    if not ep.mcp_ready:
        # The routing half is what matters for Claude Code and it works
        # regardless; the tools are a bonus this build cannot provide.
        return changed
    return _deep_set(doc, ("mcpServers", "sensei"), _mcp_entry(ep)) or changed


def _claude_code_revert(doc: dict[str, Any]) -> bool:
    changed = _deep_unset(doc, ("env", "ANTHROPIC_BASE_URL"))
    return _deep_unset(doc, ("mcpServers", "sensei")) or changed


def _continue_apply(doc: dict[str, Any], ep: Endpoints) -> bool:
    """Continue keeps a list of models, each with its own apiBase.

    Rather than adding a model — which would mean choosing one on the user's
    behalf — this rewrites the apiBase of every OpenAI/Anthropic model already
    configured. That is the change the user actually asked for: same models,
    routed through Sensei.
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
        if isinstance(model, dict) and "apiBase" in model:
            base = str(model["apiBase"])
            # Only strip the ones pointing at us. A user's own proxy stays.
            if "127.0.0.1" in base or "localhost" in base:
                del model["apiBase"]
                changed = True
    return changed


REGISTRY: tuple[Integration, ...] = (
    Integration(
        id="claude-code",
        name="Claude Code",
        binaries=("claude",),
        path=lambda: Path.home() / ".claude" / "settings.json",
        project_path=lambda root: root / ".claude" / "settings.json",
        apply=_claude_code_apply,
        revert=_claude_code_revert,
        note="Routes sessions through the gateway and registers the MCP tools.",
    ),
    Integration(
        id="claude-desktop",
        name="Claude Desktop",
        path=_claude_desktop_config,
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        note="MCP server. The desktop app talks to Anthropic directly, so only "
        "the compression tools are exposed — its traffic does not route here.",
    ),
    Integration(
        id="cursor",
        name="Cursor",
        path=lambda: Path.home() / ".cursor" / "mcp.json",
        project_path=lambda root: root / ".cursor" / "mcp.json",
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        note="MCP server. The chat model's base URL lives in Cursor's own "
        "settings UI and cannot be set from a file.",
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
        verified=False,
    ),
    Integration(
        id="roo",
        name="Roo Code (VS Code)",
        path=lambda: (
            _vscode_global_storage()
            / "rooveterinaryinc.roo-cline"
            / "settings"
            / "mcp_settings.json"
        ),
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        verified=False,
    ),
    Integration(
        id="kilo",
        name="Kilo Code (VS Code)",
        path=lambda: (
            _vscode_global_storage() / "kilocode.kilo-code" / "settings" / "mcp_settings.json"
        ),
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        verified=False,
    ),
    Integration(
        id="windsurf",
        name="Windsurf / Devin",
        binaries=("windsurf", "devin"),
        # Devin moved this out of the Codeium directory. Both are written: an
        # install that has not migrated yet still reads the old one, and the
        # app itself offers to copy the file across when it notices.
        path=_devin_config,
        legacy_paths=(lambda: Path.home() / ".codeium" / "windsurf" / "mcp_config.json",),
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        note="MCP server. Written to both the current and the former config "
        "location, because Devin migrates it on its own schedule.",
    ),
    Integration(
        id="cline",
        name="Cline (VS Code)",
        path=lambda: (
            _vscode_global_storage()
            / "saoudrizwan.claude-dev"
            / "settings"
            / "cline_mcp_settings.json"
        ),
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        note="MCP server.",
    ),
    Integration(
        id="continue",
        name="Continue (VS Code / JetBrains)",
        binaries=("continue",),
        path=lambda: Path.home() / ".continue" / "config.json",
        apply=_continue_apply,
        revert=_continue_revert,
        note="Repoints the apiBase of every OpenAI- and Anthropic-provider model "
        "you already have configured.",
    ),
    Integration(
        id="gemini-cli",
        name="Gemini CLI",
        binaries=("gemini",),
        path=lambda: Path.home() / ".gemini" / "settings.json",
        apply=_mcp_apply(("mcpServers",)),
        revert=_mcp_revert(("mcpServers",)),
        note="MCP server. Gemini traffic itself does not go through the gateway.",
        verified=False,
    ),
    Integration(
        id="opencode",
        name="opencode",
        binaries=("opencode",),
        path=lambda: _xdg_config() / "opencode" / "opencode.json",
        apply=_mcp_apply(("mcp",)),
        revert=_mcp_revert(("mcp",)),
        verified=False,
    ),
)


# ── Formats with no standard-library writer ─────────────────────────────────


@dataclass(frozen=True)
class BlockIntegration:
    """A tool whose config Sensei appends to rather than parses.

    TOML and YAML have no writer in the standard library, and this project keeps
    its dependency list short on purpose. Appending a marker-delimited block is
    the honest middle ground: it is valid in both formats as long as the keys
    are not already set, it is trivially reversible by deleting the block, and
    when the keys *are* already set the tool reports a manual step instead of
    guessing which value the user meant to keep.
    """

    id: str
    name: str
    path: Callable[[], Path]
    body: Callable[[Endpoints], str]
    # If any of these match the existing file, appending would create a
    # duplicate key — which TOML rejects outright and YAML resolves silently in
    # the wrong direction.
    conflicts: tuple[str, ...]
    binaries: tuple[str, ...] = ()
    note: str = ""
    verified: bool = False

    def detect(self) -> bool:
        if any(shutil.which(b) for b in self.binaries):
            return True
        target = self.path()
        return target.exists() or _is_tool_dir(target.parent)


BLOCK_REGISTRY: tuple[BlockIntegration, ...] = (
    BlockIntegration(
        id="codex",
        name="Codex CLI",
        binaries=("codex",),
        path=lambda: Path.home() / ".codex" / "config.toml",
        body=lambda ep: (
            "[model_providers.sensei]\n"
            'name = "Sensei"\n'
            f'base_url = "{ep.openai}"\n'
            'wire_api = "chat"\n'
            'env_key = "OPENAI_API_KEY"\n'
        ),
        conflicts=(r"^\s*\[model_providers\.sensei\]",),
        note="Adds a `sensei` provider. Select it with `codex --config "
        'model_provider=sensei`, or set `model_provider = "sensei"` yourself.',
    ),
    BlockIntegration(
        id="aider",
        name="Aider",
        binaries=("aider",),
        path=lambda: Path.home() / ".aider.conf.yml",
        body=lambda ep: f"openai-api-base: {ep.openai}\n",
        conflicts=(r"^\s*openai-api-base\s*:",),
        note="Aider reads OPENAI_API_BASE, not OPENAI_BASE_URL — this is the "
        "config-file equivalent.",
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
    removed it, forever, and the only way out would be to turn the watcher off.
    An undo has to mean something after the process it ran in has exited.
    """
    raw = _read_manifest().get("declined", [])
    return {str(x) for x in raw} if isinstance(raw, list) else set()


def _set_declined(manifest: dict[str, Any], ids: set[str]) -> None:
    manifest["declined"] = sorted(ids)


def _record(
    manifest: dict[str, Any],
    *,
    tool_id: str,
    path: Path,
    backup: Path | None,
    kind: str,
) -> None:
    """Remember one edit, replacing any earlier record for the same file.

    Keyed by (tool_id, path) rather than tool_id alone: the same tool can be
    wired machine-wide and again inside a checkout, and undoing one must not
    make Sensei forget it ever touched the other.
    """
    manifest["entries"] = [
        e
        for e in manifest["entries"]
        if not (e.get("tool_id") == tool_id and e.get("path") == str(path))
    ]
    manifest["entries"].append(
        {
            "tool_id": tool_id,
            "kind": kind,
            "path": str(path),
            "backup": str(backup) if backup else None,
            "hash_after": _sha256(path) if path.exists() else None,
            "written_at": time.time(),
        }
    )


# ── Apply ───────────────────────────────────────────────────────────────────


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
    path = path or (integration.project_path(project) if project else integration.path())
    doc = _load_json(path)
    if doc is None:
        return Outcome(
            integration.id,
            integration.name,
            "manual",
            detail="config file is not strict JSON (comments?) — not rewriting it",
            path=path,
            manual_snippet=_dump_json({"mcpServers": {"sensei": _mcp_entry(ep)}}),
        )

    before = json.dumps(doc, sort_keys=True)
    if not integration.apply(doc, ep):
        return Outcome(integration.id, integration.name, "unchanged", path=path)
    if json.dumps(doc, sort_keys=True) == before:  # pragma: no cover — belt and braces
        return Outcome(integration.id, integration.name, "unchanged", path=path)

    if dry_run:
        return Outcome(integration.id, integration.name, "applied", detail="dry run", path=path)

    backup = _backup(path, stamp)
    _atomic_write(path, _dump_json(doc))
    # Keyed by id *and* path so a project-scoped edit does not evict the record
    # of the machine-wide one — undoing one must not silently forget the other.
    _record(manifest, tool_id=integration.id, path=path, backup=backup, kind="json")
    return Outcome(integration.id, integration.name, "applied", path=path)


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

    if BLOCK_BEGIN in existing:
        return Outcome(integration.id, integration.name, "unchanged", path=path)

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
    block = f"{prefix}\n{BLOCK_BEGIN}\n{integration.body(ep)}{BLOCK_END}\n"
    _atomic_write(path, existing + block)
    _record(manifest, tool_id=integration.id, path=path, backup=backup, kind="block")
    return Outcome(integration.id, integration.name, "applied", path=path)


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
    """Wire up every detected tool. Returns one Outcome per tool considered.

    With ``project`` set, only tools that read per-repository configuration are
    touched, and only inside that directory. Detection is skipped in that mode:
    committing a `.cursor/mcp.json` for a teammate who has Cursor and you do not
    is a legitimate thing to want.

    ``automatic`` marks the call as coming from the background watcher rather
    than from a person. The two must not behave the same: a watcher has to
    respect an earlier disconnect, while someone typing `setup-tools` is asking
    for exactly this tool right now and that supersedes whatever they decided
    last week.
    """
    ep = endpoints(host, port)
    manifest = _read_manifest()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results: list[Outcome] = []
    opted_out = declined()

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
            if not isinstance(integration, Integration) or integration.project_path is None:
                continue
        elif not include_undetected and not integration.detect():
            results.append(
                Outcome(integration.id, integration.name, "not-found", detail="not installed")
            )
            continue

        try:
            if isinstance(integration, Integration):
                if project is not None:
                    results.append(
                        _apply_json(
                            integration, ep, manifest, stamp, dry_run=dry_run, project=project
                        )
                    )
                else:
                    # One outcome per file, so a tool mid-migration shows both
                    # locations rather than one line that hides the second.
                    for target in integration.targets():
                        results.append(
                            _apply_json(
                                integration, ep, manifest, stamp, dry_run=dry_run, path=target
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
        _write_manifest(manifest)
    return results


# ── Undo ────────────────────────────────────────────────────────────────────


def undo_all(*, only: set[str] | None = None, dry_run: bool = False) -> list[Outcome]:
    """Reverse every edit this module recorded.

    A backup is restored only when the file still hashes to what Sensei wrote.
    If it does not, the user changed it afterwards and the honest thing is to
    remove Sensei's own keys surgically — or, when even that is ambiguous, to
    say so and change nothing.
    """
    manifest = _read_manifest()
    by_id = {i.id: i for i in REGISTRY}
    block_by_id = {i.id: i for i in BLOCK_REGISTRY}
    results: list[Outcome] = []
    kept: list[dict[str, Any]] = []

    for entry in manifest["entries"]:
        tool_id = str(entry.get("tool_id", ""))
        if only is not None and tool_id not in only:
            kept.append(entry)
            continue

        name = by_id.get(tool_id) or block_by_id.get(tool_id)
        display = name.name if name else tool_id
        path = Path(str(entry.get("path", "")))

        if not path.exists():
            results.append(Outcome(tool_id, display, "unchanged", detail="file is gone"))
            continue

        untouched = entry.get("hash_after") == _sha256(path)

        if dry_run:
            how = "restore backup" if untouched else "remove Sensei's keys in place"
            results.append(
                Outcome(tool_id, display, "applied", detail=f"dry run — {how}", path=path)
            )
            kept.append(entry)
            continue

        try:
            if untouched and entry.get("backup") and Path(str(entry["backup"])).exists():
                shutil.copy2(Path(str(entry["backup"])), path)
                results.append(Outcome(tool_id, display, "applied", detail="restored", path=path))
            elif untouched and not entry.get("backup"):
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
                integration = by_id.get(tool_id)
                doc = _load_json(path)
                if integration is None or doc is None:
                    results.append(
                        Outcome(
                            tool_id,
                            display,
                            "manual",
                            detail="file changed since Sensei wrote it and cannot be parsed",
                            path=path,
                        )
                    )
                    kept.append(entry)
                    continue
                if integration.revert(doc):
                    _atomic_write(path, _dump_json(doc))
                    results.append(
                        Outcome(tool_id, display, "applied", detail="keys removed", path=path)
                    )
                else:
                    results.append(Outcome(tool_id, display, "unchanged", path=path))
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


def status() -> list[tuple[Integration | BlockIntegration, bool, bool]]:
    """(integration, installed, wired) for everything in both registries."""
    manifest = _read_manifest()
    wired = {str(e.get("tool_id")) for e in manifest["entries"]}
    out: list[tuple[Integration | BlockIntegration, bool, bool]] = []
    for integration in (*REGISTRY, *BLOCK_REGISTRY):
        out.append((integration, integration.detect(), integration.id in wired))
    return out

"""Tests for the tool-wiring engine.

This module edits configuration files belonging to other programs. The failure
mode that matters is not "the setting was not written" — the user notices that
immediately — but "something else in the file was lost", which they notice weeks
later when a tool stops working. Most of what follows is about that.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from sensei import integrations
from sensei.integrations import Endpoints, Integration


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point Sensei's bookkeeping at a temporary directory.

    `mcp_available` is pinned true because most of these assert that an MCP
    server entry gets written, and whether it does depends on the optional
    `mcp` extra being installed. Left to the environment, the suite passes on a
    developer machine with the extra and fails in CI without it — which is
    exactly what happened. The one place that behaviour is under test pins it
    explicitly instead.
    """
    home = tmp_path / "sensei-home"
    monkeypatch.setattr(integrations, "SENSEI_HOME", home)
    monkeypatch.setattr(integrations, "MANIFEST_PATH", home / "integrations.json")
    monkeypatch.setattr(integrations, "BACKUP_ROOT", home / "backups")
    monkeypatch.setattr(integrations, "mcp_available", lambda: True)
    return tmp_path


EP = Endpoints(
    anthropic="http://127.0.0.1:7000",
    openai="http://127.0.0.1:7000/v1",
    mcp_command="sensei",
    mcp_args=("mcp",),
)


def _json_integration(path: Path) -> Integration:
    return Integration(
        id="fake",
        name="Fake Tool",
        path=lambda: path,
        apply=integrations._mcp_apply(("mcpServers",)),
        revert=integrations._mcp_revert(("mcpServers",)),
    )


def _install(monkeypatch: pytest.MonkeyPatch, *entries: Integration) -> None:
    monkeypatch.setattr(integrations, "REGISTRY", tuple(entries))
    monkeypatch.setattr(integrations, "BLOCK_REGISTRY", ())


# ── JSON tools ──────────────────────────────────────────────────────────────


def test_existing_keys_survive(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The user's own settings must come back out byte-for-byte."""
    cfg = sandbox / "tool" / "config.json"
    cfg.parent.mkdir(parents=True)
    original = {
        "theme": "dark",
        "mcpServers": {"other": {"command": "other-server", "args": ["--flag"]}},
        "nested": {"deeply": {"kept": True}},
    }
    cfg.write_text(json.dumps(original), encoding="utf-8")

    _install(monkeypatch, _json_integration(cfg))
    outcomes = integrations.apply_all()

    assert [o.status for o in outcomes] == ["applied"]
    result = json.loads(cfg.read_text(encoding="utf-8"))
    assert result["theme"] == "dark"
    assert result["nested"] == {"deeply": {"kept": True}}
    assert result["mcpServers"]["other"] == {"command": "other-server", "args": ["--flag"]}
    # The command is whichever of `sensei` / `python -m` actually resolves here,
    # so assert the shape rather than the literal.
    assert result["mcpServers"]["sensei"]["command"]
    assert "mcp" in result["mcpServers"]["sensei"]["args"]


def test_applying_twice_changes_nothing(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = sandbox / "tool" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{}", encoding="utf-8")
    _install(monkeypatch, _json_integration(cfg))

    assert integrations.apply_all()[0].status == "applied"
    first = cfg.read_text(encoding="utf-8")
    assert integrations.apply_all()[0].status == "unchanged"
    assert cfg.read_text(encoding="utf-8") == first


def test_undo_restores_the_original_file(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = sandbox / "tool" / "config.json"
    cfg.parent.mkdir(parents=True)
    before = json.dumps({"theme": "dark"}, indent=2) + "\n"
    cfg.write_text(before, encoding="utf-8")
    _install(monkeypatch, _json_integration(cfg))

    integrations.apply_all()
    assert "sensei" in cfg.read_text(encoding="utf-8")

    outcomes = integrations.undo_all()
    assert [o.status for o in outcomes] == ["applied"]
    assert cfg.read_text(encoding="utf-8") == before


def test_undo_deletes_a_file_sensei_created(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = sandbox / "tool" / "config.json"
    cfg.parent.mkdir(parents=True)  # the tool is installed; it just has no config yet
    _install(monkeypatch, _json_integration(cfg))

    integrations.apply_all()
    assert cfg.exists()

    integrations.undo_all()
    assert not cfg.exists()


def test_undo_after_a_user_edit_removes_only_senseis_keys(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interesting case: the file changed after Sensei wrote it.

    Restoring the backup here would silently throw away whatever the user did
    in between, so undo has to fall back to surgical removal.
    """
    cfg = sandbox / "tool" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{}", encoding="utf-8")
    _install(monkeypatch, _json_integration(cfg))
    integrations.apply_all()

    doc = json.loads(cfg.read_text(encoding="utf-8"))
    doc["addedLater"] = "must survive"
    doc["mcpServers"]["alsoLater"] = {"command": "x"}
    cfg.write_text(json.dumps(doc), encoding="utf-8")

    integrations.undo_all()

    result = json.loads(cfg.read_text(encoding="utf-8"))
    assert result["addedLater"] == "must survive"
    assert result["mcpServers"]["alsoLater"] == {"command": "x"}
    assert "sensei" not in result["mcpServers"]


def test_json_with_comments_is_left_alone(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Several editors accept JSONC. Rewriting one deletes the user's comments."""
    cfg = sandbox / "tool" / "config.json"
    cfg.parent.mkdir(parents=True)
    text = '{\n  // why this is set\n  "theme": "dark"\n}\n'
    cfg.write_text(text, encoding="utf-8")
    _install(monkeypatch, _json_integration(cfg))

    outcome = integrations.apply_all()[0]
    assert outcome.status == "manual"
    assert outcome.manual_snippet
    assert cfg.read_text(encoding="utf-8") == text


def test_dry_run_writes_nothing(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = sandbox / "tool" / "config.json"
    cfg.parent.mkdir(parents=True)
    _install(monkeypatch, _json_integration(cfg))

    outcome = integrations.apply_all(dry_run=True)[0]
    assert outcome.status == "applied"
    assert not cfg.exists()
    assert not integrations.MANIFEST_PATH.exists()


# ── Appended-block tools ────────────────────────────────────────────────────


def _block_integration(path: Path) -> integrations.BlockIntegration:
    return integrations.BlockIntegration(
        id="fake-block",
        name="Fake Block Tool",
        path=lambda: path,
        body=lambda ep: f'base_url = "{ep.openai}"\n',
        conflicts=(r"^\s*base_url\s*=",),
    )


def _install_block(monkeypatch: pytest.MonkeyPatch, entry: integrations.BlockIntegration) -> None:
    monkeypatch.setattr(integrations, "REGISTRY", ())
    monkeypatch.setattr(integrations, "BLOCK_REGISTRY", (entry,))


def test_block_is_appended_and_removed_cleanly(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = sandbox / "tool" / "config.toml"
    cfg.parent.mkdir(parents=True)
    before = 'model = "gpt-4o"\n'
    cfg.write_text(before, encoding="utf-8")
    _install_block(monkeypatch, _block_integration(cfg))

    integrations.apply_all()
    after = cfg.read_text(encoding="utf-8")
    assert after.startswith(before)
    assert integrations.BLOCK_BEGIN in after

    integrations.undo_all()
    assert cfg.read_text(encoding="utf-8") == before


def test_block_is_not_appended_twice(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = sandbox / "tool" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("", encoding="utf-8")
    _install_block(monkeypatch, _block_integration(cfg))

    integrations.apply_all()
    once = cfg.read_text(encoding="utf-8")
    assert integrations.apply_all()[0].status == "unchanged"
    assert cfg.read_text(encoding="utf-8") == once


def test_conflicting_key_becomes_a_manual_step(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Appending a key TOML already has is a parse error, not a merge."""
    cfg = sandbox / "tool" / "config.toml"
    cfg.parent.mkdir(parents=True)
    before = 'base_url = "https://my-own-proxy.example"\n'
    cfg.write_text(before, encoding="utf-8")
    _install_block(monkeypatch, _block_integration(cfg))

    outcome = integrations.apply_all()[0]
    assert outcome.status == "manual"
    assert cfg.read_text(encoding="utf-8") == before


# ── Endpoints ───────────────────────────────────────────────────────────────


def test_bind_address_maps_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """0.0.0.0 is where the server listens, not somewhere a client can connect."""
    monkeypatch.setattr(integrations.settings, "host", "0.0.0.0")
    monkeypatch.setattr(integrations.settings, "port", 7000)
    assert integrations.endpoints().anthropic == "http://127.0.0.1:7000"


def test_a_frozen_binary_spawns_itself_not_a_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """PyInstaller's sys.executable is the bundle, which cannot run `-m`.

    Getting this wrong writes `sensei.exe -m sensei.cli mcp` into the user's
    editor configuration, and it fails at spawn time with an error that points
    at their editor rather than at us. Found by running an actual built binary,
    which is the only way it is visible.
    """
    monkeypatch.setattr(integrations.sys, "frozen", True, raising=False)
    monkeypatch.setattr(integrations.sys, "executable", "/opt/sensei/sensei", raising=False)

    ep = integrations.endpoints()
    assert ep.mcp_command == "/opt/sensei/sensei"
    assert ep.mcp_args == ("mcp",)


@pytest.mark.skipif(
    not integrations.mcp_available(),
    reason="a build without the extra deliberately writes no mcp block",
)
def test_codex_gets_mcp_tools_that_work_without_an_api_key() -> None:
    """Codex signed in with ChatGPT has OAuth tokens and a null OPENAI_API_KEY.

    The provider block Sensei writes declares `env_key = "OPENAI_API_KEY"`, so
    selecting it on a subscription account swaps a working login for a missing
    environment variable. The MCP block needs no credential at all, which makes
    it the part that actually helps most users — checked on a real machine,
    where `auth.json` held exactly that shape.
    """
    codex = next(i for i in integrations.BLOCK_REGISTRY if i.id == "codex")
    body = codex.body(integrations.endpoints())

    assert "[mcp_servers.sensei]" in body
    assert "[model_providers.sensei]" in body


def test_codex_gets_no_mcp_block_when_mcp_cannot_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A build without the extra would point Codex at a command that exits
    immediately — the same silent failure as pointing it at a missing file."""
    monkeypatch.setattr(integrations, "mcp_available", lambda: False)
    codex = next(i for i in integrations.BLOCK_REGISTRY if i.id == "codex")

    assert "[mcp_servers.sensei]" not in codex.body(integrations.endpoints())


def test_the_tray_points_tools_at_the_console_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP is JSON-RPC over stdio, and `senseiw.exe` is built without a console
    precisely so it has none.

    The tray runs *as* senseiw.exe, so writing `sys.executable` pointed every
    tool at the one binary whose purpose is having nowhere to write. Caught by
    installing the real thing and reading the config it produced: Zed was auto-
    connected to `senseiw.exe mcp`.

    It survives a client that hands over real pipes, which is what makes it
    worth a test — the failure only shows up on the client that does not.
    """
    (tmp_path / "sensei.exe").write_text("", encoding="utf-8")
    windowed = tmp_path / "senseiw.exe"
    windowed.write_text("", encoding="utf-8")
    monkeypatch.setattr(integrations.sys, "frozen", True, raising=False)
    monkeypatch.setattr(integrations.sys, "executable", str(windowed), raising=False)

    assert integrations.endpoints().mcp_command == str(tmp_path / "sensei.exe")


def test_a_console_only_bundle_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No sibling to fall back to means the name stays as it is, rather than
    becoming a path to a file that does not exist."""
    lone = tmp_path / "somethingw.exe"
    lone.write_text("", encoding="utf-8")
    monkeypatch.setattr(integrations.sys, "frozen", True, raising=False)
    monkeypatch.setattr(integrations.sys, "executable", str(lone), raising=False)

    assert integrations.endpoints().mcp_command == str(lone)


def test_a_source_install_without_the_script_uses_the_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(integrations.sys, "frozen", raising=False)
    monkeypatch.setattr(integrations.shutil, "which", lambda _: None)

    assert integrations.endpoints().mcp_args == ("-m", "sensei.cli", "mcp")


def test_the_module_form_it_writes_can_actually_be_run() -> None:
    """`-m sensei.cli` needs a `__main__.py`, and there was none.

    The test above only checks which string gets written. That string was
    `python -m sensei.cli mcp`, and running it produced "'sensei.cli' is a
    package and cannot be directly executed" — so every source install wired
    its editors to a command that could not start, and the editor reported
    only that it could not attach to the server.

    Asserting on the import machinery rather than spawning a subprocess: the
    question is whether the entry point exists, and a subprocess would make
    this a slow test of the whole CLI.
    """
    assert importlib.util.find_spec("sensei.cli.__main__") is not None


def test_the_console_script_is_preferred_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(integrations.sys, "frozen", raising=False)
    monkeypatch.setattr(integrations.shutil, "which", lambda _: "/usr/local/bin/sensei")

    ep = integrations.endpoints()
    assert ep.mcp_command == "sensei"
    assert ep.mcp_args == ("mcp",)


class TestToolsThatMovedTheirConfig:
    """Editors relocate their configuration and read the new place on their own
    schedule. Devin moved Windsurf's out of `~/.codeium/windsurf/` into
    `%APPDATA%/devin/` and now shows a dialog offering to copy it across —
    which means at any moment a user is on one side of that or the other, and
    nothing on this side can tell which.
    """

    @staticmethod
    def _two_location_tool(new: Path, old: Path) -> Integration:
        return Integration(
            id="fake",
            name="Fake Tool",
            path=lambda: new,
            legacy_paths=(lambda: old,),
            apply=integrations._mcp_apply(("mcpServers",)),
            revert=integrations._mcp_revert(("mcpServers",)),
        )

    def test_both_locations_are_written(
        self, sandbox: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Writing only the current one leaves an un-migrated install unwired;
        writing only the old one wires a directory the tool has stopped
        reading. Both costs a few hundred bytes."""
        new, old = sandbox / "new" / "mcp.json", sandbox / "old" / "mcp.json"
        new.parent.mkdir(parents=True)
        old.parent.mkdir(parents=True)
        _install(monkeypatch, self._two_location_tool(new, old))

        outcomes = integrations.apply_all()

        assert [o.status for o in outcomes] == ["applied", "applied"]
        for path in (new, old):
            assert "sensei" in json.loads(path.read_text(encoding="utf-8"))["mcpServers"]

    def test_undo_reaches_both(self, sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The failure this prevents: `--undo` cleans the current location and
        leaves a stale entry behind in the old one, pointing at a gateway that
        may no longer exist."""
        new, old = sandbox / "new" / "mcp.json", sandbox / "old" / "mcp.json"
        new.parent.mkdir(parents=True)
        old.parent.mkdir(parents=True)
        _install(monkeypatch, self._two_location_tool(new, old))

        integrations.apply_all()
        integrations.undo_all()

        assert not new.exists()
        assert not old.exists()

    def test_detection_accepts_either(self, sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A user who has not migrated still has the tool installed."""
        new, old = sandbox / "new" / "mcp.json", sandbox / "old" / "mcp.json"
        old.parent.mkdir(parents=True)  # only the legacy directory exists
        assert self._two_location_tool(new, old).detect() is True

    def test_the_same_path_twice_is_written_once(self, sandbox: Path) -> None:
        """A tool that never moved would otherwise be reported twice."""
        same = sandbox / "cfg.json"
        entry = self._two_location_tool(same, same)
        assert entry.targets() == [same]


class TestMcpAvailability:
    """A server entry for a command that cannot start is worse than none.

    A PyInstaller binary built without the optional `mcp` extra starts, reports
    its version and wires base URLs happily — then dies with ModuleNotFoundError
    the moment an editor spawns `sensei mcp`. Claude Desktop shows "Server
    disconnected" with no indication that a missing Python package is the
    reason, and it does so on every launch, forever.
    """

    @staticmethod
    def _endpoints(ready: bool) -> Endpoints:
        return Endpoints(
            anthropic="http://127.0.0.1:7000",
            openai="http://127.0.0.1:7000/v1",
            mcp_command="sensei",
            mcp_args=("mcp",),
            mcp_ready=ready,
        )

    def test_no_server_entry_is_written_without_the_extra(self) -> None:
        doc: dict = {}
        changed = integrations._mcp_apply(("mcpServers",))(doc, self._endpoints(False))
        assert changed is False
        assert doc == {}

    def test_the_entry_is_written_when_it_can_run(self) -> None:
        doc: dict = {}
        assert integrations._mcp_apply(("mcpServers",))(doc, self._endpoints(True))
        assert doc["mcpServers"]["sensei"]["args"] == ["mcp"]

    def test_claude_code_still_gets_its_routing(self) -> None:
        """The gateway half is what matters there and works regardless; only
        the tools are unavailable."""
        doc: dict = {}
        assert integrations._claude_code_apply(doc, self._endpoints(False))
        assert doc["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:7000"
        assert "mcpServers" not in doc

    def test_availability_follows_the_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(integrations.importlib.util, "find_spec", lambda _: None)
        assert integrations.mcp_available() is False
        monkeypatch.setattr(integrations.importlib.util, "find_spec", lambda _: object())
        assert integrations.mcp_available() is True


def test_openai_endpoint_carries_the_v1_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(integrations.settings, "host", "127.0.0.1")
    monkeypatch.setattr(integrations.settings, "port", 1234)
    ep = integrations.endpoints()
    assert ep.openai == "http://127.0.0.1:1234/v1"
    assert ep.anthropic == "http://127.0.0.1:1234"


# ── Detection ───────────────────────────────────────────────────────────────


def test_a_dotfile_in_home_does_not_count_as_installed(tmp_path: Path) -> None:
    """`~/.aider.conf.yml` has the home directory as its parent, and that always
    exists. Without a guard every such tool reports as installed everywhere."""
    entry = integrations.BlockIntegration(
        id="x",
        name="X",
        path=lambda: Path.home() / ".definitely-not-installed.conf.yml",
        body=lambda ep: "",
        conflicts=(),
    )
    assert entry.detect() is False


# ── Per-project scoping ─────────────────────────────────────────────────────


def _project_integration(name: str = "fake") -> Integration:
    return Integration(
        id=name,
        name="Fake Tool",
        path=lambda: Path.home() / ".fake" / "config.json",
        project_path=lambda root: root / ".fake" / "config.json",
        apply=integrations._mcp_apply(("mcpServers",)),
        revert=integrations._mcp_revert(("mcpServers",)),
    )


def test_project_mode_writes_inside_the_checkout(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = sandbox / "repo"
    repo.mkdir()
    _install(monkeypatch, _project_integration())

    outcomes = integrations.apply_all(project=repo)

    assert [o.status for o in outcomes] == ["applied"]
    written = repo / ".fake" / "config.json"
    assert written.is_file()
    assert "sensei" in json.loads(written.read_text(encoding="utf-8"))["mcpServers"]


def test_project_mode_skips_tools_without_repo_config(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reported as absent rather than written to the wrong place."""
    _install(monkeypatch, _json_integration(sandbox / "tool" / "config.json"))
    assert integrations.apply_all(project=sandbox) == []


def test_project_mode_ignores_detection(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Committing a `.cursor/mcp.json` for a teammate who has Cursor when you do
    not is a legitimate thing to want."""
    repo = sandbox / "repo"
    repo.mkdir()
    entry = _project_integration()
    _install(monkeypatch, entry)
    assert entry.detect() is False
    assert integrations.apply_all(project=repo)[0].status == "applied"


def test_project_and_machine_records_coexist(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Undoing one must not make Sensei forget it ever touched the other.

    The manifest used to be keyed by tool id alone, so wiring the same tool
    machine-wide and then inside a repo silently dropped the first record — and
    with it the backup that `--undo` needs.
    """
    repo = sandbox / "repo"
    repo.mkdir()
    machine_cfg = sandbox / "home" / "config.json"
    machine_cfg.parent.mkdir()

    entry = Integration(
        id="fake",
        name="Fake Tool",
        path=lambda: machine_cfg,
        project_path=lambda root: root / ".fake" / "config.json",
        apply=integrations._mcp_apply(("mcpServers",)),
        revert=integrations._mcp_revert(("mcpServers",)),
    )
    _install(monkeypatch, entry)

    integrations.apply_all()
    integrations.apply_all(project=repo)

    paths = {e["path"] for e in integrations._read_manifest()["entries"]}
    assert str(machine_cfg) in paths
    assert str(repo / ".fake" / "config.json") in paths

    integrations.undo_all()
    assert not machine_cfg.exists()
    assert not (repo / ".fake" / "config.json").exists()


def test_an_existing_tool_directory_counts_as_installed(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool_dir = sandbox / ".sometool"
    tool_dir.mkdir()
    entry = _json_integration(tool_dir / "config.json")
    assert entry.detect() is True

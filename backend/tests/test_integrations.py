"""Tests for the tool-wiring engine.

This module edits configuration files belonging to other programs. The failure
mode that matters is not "the setting was not written" — the user notices that
immediately — but "something else in the file was lost", which they notice weeks
later when a tool stops working. Most of what follows is about that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sensei import integrations
from sensei.integrations import Endpoints, Integration


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point Sensei's bookkeeping at a temporary directory."""
    home = tmp_path / "sensei-home"
    monkeypatch.setattr(integrations, "SENSEI_HOME", home)
    monkeypatch.setattr(integrations, "MANIFEST_PATH", home / "integrations.json")
    monkeypatch.setattr(integrations, "BACKUP_ROOT", home / "backups")
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

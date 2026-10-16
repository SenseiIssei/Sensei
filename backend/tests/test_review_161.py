"""Regression tests for the eight defects an independent review found in #161.

Each test names the defect it pins. Three of them were reproduced in a temp
HOME by the reviewer before being fixed.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sensei import integrations
from sensei.cli import hook
from sensei.integrations import Endpoints

EP = Endpoints(
    anthropic="http://127.0.0.1:7000",
    openai="http://127.0.0.1:7000/v1",
    mcp_command="sensei",
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sensei_home = tmp_path / "sensei-home"
    monkeypatch.setattr(integrations, "SENSEI_HOME", sensei_home)
    monkeypatch.setattr(integrations, "MANIFEST_PATH", sensei_home / "integrations.json")
    monkeypatch.setattr(integrations, "BACKUP_ROOT", sensei_home / "backups")
    monkeypatch.setattr(integrations, "mcp_available", lambda: True)
    monkeypatch.setattr(integrations, "running_processes", list)
    monkeypatch.setattr(integrations.settings, "port", 7000)
    fake = tmp_path / "user-home"
    fake.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: fake))
    for var, sub in (
        ("APPDATA", "AppData/Roaming"),
        ("LOCALAPPDATA", "AppData/Local"),
        ("XDG_CONFIG_HOME", ".config"),
    ):
        monkeypatch.setenv(var, str(fake / sub))
    for var in ("CODEX_HOME", "COPILOT_HOME", "CLINE_DIR", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)
    return fake


# ── 1. undo must never throw away the user's own edits ──────────────────────


def test_undo_keeps_edits_made_between_two_sensei_writes(home: Path) -> None:
    """The reviewer's repro: Sensei creates settings.json, the user adds
    permissions, routing is switched on (a second write), undo. The file used
    to be deleted — permissions and all."""
    (home / ".claude").mkdir()
    settings = home / ".claude" / "settings.json"
    integrations.apply_all(only={"claude-code"})

    doc = json.loads(settings.read_text("utf-8"))
    doc["permissions"] = {"allow": ["Bash(npm test)"]}
    settings.write_text(json.dumps(doc), "utf-8")

    integrations.set_option("claude-code", "route", True)
    integrations.apply_all(only={"claude-code"})
    integrations.undo_all(only={"claude-code"})

    assert settings.exists()
    assert json.loads(settings.read_text("utf-8")) == {"permissions": {"allow": ["Bash(npm test)"]}}


def test_undo_never_restores_a_stale_backup_over_later_state(home: Path) -> None:
    """With a backup present, undo used to restore the oldest copy — for
    ~/.claude.json that is weeks of Claude Code's own state."""
    (home / ".claude").mkdir()
    state = home / ".claude.json"
    state.write_text(json.dumps({"numStartups": 1}), "utf-8")
    integrations.apply_all(only={"claude-code"})

    doc = json.loads(state.read_text("utf-8"))
    doc["numStartups"] = 50
    state.write_text(json.dumps(doc), "utf-8")
    integrations.apply_all(only={"claude-code"}, port=7100)  # a second Sensei write

    integrations.undo_all(only={"claude-code"})
    assert json.loads(state.read_text("utf-8")) == {"numStartups": 50}


def test_a_pristine_file_is_still_restored_byte_for_byte(home: Path) -> None:
    (home / ".cursor").mkdir()
    cfg = home / ".cursor" / "mcp.json"
    original = '{\n    "mcpServers": {}, "theme": "x"\n}\n'
    cfg.write_text(original, "utf-8")
    integrations.apply_all(only={"cursor"})
    integrations.apply_all(only={"cursor"}, port=7100)
    integrations.undo_all(only={"cursor"})
    assert cfg.read_text("utf-8") == original


# ── 3. only Sensei's own port counts as "Sensei" ────────────────────────────


@pytest.mark.parametrize(
    "url",
    ["http://localhost:11434/v1", "http://127.0.0.1:3456", "http://localhost/v1"],
)
def test_a_users_local_proxy_is_not_sensei(home: Path, url: str) -> None:
    assert integrations._points_here(url) is False


def test_sensei_ports_are_recognised_including_ones_it_wrote(home: Path) -> None:
    assert integrations._points_here("http://127.0.0.1:7000")
    assert not integrations._points_here("http://127.0.0.1:7100")
    (home / ".cursor").mkdir()
    integrations.apply_all(only={"cursor"}, port=7100)
    assert integrations._points_here("http://127.0.0.1:7100")


def test_connect_keeps_codex_pointed_at_ollama(home: Path) -> None:
    cfg = home / ".codex" / "config.toml"
    cfg.parent.mkdir()
    cfg.write_text('openai_base_url = "http://localhost:11434/v1"\n', "utf-8")
    integrations.apply_all(only={"codex"})
    assert 'openai_base_url = "http://localhost:11434/v1"' in cfg.read_text("utf-8")
    integrations.undo_all(only={"codex"})
    assert 'openai_base_url = "http://localhost:11434/v1"' in cfg.read_text("utf-8")


def test_revert_keeps_claude_code_router(home: Path) -> None:
    doc = {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:3456"}}
    integrations._claude_code_revert(doc)
    assert doc["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:3456"
    vscode = {
        "claudeCode.environmentVariables": [
            {"name": "ANTHROPIC_BASE_URL", "value": "http://127.0.0.1:3456"}
        ]
    }
    integrations._vscode_claude_env_revert(vscode)
    assert vscode["claudeCode.environmentVariables"][0]["value"] == "http://127.0.0.1:3456"


# ── 4. writes keep the file's mode and do not replace symlinks ──────────────


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_atomic_write_keeps_owner_only_mode(tmp_path: Path) -> None:
    secret = tmp_path / ".claude.json"
    secret.write_text("{}", "utf-8")
    os.chmod(secret, 0o600)
    integrations._atomic_write(secret, '{"a": 1}\n')
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_a_new_file_is_created_owner_only(tmp_path: Path) -> None:
    fresh = tmp_path / "new.json"
    integrations._atomic_write(fresh, "{}\n")
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o600


def test_atomic_write_writes_through_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text("{}", "utf-8")
    link = tmp_path / "settings.json"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    integrations._atomic_write(link, '{"x": 1}\n')
    assert link.is_symlink()
    assert real.read_text("utf-8") == '{"x": 1}\n'


# ── 6. TOML: the user's strings are never reformatted ───────────────────────


def test_toml_multiline_strings_survive() -> None:
    user = (
        'instructions = """\n'
        "first\n\n\n\nafter three blank lines\n"
        "[mcp_servers.sensei]\n"
        'not a table, just text\n"""\n'
        '\n[windows]\nsandbox = "elevated"\n'
    )
    out = integrations._codex_apply(user, EP) or ""
    assert out.startswith(user[: user.index('"""\n\n[windows]') + 4])
    assert "after three blank lines\n[mcp_servers.sensei]\nnot a table" in out
    reverted = integrations._codex_revert(out)
    assert "first\n\n\n\nafter three blank lines" in reverted
    assert "not a table, just text" in reverted


# ── 7. the self-heal hook protects the URL in the file, not its own port ────


def test_self_heal_probes_and_starts_the_port_in_the_base_url(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_file = home / ".claude" / "settings.json"
    settings_file.parent.mkdir()
    settings_file.write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:7100"}}), "utf-8"
    )
    monkeypatch.setattr(integrations, "_sensei_ports", lambda: {7000, 7100})
    probed: list[str] = []
    started: list[Any] = []
    monkeypatch.setattr(hook, "_alive", lambda base, timeout=1.0: probed.append(base) or False)
    monkeypatch.setattr(hook, "_start_detached", lambda port: started.append(port) or False)

    hook.claude_session_start(wait_seconds=0)

    assert probed == ["http://127.0.0.1:7100"]
    assert started == [7100]


def test_self_heal_leaves_a_foreign_base_url_alone(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_file = home / ".claude" / "settings.json"
    settings_file.parent.mkdir()
    body = {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:3456"}}
    settings_file.write_text(json.dumps(body), "utf-8")
    monkeypatch.setattr(hook, "_start_detached", lambda port: pytest.fail("started Sensei"))
    assert hook.claude_session_start(wait_seconds=0) == {}
    assert json.loads(settings_file.read_text("utf-8")) == body


# ── 8. hooks are written to loopback whatever SENSEI_HOST is ────────────────


def test_hook_urls_use_loopback_with_a_lan_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(integrations.settings, "host", "192.168.1.5")
    ep = integrations.endpoints()
    assert ep.anthropic.startswith("http://192.168.1.5:")
    assert ep.hook_url("/hooks/claude/post-tool-use").startswith("http://127.0.0.1:")


# ── 2. CSRF on the state-changing API ───────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    from sensei.main import app

    return TestClient(app)


def test_a_cross_site_connect_is_refused(home: Path, client: TestClient) -> None:
    """The reviewer's repro: a simple POST from https://evil.example got 200,
    flipped auto_connect and rewrote every tool's config."""
    (home / ".cursor").mkdir()
    r = client.post(
        "/api/setup/tools/connect",
        content=b"",
        headers={"Origin": "https://evil.example", "Content-Type": "text/plain"},
    )
    assert r.status_code == 403
    assert not (home / ".cursor" / "mcp.json").exists()
    assert integrations.auto_connect_choice() is None


def test_a_text_plain_post_without_origin_is_refused(home: Path, client: TestClient) -> None:
    r = client.post(
        "/api/setup/tools/disconnect", content=b"x", headers={"Content-Type": "text/plain"}
    )
    assert r.status_code == 415


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/setup/tools/disconnect", "post"),
        ("/api/setup/tools/auto-connect", "put"),
        ("/api/setup/tools/cursor/connect", "post"),
        ("/api/setup/tools/claude-code/route", "put"),
        ("/api/settings", "put"),
        ("/api/stats/savings/forget", "post"),
    ],
)
def test_every_state_changing_api_route_refuses_a_foreign_origin(
    home: Path, client: TestClient, path: str, method: str
) -> None:
    r = getattr(client, method)(
        path, json={"enabled": True}, headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403


def test_same_origin_and_loopback_pages_still_work(home: Path, client: TestClient) -> None:
    for origin in ("http://testserver", "http://localhost:5173", "http://127.0.0.1:7000"):
        r = client.put(
            "/api/setup/tools/auto-connect", json={"enabled": True}, headers={"Origin": origin}
        )
        assert r.status_code == 200, origin


def test_reads_are_not_affected(home: Path, client: TestClient) -> None:
    assert (
        client.get("/api/setup/tools", headers={"Origin": "https://evil.example"}).status_code
        == 200
    )

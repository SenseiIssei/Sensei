"""The one switch: CLI, API, installers, the self-heal hook and remote MCP auth."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sensei import autowire, integrations
from sensei.cli import hook, setup_tools

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sensei_home = tmp_path / "sensei-home"
    monkeypatch.setattr(integrations, "SENSEI_HOME", sensei_home)
    monkeypatch.setattr(integrations, "MANIFEST_PATH", sensei_home / "integrations.json")
    monkeypatch.setattr(integrations, "BACKUP_ROOT", sensei_home / "backups")
    monkeypatch.setattr(integrations, "mcp_available", lambda: True)
    monkeypatch.setattr(integrations, "running_processes", list)
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


# ── CLI ─────────────────────────────────────────────────────────────────────


def test_auto_off_if_unset_is_what_the_installer_records(home: Path) -> None:
    assert setup_tools.run(auto="off", if_unset=True) == 0
    assert integrations.auto_connect_choice() is False


def test_from_installer_respects_an_earlier_disconnect(home: Path) -> None:
    (home / ".cursor").mkdir()
    integrations.set_auto_connect(False)
    setup_tools.run(from_installer=True)
    assert not (home / ".cursor" / "mcp.json").exists()


def test_from_installer_connects_on_a_fresh_machine(home: Path) -> None:
    (home / ".cursor").mkdir()
    setup_tools.run(from_installer=True)
    assert (home / ".cursor" / "mcp.json").exists()
    assert integrations.auto_connect_choice() is True


def test_route_needs_a_routable_tool(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert setup_tools.run(route=True) == 2
    assert setup_tools.run(route=True, only=["cursor"]) == 2
    assert "claude-code" in capsys.readouterr().out


def test_route_and_no_route_for_claude_code(home: Path) -> None:
    (home / ".claude").mkdir()
    settings = home / ".claude" / "settings.json"

    setup_tools.run(only=["claude-code"], route=True)
    doc = json.loads(settings.read_text("utf-8"))
    assert integrations.claude_code_routed(doc)
    assert "SessionStart" in doc["hooks"]

    setup_tools.run(only=["claude-code"], route=False)
    doc = json.loads(settings.read_text("utf-8"))
    assert not integrations.claude_code_routed(doc), "an explicit --no-route removes it"
    assert "PostToolUse" in doc["hooks"], "the compression hook stays"


def test_uninstall_forgets_the_choices(home: Path) -> None:
    (home / ".cursor").mkdir()
    integrations.connect_everything()
    setup_tools.run(undo=True, forget=True)
    assert integrations.declined() == set()
    assert integrations.auto_connect_choice() is None


def test_status_prints_every_tool_and_why(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert setup_tools.run(show_status=True) == 0
    out = capsys.readouterr().out
    assert "Claude Code" in out
    assert "ChatGPT" in out and "why:" in out


def test_connect_and_disconnect_commands_parse() -> None:
    from sensei.cli import _build_parser

    parser = _build_parser()
    assert parser.parse_args(["connect", "--dry-run"]).command == "connect"
    assert parser.parse_args(["disconnect"]).command == "disconnect"
    args = parser.parse_args(["setup-tools", "--only", "claude-code", "--route"])
    assert args.route is True
    args = parser.parse_args(["mcp", "--transport", "streamable-http", "--allow-host", "x.ts.net"])
    assert args.allow_host == ["x.ts.net"]


# ── The watcher ─────────────────────────────────────────────────────────────


def test_the_watcher_does_nothing_once_told_no(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(integrations, "apply_all", lambda **kw: calls.append(kw) or [])
    integrations.set_auto_connect(False)
    (home / ".cursor").mkdir()

    watcher = autowire.Watcher(interval=0.01)
    assert asyncio.run(watcher.scan(first=True)) == []
    assert calls == []


def test_the_watcher_tells_listeners_what_it_connected(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (home / ".cursor").mkdir()
    heard: list[list[str]] = []
    monkeypatch.setattr(autowire, "_listeners", [heard.append])
    asyncio.run(autowire.Watcher(interval=0.01).scan(first=True))
    assert heard and "Cursor" in heard[0]


# ── API ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    from sensei.main import app

    return TestClient(app)


def test_api_lists_rich_rows(home: Path, client: TestClient) -> None:
    body = client.get("/api/setup/tools").json()
    row = next(t for t in body["tools"] if t["id"] == "claude-code")
    assert row["support"] == "hook+mcp"
    assert "route" in row["options"]
    assert "choice" in body["auto_connect"]


def test_api_connect_and_disconnect_everything(home: Path, client: TestClient) -> None:
    (home / ".cursor").mkdir()
    out = client.post("/api/setup/tools/connect", json={}).json()["outcomes"]
    assert any(o["id"] == "cursor" and o["status"] == "applied" for o in out)
    assert integrations.auto_connect_choice() is True

    client.post("/api/setup/tools/disconnect", json={})
    assert not (home / ".cursor" / "mcp.json").exists()
    assert integrations.auto_connect_choice() is False


def test_api_per_tool_and_route(home: Path, client: TestClient) -> None:
    (home / ".claude").mkdir()
    assert client.post("/api/setup/tools/nope/connect", json={}).status_code == 404
    assert client.put("/api/setup/tools/cursor/route", json={"enabled": True}).status_code == 400
    r = client.put("/api/setup/tools/claude-code/route", json={"enabled": True})
    assert r.status_code == 200
    doc = json.loads((home / ".claude" / "settings.json").read_text("utf-8"))
    assert integrations.claude_code_routed(doc)


# ── The SessionStart self-heal hook ─────────────────────────────────────────


def _routed(home: Path, extra: dict[str, str] | None = None) -> Path:
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(exist_ok=True)
    env = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:7000", **(extra or {})}
    settings.write_text(json.dumps({"env": env}), "utf-8")
    return settings


def test_self_heal_is_silent_when_sensei_answers(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _routed(home)
    monkeypatch.setattr(hook, "_alive", lambda base, timeout=1.0: True)
    assert hook.claude_session_start() == {}


def test_self_heal_is_silent_without_routing(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook, "_start_detached", lambda port: pytest.fail("started Sensei"))
    assert hook.claude_session_start() == {}


def test_self_heal_starts_sensei_when_it_can(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _routed(home)
    state = {"started": False}
    monkeypatch.setattr(hook, "_alive", lambda base, timeout=1.0: state["started"])
    monkeypatch.setattr(hook, "_start_detached", lambda port: state.update(started=True) or True)
    monkeypatch.setattr(hook.time, "sleep", lambda _s: None)
    assert "started it" in hook.claude_session_start()["systemMessage"]


def test_self_heal_clears_a_dead_base_url(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _routed(home, {"FOO": "1"})
    monkeypatch.setattr(hook, "_alive", lambda base, timeout=1.0: False)
    monkeypatch.setattr(hook, "_start_detached", lambda port: False)

    answer = hook.claude_session_start(wait_seconds=0)
    assert "Removed it" in answer["systemMessage"]
    assert json.loads(settings.read_text("utf-8")) == {"env": {"FOO": "1"}}


def test_self_heal_never_fails_the_tool(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(**_kw: Any) -> dict[str, Any]:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(hook, "claude_session_start", boom)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    assert hook.run("claude-session-start") == 0
    assert capsys.readouterr().out == ""


# ── Remote MCP ──────────────────────────────────────────────────────────────


class TestRemoteMcpGuard:
    @pytest.fixture
    def guarded(self) -> TestClient:
        pytest.importorskip("mcp")
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        from sensei.mcp_server import Guard

        async def ok(_request: Any) -> PlainTextResponse:
            return PlainTextResponse("ok")

        inner = Starlette(routes=[Route("/mcp", ok, methods=["GET", "POST"])])
        app = Guard(inner, token="s3cret", allow_hosts=("box.tail1234.ts.net",))
        return TestClient(app, base_url="http://127.0.0.1:7001")

    def test_needs_the_token(self, guarded: TestClient) -> None:
        assert guarded.post("/mcp").status_code == 401
        assert guarded.post("/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert guarded.post("/mcp", headers={"Authorization": "Bearer s3cret"}).text == "ok"

    def test_rejects_an_unknown_host(self, guarded: TestClient) -> None:
        """DNS rebinding: a page whose name now resolves to 127.0.0.1 still
        sends its own Host."""
        headers = {"Authorization": "Bearer s3cret", "Host": "evil.example"}
        assert guarded.post("/mcp", headers=headers).status_code == 421
        headers["Host"] = "box.tail1234.ts.net"
        assert guarded.post("/mcp", headers=headers).status_code == 200

    def test_rejects_a_foreign_origin(self, guarded: TestClient) -> None:
        headers = {"Authorization": "Bearer s3cret", "Origin": "https://evil.example"}
        assert guarded.post("/mcp", headers=headers).status_code == 403

    def test_no_auth_is_refused_when_exposed(self) -> None:
        from sensei import mcp_server

        assert mcp_server.run("streamable-http", no_auth=True, allow_hosts=("x.ts.net",)) == 2
        assert mcp_server.run("streamable-http", host="0.0.0.0", no_auth=True) == 2

    def test_token_is_created_once_and_private(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sensei import mcp_server

        monkeypatch.setattr(mcp_server, "_token_path", lambda: tmp_path / "mcp-token")
        monkeypatch.setattr(mcp_server.settings, "mcp_http_token", "")
        first = mcp_server.http_token()
        assert first and mcp_server.http_token() == first
        assert len(first) >= 32


# ── Installers ──────────────────────────────────────────────────────────────


def test_the_installer_records_no_before_starting_the_tray() -> None:
    script = (ROOT / "packaging" / "sensei.iss").read_text(encoding="utf-8")
    # The section header, not the mention of it in the file's top comment.
    run = script.split("\n[Run]\n", 1)[1].split("\n[", 1)[0]
    tray = run.index("tray --no-browser")
    # The wizard's "no" overrides an earlier yes; only the silent update
    # replay leaves a later choice alone.
    explicit = run.index('Parameters: "setup-tools --auto off";')
    replay = run.index('Parameters: "setup-tools --auto off --if-unset";')
    assert "Tasks: not wiretools; Check: not WizardSilent" in run[explicit : explicit + 300]
    assert "Tasks: not wiretools; Check: WizardSilent" in run[replay : replay + 300]
    assert max(explicit, replay) < tray, "the tray would scan before the no is saved"
    assert "--from-installer" in run


def test_install_ps1_does_not_wait_for_the_tray() -> None:
    """`Start-Process -Wait` waits for the whole process tree, and the silent
    installer leaves the tray running: the script hung forever."""
    script = (ROOT / "install.ps1").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "-Wait" not in code
    assert "WaitForExit()" in code
    assert 'Get-Process -Name "senseiw"' in code


def test_install_sh_asks_about_tools_before_starting_the_server() -> None:
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert script.index("setup-tools --from-installer") < script.index('"$DIR/sensei" autostart on')
    # An explicit "no" overrides an earlier "yes".
    assert "setup-tools --auto off" in script
    assert "--if-unset" not in script


def test_install_ps1_and_py_no_overrides_an_earlier_yes() -> None:
    for name in ("install.ps1", "install.py"):
        script = (ROOT / name).read_text(encoding="utf-8")
        assert "--if-unset" not in script, name

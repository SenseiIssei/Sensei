"""Hook-based wiring, Codex's TOML, and the one switch.

The registry entries under test build their paths from `Path.home()` and the
platform directories, so everything here runs in the same fenced-off home as
test_integrations.py — a test that wires the real Claude Code would edit the
settings of whoever runs the suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sensei import integrations
from sensei.integrations import Endpoints

EP = Endpoints(
    anthropic="http://127.0.0.1:7000",
    openai="http://127.0.0.1:7000/v1",
    mcp_command="sensei",
    mcp_args=("mcp",),
)
ROUTED = Endpoints(
    anthropic=EP.anthropic,
    openai=EP.openai,
    mcp_command=EP.mcp_command,
    mcp_args=EP.mcp_args,
    opt_in=frozenset({"claude-code:route", "codex:route"}),
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sensei_home = tmp_path / "sensei-home"
    monkeypatch.setattr(integrations, "SENSEI_HOME", sensei_home)
    monkeypatch.setattr(integrations, "MANIFEST_PATH", sensei_home / "integrations.json")
    monkeypatch.setattr(integrations, "BACKUP_ROOT", sensei_home / "backups")
    monkeypatch.setattr(integrations, "mcp_available", lambda: True)
    monkeypatch.setattr(integrations.shutil, "which", lambda _name: None)
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


def _tool(tool_id: str) -> integrations.Integration:
    return next(i for i in integrations.REGISTRY if i.id == tool_id)


# ── Claude Code ─────────────────────────────────────────────────────────────


class TestClaudeCodeHook:
    def test_default_is_a_hook_not_a_base_url(self) -> None:
        """A custom ANTHROPIC_BASE_URL turns Remote Control off. The default
        must not set one."""
        doc: dict = {}
        assert integrations._claude_code_apply(doc, EP)
        assert "env" not in doc
        (group,) = doc["hooks"]["PostToolUse"]
        (hook,) = group["hooks"]
        assert hook["type"] == "http"
        assert hook["url"] == "http://127.0.0.1:7000/hooks/claude/post-tool-use"
        # Never the file tools: Edit matches against what Read returned.
        for tool in ("Read", "Edit", "Write"):
            assert tool not in group["matcher"].split("|")
        assert "Bash" in group["matcher"]

    def test_applying_twice_is_a_no_op(self) -> None:
        doc: dict = {}
        integrations._claude_code_apply(doc, EP)
        assert integrations._claude_code_apply(doc, EP) is False

    def test_the_users_own_hooks_survive_apply_and_revert(self) -> None:
        mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "lint.sh"}]}
        doc: dict = {"hooks": {"PostToolUse": [mine]}, "model": "opus"}
        integrations._claude_code_apply(doc, EP)
        assert doc["hooks"]["PostToolUse"][0] == mine
        assert len(doc["hooks"]["PostToolUse"]) == 2

        assert integrations._claude_code_revert(doc)
        assert doc == {"hooks": {"PostToolUse": [mine]}, "model": "opus"}

    def test_a_port_change_replaces_the_hook_instead_of_adding_one(self) -> None:
        doc: dict = {}
        integrations._claude_code_apply(doc, EP)
        moved = Endpoints(
            anthropic="http://127.0.0.1:7100",
            openai="http://127.0.0.1:7100/v1",
            mcp_command="sensei",
        )
        assert integrations._claude_code_apply(doc, moved)
        (group,) = doc["hooks"]["PostToolUse"]
        assert group["hooks"][0]["url"].startswith("http://127.0.0.1:7100/")

    def test_routing_is_opt_in_and_brings_the_self_heal_hook(self) -> None:
        doc: dict = {}
        integrations._claude_code_apply(doc, ROUTED)
        assert doc["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:7000"
        (start,) = doc["hooks"]["SessionStart"]
        assert start["hooks"][0]["type"] == "command"
        assert "hook claude-session-start" in start["hooks"][0]["command"]

    def test_turning_routing_off_removes_the_self_heal_but_leaves_a_users_url(self) -> None:
        doc: dict = {}
        integrations._claude_code_apply(doc, ROUTED)
        integrations._claude_code_apply(doc, EP)
        assert "SessionStart" not in doc["hooks"]
        # The base URL itself stays until undo: turning the option off is
        # recorded, and undo is what removes Sensei's keys.
        assert integrations._claude_code_revert(doc)
        assert "env" not in doc

    def test_revert_keeps_a_base_url_that_is_not_sensei(self) -> None:
        doc = {"env": {"ANTHROPIC_BASE_URL": "https://gateway.example.com"}}
        integrations._claude_code_revert(doc)
        assert doc["env"]["ANTHROPIC_BASE_URL"] == "https://gateway.example.com"

    def test_the_dead_mcp_key_from_0_2_is_tidied_away(self) -> None:
        doc = {"mcpServers": {"sensei": {"command": "sensei", "args": ["mcp"]}}}
        assert integrations._claude_code_apply(doc, EP)
        assert "mcpServers" not in doc

    def test_mcp_goes_to_claude_json_and_project_mode_to_local_files(
        self, home: Path, tmp_path: Path
    ) -> None:
        (home / ".claude").mkdir()
        state = home / ".claude.json"
        state.write_text(json.dumps({"numStartups": 3, "projects": {}}), encoding="utf-8")

        integrations.apply_all(only={"claude-code"})

        settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert "mcpServers" not in settings
        claude_json = json.loads(state.read_text(encoding="utf-8"))
        assert claude_json["numStartups"] == 3
        ep = integrations.endpoints()
        assert claude_json["mcpServers"]["sensei"] == {
            "type": "stdio",
            "command": ep.mcp_command,
            "args": list(ep.mcp_args),
        }

        repo = tmp_path / "repo"
        repo.mkdir()
        integrations.apply_all(only={"claude-code"}, project=repo)
        assert (repo / ".claude" / "settings.local.json").is_file()
        assert (repo / ".mcp.json").is_file()
        assert not (repo / ".claude" / "settings.json").exists(), "the committed file is untouched"

    def test_claude_config_dir_moves_both_files(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With CLAUDE_CONFIG_DIR set, Claude Code reads settings.json *and*
        .claude.json from that directory and ignores ~/.claude.json."""
        custom = tmp_path / "claude-cfg"
        custom.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(custom))

        integrations.apply_all(only={"claude-code"})

        assert (custom / "settings.json").is_file()
        assert "sensei" in json.loads((custom / ".claude.json").read_text("utf-8"))["mcpServers"]
        assert not (home / ".claude.json").exists()

    def test_undo_after_claude_rewrote_its_state_file_removes_only_sensei(self, home: Path) -> None:
        """~/.claude.json is rewritten constantly, so its hash never matches on
        undo. That must lead to a surgical removal, not a restored backup that
        would roll back everything Claude Code wrote since."""
        (home / ".claude").mkdir()
        state = home / ".claude.json"
        state.write_text(json.dumps({"numStartups": 1}), encoding="utf-8")
        integrations.apply_all(only={"claude-code"})

        doc = json.loads(state.read_text(encoding="utf-8"))
        doc["numStartups"] = 99
        state.write_text(json.dumps(doc), encoding="utf-8")

        integrations.undo_all(only={"claude-code"})
        assert json.loads(state.read_text(encoding="utf-8")) == {"numStartups": 99}

    def test_status_counts_the_hook_and_the_mcp_entry(self, home: Path) -> None:
        (home / ".claude").mkdir()
        claude = _tool("claude-code")
        assert integrations._is_wired(claude, EP) is False
        integrations.apply_all(only={"claude-code"})
        assert integrations._is_wired(claude, integrations.endpoints()) is True

    def test_the_vscode_env_part_is_written_only_when_routing(self, home: Path) -> None:
        user = integrations._vscode_user("Code")
        user.mkdir(parents=True)
        cfg = user / "settings.json"
        cfg.write_text('{"editor.fontSize": 13}', encoding="utf-8")
        (home / ".claude").mkdir()

        integrations.apply_all(only={"claude-code"})
        assert "claudeCode.environmentVariables" not in json.loads(cfg.read_text("utf-8"))

        integrations.set_option("claude-code", "route", True)
        integrations.apply_all(only={"claude-code"})
        env = json.loads(cfg.read_text("utf-8"))["claudeCode.environmentVariables"]
        assert env == [{"name": "ANTHROPIC_BASE_URL", "value": integrations.endpoints().anthropic}]


# ── Codex ───────────────────────────────────────────────────────────────────

APP_WRITTEN = """notify = ["codex-notify"]

[desktop]
theme = "dark"

[mcp_servers.node_repl]
command = "node"

[windows]
sandbox = "elevated"
"""


class TestCodexToml:
    def test_tables_are_added_without_disturbing_the_rest(self) -> None:
        out = integrations._codex_apply(APP_WRITTEN, EP)
        assert out is not None
        assert out.startswith('notify = ["codex-notify"]\n\n[desktop]')
        assert "[mcp_servers.node_repl]" in out
        assert '[mcp_servers.sensei]\ncommand = "sensei"\nargs = ["mcp"]' in out
        assert 'wire_api = "responses"' in out
        assert 'wire_api = "chat"' not in out
        assert "openai_base_url" not in out, "routing is opt-in"

    def test_idempotent(self) -> None:
        once = integrations._codex_apply(APP_WRITTEN, EP)
        assert integrations._codex_apply(once or "", EP) == once

    def test_route_puts_the_top_level_key_before_the_first_table(self) -> None:
        """Appended at the end it would land inside [windows]."""
        out = integrations._codex_apply(APP_WRITTEN, ROUTED) or ""
        head = out.split("[desktop]", 1)[0]
        assert 'openai_base_url = "http://127.0.0.1:7000/v1"' in head

    def test_survives_the_app_reordering_tables_and_dropping_comments(self) -> None:
        """The Codex app rewrites config.toml. Nothing may depend on markers."""
        written = integrations._codex_apply(APP_WRITTEN, ROUTED) or ""
        sections = written.split("\n[")
        rewritten = "\n[".join([sections[0], *reversed(sections[1:])])
        rewritten = rewritten.replace(integrations.BLOCK_BEGIN, "").replace(
            integrations.BLOCK_END, ""
        )

        reverted = integrations._codex_revert(rewritten)
        assert "sensei" not in reverted
        assert "openai_base_url" not in reverted
        assert "[mcp_servers.node_repl]" in reverted
        assert 'sandbox = "elevated"' in reverted

    def test_a_0_2_marker_block_is_migrated_in_place(self) -> None:
        old = (
            APP_WRITTEN
            + f"\n{integrations.BLOCK_BEGIN}\n[model_providers.sensei]\n"
            + 'base_url = "http://127.0.0.1:9999/v1"\n'
            + f"{integrations.BLOCK_END}\n"
        )
        out = integrations._codex_apply(old, EP) or ""
        assert "9999" not in out
        assert integrations.BLOCK_BEGIN not in out
        assert out.count("[model_providers.sensei]") == 1

    def test_an_inline_entry_the_user_wrote_is_a_manual_step(self) -> None:
        mine = '[mcp_servers]\nsensei = { command = "my-sensei" }\n'
        assert integrations._codex_apply(mine, EP) is None

    def test_no_mcp_table_when_mcp_cannot_run(self) -> None:
        no_mcp = Endpoints(
            anthropic=EP.anthropic, openai=EP.openai, mcp_command="sensei", mcp_ready=False
        )
        out = integrations._codex_apply("", no_mcp) or ""
        assert "[mcp_servers.sensei]" not in out
        assert "[model_providers.sensei]" in out

    def test_round_trip_through_apply_all_and_undo(self, home: Path) -> None:
        cfg = home / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(APP_WRITTEN, encoding="utf-8")

        outcomes = integrations.apply_all(only={"codex"})
        assert [o.status for o in outcomes] == ["applied"]
        assert integrations.apply_all(only={"codex"})[0].status == "unchanged"

        # The app rewrites the file after Sensei did: undo cannot restore the
        # backup and must take Sensei's tables out by name.
        cfg.write_text(cfg.read_text("utf-8") + "\n[plugins.new]\nenabled = true\n", "utf-8")
        integrations.undo_all(only={"codex"})
        text = cfg.read_text("utf-8")
        assert "sensei" not in text
        assert "[plugins.new]" in text and "[windows]" in text


# ── Other hook writers ──────────────────────────────────────────────────────


def test_copilot_cli_gets_a_hook_file_of_its_own(home: Path) -> None:
    (home / ".copilot").mkdir()
    integrations.apply_all(only={"copilot-cli"})
    hook = json.loads((home / ".copilot" / "hooks" / "sensei.json").read_text("utf-8"))
    (entry,) = hook["hooks"]["postToolUse"]
    assert entry["powershell"].startswith("curl.exe ")
    assert entry["bash"].startswith("curl ")
    assert "/hooks/copilot/post-tool-use" in entry["bash"]

    integrations.undo_all(only={"copilot-cli"})
    assert not (home / ".copilot" / "hooks" / "sensei.json").exists()


def test_opencode_gets_the_right_mcp_shape_and_a_plugin(home: Path) -> None:
    cfg_dir = home / ".config" / "opencode"
    cfg_dir.mkdir(parents=True)
    integrations.apply_all(only={"opencode"})
    cfg = json.loads((cfg_dir / "opencode.json").read_text("utf-8"))
    ep = integrations.endpoints()
    assert cfg["mcp"]["sensei"] == {
        "type": "local",
        "command": [ep.mcp_command, *ep.mcp_args],
        "enabled": True,
    }
    plugin = (cfg_dir / "plugins" / "sensei.js").read_text("utf-8")
    assert "tool.execute.after" in plugin and "/hooks/compress" in plugin


def test_a_users_file_under_the_plugin_name_is_left_alone(home: Path) -> None:
    plugin = home / ".config" / "opencode" / "plugins" / "sensei.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("// my own plugin\n", encoding="utf-8")
    outcomes = integrations.apply_all(only={"opencode"})
    assert any(o.status == "manual" for o in outcomes)
    assert plugin.read_text("utf-8") == "// my own plugin\n"


def test_kilo_plugin_has_the_default_export_kilo_expects() -> None:
    assert 'export default { id: "sensei"' in integrations._kilo_plugin(EP)
    assert "export default" not in integrations._opencode_plugin(EP)


def test_the_hook_command_parses_in_every_shell() -> None:
    """`--data-binary @-` is a parse error in PowerShell, which is the shell
    Copilot CLI runs its `powershell` variant in — found with the real CLI."""
    for exe in ("curl", "curl.exe"):
        command = integrations._curl_hook(EP, integrations.COPILOT_HOOK_PATH, exe)
        assert "@" not in command
        assert " -T - " in command


def test_gemini_gets_mcp_only() -> None:
    gemini = _tool("gemini-cli")
    doc: dict = {"theme": "dark"}
    assert gemini.apply(doc, EP)
    assert "hooks" not in doc
    assert gemini.support == "mcp"


def test_vscode_copilot_writes_no_model_group() -> None:
    """A literal apiKey in chatLanguageModels.json is never used by VS Code."""
    vscode = _tool("vscode-copilot")
    assert [p.key for p in vscode.all_parts()] == ["main"]
    assert "route" not in vscode.options


# ── Paths that 0.2 got wrong ────────────────────────────────────────────────


def test_devin_on_macos_and_linux_reads_dot_config(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(integrations.sys, "platform", "darwin")
    assert integrations._devin_config() == home / ".config" / "devin" / "mcp_config.json"


def test_opencode_on_windows_is_under_dot_config_not_appdata(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(integrations.sys, "platform", "win32")
    path = _tool("opencode").path()
    assert path == home / ".config" / "opencode" / "opencode.json"


def test_alternate_homes_are_written_only_where_they_exist(home: Path) -> None:
    """Cline in Cursor is a real install; Cline in an editor the user does not
    have is a directory tree created for nothing."""
    cursor_cline = (
        integrations._vscode_global_storage("Cursor") / "saoudrizwan.claude-dev" / "settings"
    )
    cursor_cline.mkdir(parents=True)
    outcomes = integrations.apply_all(only={"cline"})
    written = {o.path for o in outcomes if o.status == "applied"}
    assert cursor_cline / "cline_mcp_settings.json" in written
    assert not (integrations._vscode_global_storage("Code") / "saoudrizwan.claude-dev").exists()


# ── The one switch and the installer's opt-out ──────────────────────────────


def test_installer_opt_out_stops_the_watcher(home: Path) -> None:
    """The bug: install.ps1 ran with SENSEI_SETUP_TOOLS=no, and the tray it
    started wired every tool within thirty seconds anyway."""
    (home / ".cursor").mkdir()
    integrations.set_auto_connect(False, only_if_unset=True)

    assert integrations.apply_all(automatic=True) == []
    assert not (home / ".cursor" / "mcp.json").exists()


def test_installer_opt_out_does_not_override_a_later_choice(home: Path) -> None:
    """`sensei update` re-runs the installer with the tasks it remembers."""
    integrations.set_auto_connect(True)
    assert integrations.set_auto_connect(False, only_if_unset=True) is True
    assert integrations.auto_connect_allowed()


def test_disconnect_everything_undoes_and_stays_disconnected(home: Path) -> None:
    (home / ".cursor").mkdir()
    integrations.connect_everything()
    assert (home / ".cursor" / "mcp.json").exists()

    integrations.disconnect_everything()
    assert not (home / ".cursor" / "mcp.json").exists()
    assert integrations.auto_connect_choice() is False
    assert integrations.apply_all(automatic=True) == []

    integrations.connect_everything()
    assert integrations.auto_connect_choice() is True
    assert (home / ".cursor" / "mcp.json").exists()


def test_undo_deletes_a_created_file_even_after_a_second_write(home: Path) -> None:
    """The record of a re-write used to replace the first one, and with it
    the fact that the file did not exist before Sensei."""
    (home / ".cursor").mkdir()
    integrations.apply_all(only={"cursor"}, port=7000)
    integrations.apply_all(only={"cursor"}, port=7100)
    integrations.undo_all(only={"cursor"})
    assert not (home / ".cursor" / "mcp.json").exists()


def test_describe_explains_every_row(home: Path) -> None:
    rows = integrations.describe()
    ids = {r["id"] for r in rows}
    assert {"claude-code", "codex", "chatgpt", "jetbrains-ai"} <= ids
    for row in rows:
        assert row["state"] in (
            "connected",
            "declined",
            "not-connected",
            "not-installed",
            "unsupported",
        )
        if row["state"] == "unsupported":
            assert row["why"]


def test_etime_parsing() -> None:
    assert integrations._etime_seconds("05:03") == 303
    assert integrations._etime_seconds("01:00:00") == 3600
    assert integrations._etime_seconds("2-00:00:01") == 172801
    assert integrations._etime_seconds("garbage") is None


def test_needs_restart_compares_process_start_with_the_last_write() -> None:
    claude_desktop = _tool("claude-desktop")
    manifest = {"entries": [{"tool_id": "claude-desktop", "written_at": 1000.0}]}
    assert integrations.needs_restart(claude_desktop, manifest, [("claude.exe", 900.0)])
    assert not integrations.needs_restart(claude_desktop, manifest, [("claude.exe", 1100.0)])
    assert not integrations.needs_restart(claude_desktop, manifest, [])

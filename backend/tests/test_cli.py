"""Tests for the `sensei` command surface.

These cover the parts a first-time user hits: does `sensei wrap claude` set the
right variables, does the hardware sizing pick a model that actually fits, does
`doctor` say something actionable when nothing is configured.
"""

from __future__ import annotations

import pytest

from sensei import hardware
from sensei.cli import _build_parser, main, wrap
from sensei.cli import doctor as doctor_mod


class TestParser:
    def test_bare_invocation_prints_help_and_succeeds(self, capsys):
        assert main([]) == 0
        out = capsys.readouterr().out
        assert "sensei wrap claude" in out
        assert "doctor" in out

    @pytest.mark.parametrize("cmd", ["up", "wrap", "doctor", "models", "stats", "chat"])
    def test_every_command_is_registered(self, cmd):
        args = _build_parser().parse_args([cmd])
        assert args.command == cmd

    def test_up_flags(self):
        args = _build_parser().parse_args(["up", "--port", "9000", "--expose", "--no-browser"])
        assert (args.port, args.expose, args.no_browser) == (9000, True, True)

    def test_wrap_passes_arguments_through(self):
        args = _build_parser().parse_args(["wrap", "aider", "--", "--model", "gpt-4o"])
        assert args.tool == "aider"
        assert args.args[-2:] == ["--model", "gpt-4o"]


class TestWrap:
    def test_claude_gets_the_anthropic_base_url(self):
        env = wrap.routing_env(wrap.TOOLS["claude"], base="http://localhost:7000")
        assert env == {"ANTHROPIC_BASE_URL": "http://localhost:7000"}

    def test_openai_tools_get_the_v1_suffix(self):
        env = wrap.routing_env(wrap.TOOLS["codex"], base="http://localhost:7000")
        assert env == {"OPENAI_BASE_URL": "http://localhost:7000/v1"}

    def test_aider_gets_both_of_its_variable_names(self):
        env = wrap.routing_env(wrap.TOOLS["aider"], base="http://localhost:7000")
        # Aider reads OPENAI_API_BASE; missing it is a silent no-op, not an error.
        assert env["OPENAI_API_BASE"] == "http://localhost:7000/v1"
        assert env["OPENAI_BASE_URL"] == "http://localhost:7000/v1"
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:7000"

    @pytest.mark.parametrize("bind", ["0.0.0.0", "::", ""])
    def test_bind_address_is_never_handed_to_a_client(self, bind, monkeypatch):
        """0.0.0.0 is where a server listens, not somewhere a client can connect."""
        monkeypatch.setattr("sensei.cli.wrap.settings.host", bind)
        monkeypatch.setattr("sensei.cli.wrap.settings.port", 7000)
        assert wrap.gateway_base() == "http://localhost:7000"

    def test_real_host_is_preserved(self, monkeypatch):
        monkeypatch.setattr("sensei.cli.wrap.settings.host", "192.168.1.5")
        monkeypatch.setattr("sensei.cli.wrap.settings.port", 8080)
        assert wrap.gateway_base() == "http://192.168.1.5:8080"

    def test_unknown_tool_lists_the_known_ones(self, capsys):
        assert wrap.run("definitely-not-a-tool", []) == 2
        assert "claude" in capsys.readouterr().err

    def test_every_tool_routes_somewhere(self):
        for name, tool in wrap.TOOLS.items():
            assert tool.openai_vars or tool.anthropic_vars, f"{name} routes nowhere"


CATALOG = [
    {"id": "tiny", "name": "Tiny", "params": "1B", "size_mb": 1000, "good_for": "x"},
    {"id": "mid", "name": "Mid", "params": "7B", "size_mb": 5000, "good_for": "x"},
    {"id": "huge", "name": "Huge", "params": "70B", "size_mb": 40000, "good_for": "x"},
]


class TestHardwareSizing:
    def _hw(self, ram_mb=None, vram_mb=None, unified=False):
        gpus = [hardware.GPU(name="test", vram_mb=vram_mb, vendor="nvidia")] if vram_mb else []
        return hardware.Hardware(
            os="Test", arch="x86_64", cpu_count=8, ram_mb=ram_mb, gpus=gpus, unified_memory=unified
        )

    def test_a_24gb_gpu_fits_the_mid_model_comfortably(self):
        ranked = hardware.recommend(self._hw(ram_mb=32000, vram_mb=24000), CATALOG)
        fits = {m["id"]: m["fit"] for m in ranked}
        assert fits == {"mid": "comfortable", "tiny": "comfortable", "huge": "too_large"}

    def test_biggest_comfortable_model_is_recommended_first(self):
        pick = hardware.best_pick(self._hw(ram_mb=32000, vram_mb=24000), CATALOG)
        assert pick["id"] == "mid"

    def test_no_gpu_falls_back_to_half_of_ram(self):
        hw = self._hw(ram_mb=8000)
        assert hw.usable_vram_mb == 4000
        assert hardware.best_pick(hw, CATALOG)["id"] == "tiny"

    def test_apple_silicon_uses_unified_memory(self):
        hw = self._hw(ram_mb=16000, unified=True)
        assert hw.usable_vram_mb == 11200  # 70% of RAM, not a separate pool
        assert hardware.best_pick(hw, CATALOG)["id"] == "mid"

    def test_nothing_fits_returns_none_rather_than_lying(self):
        assert hardware.best_pick(self._hw(ram_mb=1000), CATALOG) is None

    def test_unknown_memory_never_claims_a_fit(self):
        ranked = hardware.recommend(self._hw(), CATALOG)
        assert {m["fit"] for m in ranked} == {"unknown"}

    def test_detect_never_raises_on_this_machine(self):
        hw = hardware.detect()
        assert hw.cpu_count >= 1
        assert hw.os and hw.arch

    def test_shipped_catalog_is_well_formed(self):
        catalog = hardware.load_catalog()
        assert catalog, "the shipped catalogue should not be empty"
        for m in catalog:
            assert {"id", "name", "size_mb", "params", "good_for"} <= set(m), m


class TestDoctor:
    async def test_no_key_of_its_own_is_a_warning_not_a_failure(self, monkeypatch):
        """This used to assert FAIL — "Sensei cannot answer anything" — and that
        was wrong for the most common setup there is.

        The gateway forwards whatever credential the client sent and only falls
        back to a server-configured key when the client sends none. A Claude
        Code or Copilot subscription therefore routes through Sensei with no key
        configured here at all: the tool authenticates as itself and Sensei only
        compresses on the way past. Verified against the real thing — a request
        carrying an OAuth bearer reaches Anthropic and comes back with
        `authentication_error`, which is Anthropic answering, not Sensei
        refusing.

        What genuinely needs a key of Sensei's own is the built-in chat, RAG and
        the agent — the parts that originate a request rather than relay one.
        So the check warns about those and says so.
        """
        monkeypatch.setattr(doctor_mod, "_ollama_running", _false)
        monkeypatch.setattr(doctor_mod, "_configured_providers", list)

        checks = await doctor_mod.collect()
        by_name = {c.name: c for c in checks}
        assert by_name["Model access"].status == doctor_mod.WARN
        assert "gateway still works" in by_name["Model access"].detail
        assert "Ollama" in by_name["Model access"].fix

    async def test_exposed_without_auth_is_a_failure(self, monkeypatch):
        monkeypatch.setattr(doctor_mod.settings, "host", "0.0.0.0")
        monkeypatch.setattr(doctor_mod.settings, "auth_enabled", False)

        by_name = {c.name: c for c in await doctor_mod.collect()}
        assert by_name["Auth"].status == doctor_mod.FAIL
        assert by_name["Bind address"].status == doctor_mod.WARN

    async def test_loopback_without_auth_is_fine(self, monkeypatch):
        monkeypatch.setattr(doctor_mod.settings, "host", "127.0.0.1")
        monkeypatch.setattr(doctor_mod.settings, "auth_enabled", False)

        by_name = {c.name: c for c in await doctor_mod.collect()}
        assert by_name["Auth"].status == doctor_mod.OK
        assert by_name["Bind address"].status == doctor_mod.OK

    async def test_every_failure_carries_a_fix(self):
        for c in await doctor_mod.collect():
            if c.status == doctor_mod.FAIL:
                assert c.fix, f"{c.name} fails without telling the user what to do"

    async def test_render_is_plain_text_without_color(self):
        out = doctor_mod.render(await doctor_mod.collect(), color=False)
        assert "\033[" not in out


async def _false() -> bool:
    return False

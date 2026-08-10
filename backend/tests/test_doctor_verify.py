"""Tests for `sensei doctor --verify`.

Everything else `doctor` reports is a static check — a file exists, a port is
free, a key is set. None of that can tell you whether a request actually reaches
the gateway and comes back compressed, which is the only property the user cares
about and the only one `setup-tools` cannot confirm for itself.

The distinction these tests protect is between *compression is broken* and
*you have not added an API key yet*. Collapsing those two into one red line is
how a working install gets thrown away.
"""

from __future__ import annotations

import json

import httpx
import pytest

from sensei.cli import doctor


def _mock_transport(handler):
    """Patch httpx.AsyncClient.post with a canned response."""

    async def post(self, url, **kwargs):
        return handler(url, kwargs)

    return post


@pytest.fixture
def no_wired_tools(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sensei.integrations._read_manifest", lambda: {"version": 1, "entries": []})


def _reply(status: int, headers: dict[str, str], body: str = "{}") -> httpx.Response:
    return httpx.Response(status_code=status, headers=headers, text=body)


def _statuses(checks: list[doctor.Check]) -> dict[str, str]:
    return {c.name: c.status for c in checks}


def doctor_endpoints(command: str):
    """An Endpoints whose MCP command is whatever the test needs."""
    from sensei.integrations import Endpoints

    return Endpoints(
        anthropic="http://127.0.0.1:7000",
        openai="http://127.0.0.1:7000/v1",
        mcp_command=command,
        mcp_args=("mcp",),
    )


async def test_a_dead_server_says_how_to_start_it(monkeypatch: pytest.MonkeyPatch) -> None:
    async def post(self, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", post)

    checks = await doctor.verify()
    assert _statuses(checks) == {"Gateway": doctor.FAIL}
    assert "sensei up" in checks[0].fix


async def test_compression_is_confirmed_even_without_an_upstream(
    monkeypatch: pytest.MonkeyPatch, no_wired_tools
) -> None:
    """The important case. A machine mid-setup has no key, so the model call
    502s — but the savings headers are attached before forwarding, so this can
    still prove the half that matters is working."""
    monkeypatch.setattr(
        httpx.AsyncClient,
        "post",
        _mock_transport(
            lambda url, kw: _reply(
                502,
                {
                    "X-Sensei-Tokens-Saved": "497",
                    "X-Sensei-Compression-Ratio": "0.201",
                    "X-Sensei-Compression-Enabled": "true",
                },
                '{"error":{"message":"No API key."}}',
            )
        ),
    )

    status = _statuses(await doctor.verify())
    assert status["Gateway"] == doctor.OK
    assert status["Compression"] == doctor.OK
    # Not a failure: it is a different problem with a different fix.
    assert status["Upstream"] == doctor.WARN


async def test_zero_savings_on_the_probe_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, no_wired_tools
) -> None:
    """The probe is 30 near-identical records. Anything that compresses at all
    saves something on it, so zero means the pipeline is broken, not that the
    payload was unlucky."""
    monkeypatch.setattr(
        httpx.AsyncClient,
        "post",
        _mock_transport(
            lambda url, kw: _reply(
                200, {"X-Sensei-Tokens-Saved": "0", "X-Sensei-Compression-Enabled": "true"}
            )
        ),
    )

    assert _statuses(await doctor.verify())["Compression"] == doctor.FAIL


async def test_compression_switched_off_is_a_warning_not_a_failure(
    monkeypatch: pytest.MonkeyPatch, no_wired_tools
) -> None:
    monkeypatch.setattr(
        httpx.AsyncClient,
        "post",
        _mock_transport(
            lambda url, kw: _reply(
                200, {"X-Sensei-Tokens-Saved": "0", "X-Sensei-Compression-Enabled": "false"}
            )
        ),
    )

    checks = await doctor.verify()
    compression = next(c for c in checks if c.name == "Compression")
    assert compression.status == doctor.WARN
    assert "SENSEI_COMPRESSION_ENABLED" in compression.detail


async def test_missing_headers_are_reported_as_a_bug(
    monkeypatch: pytest.MonkeyPatch, no_wired_tools
) -> None:
    """Something answered on the port, but it was not Sensei."""
    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_transport(lambda url, kw: _reply(200, {})))

    checks = await doctor.verify()
    compression = next(c for c in checks if c.name == "Compression")
    assert compression.status == doctor.FAIL
    assert "issue" in compression.fix


class TestWiredTools:
    def test_a_tool_pointing_at_the_wrong_port_is_caught(self, tmp_path, monkeypatch) -> None:
        """The most common way a working setup breaks: SENSEI_PORT changes
        after `setup-tools` ran, and every tool's own error message for that
        says "connection refused" without mentioning Sensei."""
        config = tmp_path / "settings.json"
        config.write_text('{"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:7000"}}')
        monkeypatch.setattr(
            "sensei.integrations._read_manifest",
            lambda: {"entries": [{"tool_id": "claude-code", "path": str(config)}]},
        )

        checks = doctor._wired_tool_checks("http://127.0.0.1:9999")
        assert checks[0].status == doctor.FAIL
        assert "claude-code" in checks[0].detail
        assert "setup-tools" in checks[0].fix

    def test_an_mcp_only_tool_is_not_reported_as_stale(self, tmp_path, monkeypatch) -> None:
        """Found by running it against a real setup.

        Claude Desktop, Cursor and Windsurf are wired by spawning `sensei mcp`
        as a subprocess. Their config files contain the *command* and no URL at
        all — correctly. Checking only for the base URL reported every healthy
        one of them as broken, and told the user to re-run setup-tools, which
        would have changed nothing.
        """
        config = tmp_path / "claude_desktop_config.json"
        config.write_text(
            '{"mcpServers": {"sensei": {"command": "/opt/sensei/sensei", "args": ["mcp"]}}}'
        )
        monkeypatch.setattr(
            "sensei.integrations._read_manifest",
            lambda: {"entries": [{"tool_id": "claude-desktop", "path": str(config)}]},
        )
        monkeypatch.setattr(
            "sensei.integrations.endpoints",
            lambda: doctor_endpoints("/opt/sensei/sensei"),
        )

        checks = doctor._wired_tool_checks("http://127.0.0.1:7000")
        assert checks[0].status == doctor.OK

    def test_a_windows_path_survives_json_escaping(self, tmp_path, monkeypatch) -> None:
        r"""The second half of the same bug, and the reason it took two goes.

        JSON escapes backslashes, so a Windows path is stored with doubled
        separators and a plain substring test never matches the path as Python
        knows it. Every Windows user with an MCP-wired tool would be told their
        working setup was broken.
        """
        exe = r"C:\Program Files\Sensei\Sensei.exe"
        config = tmp_path / "claude_desktop_config.json"
        config.write_text(json.dumps({"mcpServers": {"sensei": {"command": exe, "args": ["mcp"]}}}))
        assert "\\\\" in config.read_text(encoding="utf-8")  # the escaping is real

        monkeypatch.setattr(
            "sensei.integrations._read_manifest",
            lambda: {"entries": [{"tool_id": "claude-desktop", "path": str(config)}]},
        )
        monkeypatch.setattr("sensei.integrations.endpoints", lambda: doctor_endpoints(exe))

        assert doctor._wired_tool_checks("http://127.0.0.1:7000")[0].status == doctor.OK

    def test_an_mcp_tool_whose_binary_moved_is_caught(self, tmp_path, monkeypatch) -> None:
        """The staleness this kind of wiring actually suffers from."""
        config = tmp_path / "mcp.json"
        config.write_text('{"mcpServers": {"sensei": {"command": "/old/path/sensei"}}}')
        monkeypatch.setattr(
            "sensei.integrations._read_manifest",
            lambda: {"entries": [{"tool_id": "cursor", "path": str(config)}]},
        )
        monkeypatch.setattr(
            "sensei.integrations.endpoints",
            lambda: doctor_endpoints("/new/path/sensei"),
        )

        checks = doctor._wired_tool_checks("http://127.0.0.1:7000")
        # A warning, not a failure: the tool is wired, just to another copy.
        # Telling this user "the server moved, re-run setup-tools" would have
        # them rewire away from a working setup.
        assert checks[0].status == doctor.WARN
        assert "cursor" in checks[0].detail
        assert "different Sensei" in checks[0].detail

    def test_a_genuinely_dead_port_is_still_a_failure(self, tmp_path, monkeypatch) -> None:
        """No Sensei named anywhere — this one really is broken."""
        config = tmp_path / "settings.json"
        config.write_text('{"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:7000"}}')
        monkeypatch.setattr(
            "sensei.integrations._read_manifest",
            lambda: {"entries": [{"tool_id": "claude-code", "path": str(config)}]},
        )
        monkeypatch.setattr(
            "sensei.integrations.endpoints", lambda: doctor_endpoints("/usr/bin/nothing")
        )

        checks = doctor._wired_tool_checks("http://127.0.0.1:9999")
        assert checks[0].status == doctor.FAIL
        assert "setup-tools" in checks[0].fix

    def test_a_correctly_wired_tool_passes(self, tmp_path, monkeypatch) -> None:
        config = tmp_path / "settings.json"
        config.write_text('{"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:7000"}}')
        monkeypatch.setattr(
            "sensei.integrations._read_manifest",
            lambda: {"entries": [{"tool_id": "claude-code", "path": str(config)}]},
        )

        checks = doctor._wired_tool_checks("http://127.0.0.1:7000")
        assert checks[0].status == doctor.OK

    def test_a_deleted_config_is_reported(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            "sensei.integrations._read_manifest",
            lambda: {"entries": [{"tool_id": "cursor", "path": str(tmp_path / "gone.json")}]},
        )

        checks = doctor._wired_tool_checks("http://127.0.0.1:7000")
        assert checks[0].status == doctor.FAIL
        assert "config gone" in checks[0].detail

    def test_no_wired_tools_suggests_setup_tools(self, monkeypatch) -> None:
        monkeypatch.setattr("sensei.integrations._read_manifest", lambda: {"entries": []})
        checks = doctor._wired_tool_checks("http://127.0.0.1:7000")
        assert checks[0].status == doctor.WARN
        assert "sensei setup-tools" in checks[0].fix

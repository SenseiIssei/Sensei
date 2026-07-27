"""Tests for the MCP server.

These call the tools the way a client does — through the server's own dispatch,
not by importing the Python functions — so a change to a tool name, schema or
return shape breaks the test rather than silently breaking every MCP client.
"""

from __future__ import annotations

import json

import pytest

from sensei import mcp_server

mcp = pytest.importorskip("mcp", reason="needs the optional 'mcp' extra")


@pytest.fixture
def server(tmp_path, monkeypatch):
    # Point the CCR cache at a temp dir and rebuild the cached pipeline so the
    # module-level singletons don't leak between tests.
    monkeypatch.setattr("sensei.config.settings.ccr_cache_dir", str(tmp_path / "ccr"))
    monkeypatch.setattr(mcp_server, "_router", None)
    monkeypatch.setattr(mcp_server, "_store", None)
    return mcp_server.build_server()


async def call(server, name: str, **kwargs) -> str:
    """Invoke a tool the way a client would, and return its text payload."""
    result = await server.call_tool(name, kwargs)
    # FastMCP returns (content_blocks, structured) across recent versions;
    # older ones return just the blocks.
    blocks = result[0] if isinstance(result, tuple) else result
    return "".join(getattr(b, "text", "") for b in blocks)


BIG_JSON = json.dumps(
    [{"id": i, "name": f"item-{i}", "url": f"https://x.test/{i}"} for i in range(40)]
)


class TestToolSurface:
    async def test_exposes_exactly_the_three_documented_tools(self, server):
        names = {t.name for t in await server.list_tools()}
        assert names == {"sensei_compress", "sensei_retrieve", "sensei_stats"}

    async def test_every_tool_describes_itself(self, server):
        for tool in await server.list_tools():
            assert tool.description, f"{tool.name} has no description"
            # A model picks tools from these strings; a bare name is useless.
            assert len(tool.description) > 40, f"{tool.name} description is too thin"

    async def test_instructions_tell_the_client_about_retrieval(self, server):
        # The whole safety story is that compression is reversible. If the
        # instructions don't say so, clients won't use it.
        assert "sensei_retrieve" in server.instructions


class TestCompress:
    async def test_compresses_json_and_reports_the_saving(self, server):
        out = json.loads(await call(server, "sensei_compress", text=BIG_JSON))
        assert out["content_type"] == "json"
        assert out["tokens_saved"] > 0
        assert out["percent_saved"] > 30
        assert len(out["compressed"]) < len(BIG_JSON)

    async def test_returns_a_ccr_id_so_the_original_is_recoverable(self, server):
        out = json.loads(await call(server, "sensei_compress", text=BIG_JSON))
        assert out["ccr_id"]

    async def test_content_type_can_be_forced(self, server):
        out = json.loads(await call(server, "sensei_compress", text=BIG_JSON, content_type="text"))
        assert out["content_type"] == "text"

    async def test_an_unknown_content_type_lists_the_valid_ones(self, server):
        out = json.loads(await call(server, "sensei_compress", text="hello", content_type="yaml"))
        assert "unknown content_type" in out["error"]
        assert "json" in out["error"]

    async def test_empty_input_is_an_error_not_a_crash(self, server):
        out = json.loads(await call(server, "sensei_compress", text=""))
        assert "error" in out


class TestRetrieve:
    async def test_round_trips_the_exact_original(self, server):
        """The point of CCR: what comes back is byte-identical."""
        compressed = json.loads(await call(server, "sensei_compress", text=BIG_JSON))
        restored = await call(server, "sensei_retrieve", ccr_id=compressed["ccr_id"])
        assert restored == BIG_JSON

    async def test_an_unknown_id_explains_why_rather_than_returning_nothing(self, server):
        out = json.loads(await call(server, "sensei_retrieve", ccr_id="does-not-exist"))
        assert "no entry" in out["error"]
        assert "expire" in out["hint"]


class TestStats:
    async def test_reports_version_and_cache_state(self, server):
        await call(server, "sensei_compress", text=BIG_JSON)
        out = json.loads(await call(server, "sensei_stats"))
        assert out["version"]
        assert "savings" in out
        assert out["ccr_cache"]["total_entries"] >= 1

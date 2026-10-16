"""The MCP proxy, against a real downstream MCP server running in-process.

The downstream stands in for a reverse-engineering server like REA or
GhidraMCP: many tools, and one that returns a long disassembly listing.
Everything goes through the MCP protocol on both sides — the agent talks to
Sensei's server, Sensei talks to the downstream with `mcp.Client`.
"""

from __future__ import annotations

import json

import pytest

mcp = pytest.importorskip("mcp", reason="needs the optional 'mcp' extra")

from mcp import Client  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

from sensei import mcp_server  # noqa: E402
from sensei.mcp_proxy import ProxyHub, load_config  # noqa: E402

LISTING = "\n".join(
    f"  {0x401000 + i * 4:x}:\t48 89 e5 90          \tmov    %rsp,%rbp" for i in range(2000)
)


def _downstream() -> MCPServer:
    server = MCPServer(name="fake-re")

    @server.tool(name="decompile_function", description="Decompile a function to C pseudocode.")
    def decompile_function(address: str) -> str:
        return f"int main(void) {{ return 0; }} /* {address} */"

    @server.tool(
        name="disassemble", description="Disassemble a function and list its instructions."
    )
    def disassemble(address: str) -> str:
        return LISTING

    @server.tool(name="list_strings", description="List printable strings found in the binary.")
    def list_strings() -> str:
        return "hello\nworld"

    return server


@pytest.fixture
async def proxy(tmp_path, monkeypatch):
    monkeypatch.setattr("sensei.config.settings.ccr_cache_dir", str(tmp_path / "ccr"))
    monkeypatch.setattr("sensei.config.settings.mcp_page_chars", 4000)
    monkeypatch.setattr(mcp_server, "_router", None)
    monkeypatch.setattr(mcp_server, "_store", None)
    hub = ProxyHub(servers={"re": _downstream()})
    yield mcp_server.build_server(hub=hub)
    await hub.close()


async def _text(client: Client, name: str, args: dict) -> str:
    result = await client.call_tool(name, args)
    return "".join(getattr(b, "text", "") for b in result.content)


async def test_agent_sees_two_proxy_tools_not_the_whole_surface(proxy):
    async with Client(proxy) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert {"sensei_find_tools", "sensei_call_tool"} <= names
    assert "disassemble" not in names


async def test_find_tools_ranks_by_keyword_and_returns_schemas(proxy):
    async with Client(proxy) as client:
        found = json.loads(await _text(client, "sensei_find_tools", {"query": "decompile"}))
    assert found["matches"][0]["tool"] == "decompile_function"
    assert "address" in json.dumps(found["matches"][0]["input_schema"])


async def test_find_tools_without_query_lists_everything_compactly(proxy):
    async with Client(proxy) as client:
        found = json.loads(await _text(client, "sensei_find_tools", {}))
    assert {t["tool"] for t in found["tools"]} == {
        "decompile_function",
        "disassemble",
        "list_strings",
    }
    assert all("input_schema" not in t for t in found["tools"])


async def test_long_results_are_compressed_and_paged(proxy):
    async with Client(proxy) as client:
        first = await _text(
            client,
            "sensei_call_tool",
            {"server": "re", "tool": "disassemble", "arguments": {"address": "0x401000"}},
        )
        assert len(first) < len(LISTING) / 4
        assert "48 89 e5" not in first  # opcode bytes dropped
        assert "401000: mov %rsp,%rbp" in first
        ccr_id = first.rsplit('ccr_id="', 1)[1].split('"', 1)[0]

        nxt = first.split("offset=", 1)[1].split(",", 1)[0]
        second = await _text(
            client,
            "sensei_retrieve",
            {"ccr_id": ccr_id, "offset": int(nxt), "max_chars": 4000, "view": "compressed"},
        )
        assert second and second != first

        original = await _text(client, "sensei_retrieve", {"ccr_id": ccr_id})
        assert original == LISTING


async def test_short_results_pass_through(proxy):
    async with Client(proxy) as client:
        out = await _text(
            client, "sensei_call_tool", {"server": "re", "tool": "list_strings", "arguments": {}}
        )
    assert out == "hello\nworld"


async def test_unknown_server_is_a_readable_error(proxy):
    async with Client(proxy) as client:
        out = json.loads(await _text(client, "sensei_call_tool", {"server": "nope", "tool": "x"}))
    assert out["servers"] == ["re"]


def test_config_accepts_claude_desktop_shape_and_skips_itself(tmp_path):
    path = tmp_path / "servers.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "rea": {"command": "npx", "args": ["-y", "rea-agents", "mcp"]},
                    "ghidra": {"url": "http://127.0.0.1:8089/mcp"},
                    "sensei": {"command": "sensei", "args": ["mcp"]},
                    "broken": {"args": ["no command"]},
                }
            }
        ),
        encoding="utf-8",
    )
    assert set(load_config(path)) == {"rea", "ghidra"}


def test_no_config_means_no_proxy_tools(tmp_path):
    assert load_config(tmp_path / "missing.json") == {}

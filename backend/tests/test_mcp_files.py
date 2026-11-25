"""`sensei_compress` on files, and what the MCP server may claim about itself."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from sensei import mcp_server

BIG_JSON = json.dumps(
    [{"id": i, "name": f"item-{i}", "url": f"https://x.test/{i}"} for i in range(40)]
)


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr("sensei.config.settings.ccr_cache_dir", str(tmp_path / "ccr"))
    monkeypatch.setattr(mcp_server, "_router", None)
    monkeypatch.setattr(mcp_server, "_store", None)
    return mcp_server.build_server()


async def call(server: Any, name: str, **kwargs: Any) -> str:
    result = await server.call_tool(name, kwargs)
    blocks = getattr(result, "content", None)
    if blocks is None:
        blocks = result[0] if isinstance(result, tuple) else result
    return "".join(getattr(b, "text", "") for b in blocks)


class TestFiles:
    """What the tool is for: output that never enters the conversation whole."""

    async def test_a_file_is_read_compressed_and_retrievable(self, server, tmp_path):
        target = tmp_path / "big.json"
        target.write_text(BIG_JSON, encoding="utf-8")
        out = json.loads(await call(server, "sensei_compress", path=str(target)))
        assert len(out["compressed"]) < len(BIG_JSON)
        assert await call(server, "sensei_retrieve", ccr_id=out["ccr_id"]) == BIG_JSON

    async def test_code_in_a_file_stays_exact(self, server, tmp_path):
        code = "import os\n\n# keep me\ndef f():\n    return 1  # and me\n" * 4
        target = tmp_path / "a.py"
        target.write_bytes(code.encode())
        out = json.loads(await call(server, "sensei_compress", path=str(target)))
        assert out["compressed"] == code

    async def test_what_cannot_be_read_says_why(self, server, tmp_path, monkeypatch):
        (tmp_path / "blob").write_bytes(bytes([0, 1, 2]) * 50)
        (tmp_path / "big.log").write_text("x" * 200, encoding="utf-8")
        monkeypatch.setattr(mcp_server, "_MAX_FILE", 180)
        for path, why in [
            (str(tmp_path / "missing"), "no file"),
            (str(tmp_path), "no file"),
            ("relative.log", "absolute"),
            (str(tmp_path / "big.log"), "too large"),
            (str(tmp_path / "blob"), "not a text file"),
        ]:
            out = json.loads(await call(server, "sensei_compress", path=path))
            assert why in out["error"], path

    async def test_remote_clients_cannot_read_files(self):
        remote = mcp_server.build_server(local_files=False)
        (tool,) = [t for t in await remote.list_tools() if t.name == "sensei_compress"]
        schema = getattr(tool, "input_schema", None) or tool.inputSchema
        assert "path" not in schema["properties"]
        assert "path=" not in remote.instructions

    async def test_other_scripts_are_not_escaped(self, server):
        out = await call(server, "sensei_compress", text="日本語のログ " * 40)
        assert "日本語" in out


class TestHonesty:
    async def test_only_a_file_counts_as_saved(self, server, tmp_path: Path, monkeypatch):
        """A text argument was written by the model, token by token, already."""
        calls: list[dict] = []

        class Tracker:
            def record(self, savings, **_):
                calls.append(savings)

        monkeypatch.setattr("sensei.savings.get_savings_tracker", Tracker)
        await call(server, "sensei_compress", text=BIG_JSON)
        assert calls == []
        target = tmp_path / "big.json"
        target.write_text(BIG_JSON, encoding="utf-8")
        await call(server, "sensei_compress", path=str(target))
        assert calls[0]["tokens_saved"] > 0

    async def test_no_percentage_is_promised(self, server):
        texts = [server.instructions, *(t.description for t in await server.list_tools())]
        assert not [t for t in texts if "%" in t]

"""`sensei_read_file`, and what the MCP server may claim about itself."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from sensei import mcp_server
from sensei.config import settings

BIG_JSON = json.dumps(
    [{"id": i, "name": f"item-{i}", "url": f"https://x.test/{i}"} for i in range(40)]
)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(settings, "ccr_cache_dir", str(tmp_path / "ccr"))
    monkeypatch.setattr(settings, "mcp_file_roots", str(root))
    monkeypatch.setattr(mcp_server, "_router", None)
    monkeypatch.setattr(mcp_server, "_store", None)
    return root


@pytest.fixture
def server(root: Path) -> Any:
    return mcp_server.build_server()


async def call(server: Any, name: str, **kwargs: Any) -> str:
    result = await server.call_tool(name, kwargs)
    blocks = getattr(result, "content", None)
    if blocks is None:
        blocks = result[0] if isinstance(result, tuple) else result
    return "".join(getattr(b, "text", "") for b in blocks)


async def names(server: Any) -> set[str]:
    return {t.name for t in await server.list_tools()}


class TestOffUnlessAskedFor:
    """A model must not gain file access because a compression tool was installed."""

    async def test_not_offered_by_default(self, root, monkeypatch) -> None:
        monkeypatch.setattr(settings, "mcp_file_roots", "")
        plain = mcp_server.build_server()
        assert "sensei_read_file" not in await names(plain)
        assert "sensei_read_file" not in plain.instructions

    async def test_not_offered_to_remote_clients(self, root) -> None:
        assert "sensei_read_file" not in await names(mcp_server.build_server(local_files=False))

    async def test_the_old_tool_did_not_change_what_it_can_do(self, server) -> None:
        (tool,) = [t for t in await server.list_tools() if t.name == "sensei_compress"]
        schema = getattr(tool, "input_schema", None) or tool.inputSchema
        assert set(schema["properties"]) == {"text", "content_type"}


class TestReading:
    async def test_compressed_and_retrievable(self, server, root) -> None:
        (root / "big.json").write_text(BIG_JSON, encoding="utf-8")
        out = await call(server, "sensei_read_file", path=str(root / "big.json"))
        assert len(out) < len(BIG_JSON)
        ccr_id = out.split('ccr_id="')[1].split('"')[0]
        assert await call(server, "sensei_retrieve", ccr_id=ccr_id) == BIG_JSON

    async def test_code_stays_exact(self, server, root) -> None:
        code = "import os\n\n# keep me\ndef f():\n    return 1  # and me\n" * 4
        (root / "a.py").write_bytes(code.encode())
        assert await call(server, "sensei_read_file", path=str(root / "a.py")) == code

    async def test_a_large_file_comes_in_pages(self, server, root) -> None:
        code = "def function_number_{0}():\n    return {0}\n"
        text = "import os\n" + "".join(code.format(i) for i in range(5000))
        (root / "big.py").write_bytes(text.encode())
        out = await call(server, "sensei_read_file", path=str(root / "big.py"))
        assert len(out) < settings.mcp_page_chars + 500
        assert "Next page" in out
        ccr_id = out.split('ccr_id="')[1].split('"')[0]
        assert await call(server, "sensei_retrieve", ccr_id=ccr_id) == text

    @pytest.mark.parametrize(
        ("path", "why"),
        [
            ("{root}/missing", "no file"),
            ("{root}", "no file"),
            ("relative.log", "absolute"),
            ("{root}/../secret.txt", "outside"),
            ("{root}/.env", "hidden"),
            ("{root}/.git/config", "hidden"),
            ("//host/share/x", "outside"),
            ("\\\\host\\share\\x", "outside"),
            ("\\/host/share/x", "outside"),
            ("\\\\?\\C:\\Windows\\win.ini", "outside"),
            ("{root}/blob", "not a text file"),
            ("{root}/big.log", "too large"),
        ],
    )
    async def test_what_is_refused(self, server, root, monkeypatch, path, why) -> None:
        (root.parent / "secret.txt").write_text("secret", encoding="utf-8")
        (root / ".env").write_text("KEY=1", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text("x", encoding="utf-8")
        (root / "blob").write_bytes(bytes([0, 1, 2]) * 50)
        (root / "big.log").write_text("x" * 200, encoding="utf-8")
        monkeypatch.setattr(mcp_server, "_MAX_FILE", 180)
        out = await call(server, "sensei_read_file", path=path.format(root=root))
        assert why in json.loads(out)["error"]

    async def test_a_link_does_not_lead_out(self, server, root) -> None:
        (root.parent / "secret.txt").write_text("secret", encoding="utf-8")
        try:
            os.symlink(root.parent / "secret.txt", root / "link.txt")
        except OSError:
            pytest.skip("links need a privilege on this Windows")
        out = await call(server, "sensei_read_file", path=str(root / "link.txt"))
        assert "outside" in json.loads(out)["error"]


class TestHonesty:
    async def test_only_a_file_counts_as_saved(self, server, root, monkeypatch) -> None:
        """A text argument was written by the model, token by token, already."""
        calls: list[dict] = []

        class Tracker:
            def record(self, savings, **_):
                calls.append(savings)

        monkeypatch.setattr("sensei.savings.get_savings_tracker", Tracker)
        await call(server, "sensei_compress", text=BIG_JSON)
        assert calls == []
        (root / "big.json").write_text(BIG_JSON, encoding="utf-8")
        await call(server, "sensei_read_file", path=str(root / "big.json"))
        assert calls[0]["tokens_saved"] > 0

    async def test_no_percentage_is_promised(self, server) -> None:
        texts = [server.instructions, *(t.description for t in await server.list_tools())]
        assert not [t for t in texts if "%" in t]

    async def test_other_scripts_are_not_escaped(self, server) -> None:
        out = await call(server, "sensei_compress", text="日本語のログ " * 40)
        assert "日本語" in out

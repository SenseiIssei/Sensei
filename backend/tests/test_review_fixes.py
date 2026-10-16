"""Regression tests for problems found in review of the 0.2 work.

Each test names the scenario that went wrong; none of them passed before the
fix it guards.
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx
import pytest

from sensei.compression.codecomp import CodeCompressor
from sensei.compression.router import ContentRouter
from sensei.config import settings
from sensei.usage import UsageSniffer

# ─── code compression ────────────────────────────────────────────────────────


def test_a_triple_quoted_argument_is_not_a_docstring():
    src = (
        "import textwrap\n\n"
        "def q():\n"
        '    """Doc."""\n'
        "    return textwrap.dedent(\n"
        '        """\n'
        "        SELECT 1  # keep\n"
        '        """\n'
        "    )\n"
    )
    out = CodeCompressor().compress(src)
    assert "SELECT 1  # keep" in out
    assert "Doc." not in out


def test_a_javascript_regex_literal_is_not_a_comment():
    src = "function f(url) {\n  return url.replace(/^\\/\\//, ''); // strip\n}\n"
    out = CodeCompressor().compress(src)
    assert "url.replace(/^\\/\\//, '');" in out
    assert "strip" not in out


# ─── edit targets ────────────────────────────────────────────────────────────


def test_a_config_file_read_by_an_agent_stays_byte_exact():
    package_json = json.dumps({"name": "app", "scripts": {"build": "vite build"}}, indent=2)
    r = ContentRouter(enable_caching=False).compress(package_json * 1, edit_target=True)
    assert r.compressed == package_json


def test_api_output_arrays_still_compress_as_tool_results():
    """One-line JSON is an API or MCP response and compresses. Pretty-printed
    JSON read as a tool result may be a fixture or data file on disk that the
    model edits next, so it stays byte-exact, arrays included."""
    data = [{"id": i, "name": f"n{i}", "ok": True} for i in range(30)]
    router = ContentRouter(enable_caching=False)
    api = json.dumps(data)
    assert len(router.compress(api, edit_target=True).compressed) < len(api)
    on_disk = json.dumps(data, indent=2)
    assert router.compress(on_disk, edit_target=True).compressed == on_disk


def test_protected_content_keeps_invisible_characters():
    code = "def f():\n    return 1\u200b\n\n\ndef g():\n    return 2\n"
    r = ContentRouter(enable_caching=False).compress(code, edit_target=True)
    assert r.compressed == code


# ─── usage from large streamed events ────────────────────────────────────────


def test_usage_survives_a_huge_responses_completed_event():
    event = {
        "type": "response.completed",
        "response": {
            "instructions": "x" * 200_000,
            "usage": {
                "input_tokens": 9000,
                "output_tokens": 12,
                "input_tokens_details": {"cached_tokens": 8000},
            },
        },
    }
    data = f"data: {json.dumps(event)}\n\n".encode()
    sniffer = UsageSniffer()
    for i in range(0, len(data), 4096):
        sniffer.feed(data[i : i + 4096])
    usage = sniffer.close()
    assert usage.prompt == 9000 and usage.cache_read == 8000


# ─── MCP paging ──────────────────────────────────────────────────────────────


def test_paging_always_moves_forward():
    from sensei.mcp_server import _page

    text = "\n".join(f"line {i}" for i in range(500))
    offset, seen = 0, 0
    while offset is not None:
        page, nxt = _page(text, offset, 37)
        assert nxt is None or nxt > offset
        seen += len(page)
        offset = nxt
    assert seen == len(text)
    # A nonsensical page size is clamped rather than looping.
    _, nxt = _page(text, 100, -10)
    assert nxt is None or nxt > 100


# ─── MCP proxy connection lifecycle ──────────────────────────────────────────


class _FakeClient:
    """Stands in for mcp.Client: counts connections; the first one dies."""

    instances = 0
    delay = 0.0

    def __init__(self, target, **_):
        type(self).instances += 1
        self.n = type(self).instances

    async def __aenter__(self):
        await asyncio.sleep(type(self).delay)
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, args):
        if self.n == 1:
            raise ConnectionError("Connection closed")
        return f"ok from connection {self.n}"


@pytest.fixture
def fake_mcp(monkeypatch):
    mcp = pytest.importorskip("mcp")
    _FakeClient.instances = 0
    _FakeClient.delay = 0.0
    monkeypatch.setattr(mcp, "Client", _FakeClient)
    return _FakeClient


async def test_a_dead_server_is_reconnected(fake_mcp):
    from sensei.mcp_proxy import ProxyHub

    hub = ProxyHub(servers={"re": object()})
    with pytest.raises(ConnectionError):
        await hub.call("re", "t", {})
    assert await hub.call("re", "t", {}) == "ok from connection 2"
    await hub.close()


async def test_one_cancelled_caller_does_not_cancel_the_others(fake_mcp):
    from sensei.mcp_proxy import ProxyHub

    fake_mcp.instances = 1  # skip the dying first connection
    fake_mcp.delay = 0.2
    hub = ProxyHub(servers={"re": object()})
    first = asyncio.create_task(hub.call("re", "t", {}))
    second = asyncio.create_task(hub.call("re", "t", {}))
    await asyncio.sleep(0.05)
    first.cancel()
    assert await second == "ok from connection 2"
    await hub.close()


# ─── gateway ─────────────────────────────────────────────────────────────────


@pytest.fixture
def upstream(monkeypatch, tmp_path):
    from sensei import savings as savings_mod
    from sensei.routers import gateway

    sent: list[httpx.Request] = []
    handlers: dict[str, object] = {}

    def factory(base_url: str) -> httpx.AsyncClient:
        def dispatch(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            handler = handlers.get(base_url.rstrip("/")) or handlers.get("*")
            if handler is None:
                raise httpx.ConnectError("no route", request=request)
            return handler(request)

        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(dispatch))

    monkeypatch.setattr(gateway, "_pooled_client", factory)
    monkeypatch.setattr(settings, "upstream_retry_max_wait", 0.0)
    monkeypatch.setattr(settings, "savings_db", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(settings, "output_shaper", False)
    savings_mod.reset_savings_tracker()
    yield sent, handlers
    savings_mod.reset_savings_tracker()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from sensei.main import app

    return TestClient(app)


def test_count_tokens_is_redacted_like_a_turn(client, upstream, monkeypatch):
    sent, handlers = upstream
    monkeypatch.setattr(settings, "redaction_enabled", True)
    handlers["*"] = lambda r: httpx.Response(200, json={"input_tokens": 3})
    secret = "sk-ant-api03-" + "Z" * 40
    client.post(
        "/v1/messages/count_tokens",
        json={"model": "m", "messages": [{"role": "user", "content": f"key {secret}"}]},
        headers={"x-api-key": "k"},
    )
    assert secret not in sent[0].content.decode()


def test_compact_is_redacted_and_never_falls_back(client, upstream, monkeypatch):
    sent, handlers = upstream
    monkeypatch.setattr(settings, "redaction_enabled", True)
    monkeypatch.setattr(settings, "fallback_enabled", True)
    monkeypatch.setattr(settings, "upstream_retries", 0)
    monkeypatch.setattr(settings, "api_provider", "openai")
    handlers[settings.openai_api_base_url.rstrip("/")] = lambda r: httpx.Response(503, json={})
    handlers["http://localhost:11434/v1"] = lambda r: httpx.Response(200, json={"output": []})
    secret = "sk-proj-" + "Q" * 48
    resp = client.post(
        "/v1/responses/compact",
        json={"model": "m", "input": [{"role": "user", "content": f"token {secret}"}]},
        headers={"Authorization": "Bearer k"},
    )
    assert resp.status_code == 503
    assert all("11434" not in str(r.url) for r in sent)
    assert secret not in sent[0].content.decode()


def test_a_read_timeout_is_not_retried(client, upstream, monkeypatch):
    sent, handlers = upstream
    monkeypatch.setattr(settings, "upstream_retries", 3)
    monkeypatch.setattr(settings, "fallback_enabled", False)

    def slow(request):
        raise httpx.ReadTimeout("generating", request=request)

    handlers["*"] = slow
    resp = client.post(
        "/v1/messages",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        headers={"x-api-key": "k"},
    )
    assert resp.status_code == 502
    assert len(sent) == 1  # once, not four times billed


# ─── autostart and update ────────────────────────────────────────────────────


def test_systemd_exec_line_survives_awkward_paths():
    from sensei.cli.system import _unit_quote

    line = _unit_quote(["/home/o'neil/my apps/sensei", "up", "50%"])
    assert line == '"/home/o\'neil/my apps/sensei" "up" "50%%"'


def test_desktop_exec_line_escapes_per_spec():
    from sensei.cli.system import _desktop_quote

    assert _desktop_quote(["/opt/x/sensei", "tray"]) == "/opt/x/sensei tray"
    assert _desktop_quote(["/home/a b/sensei"]) == '"/home/a b/sensei"'
    assert _desktop_quote(["/p/$x"]) == '"/p/\\\\$x"'


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_an_unwritable_install_dir_is_not_replaced(tmp_path, monkeypatch):
    from sensei.cli import system

    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "sensei"
    exe.write_bytes(b"")
    bindir.chmod(0o555)
    try:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        monkeypatch.delenv("APPIMAGE", raising=False)
        if __import__("os").access(bindir, __import__("os").W_OK):
            pytest.skip("running as root")
        assert system.install_kind() == "binary-readonly"
    finally:
        bindir.chmod(0o755)

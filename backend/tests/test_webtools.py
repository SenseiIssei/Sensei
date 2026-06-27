from __future__ import annotations

import sensei.agents.webtools as wt
from sensei.agents.toolbox import build_default_registry
from sensei.config import settings


def test_html_to_text_strips_tags_and_scripts():
    out = wt._html_to_text("<p>Hello <b>world</b></p><script>bad()</script>")
    assert out == "Hello world"


async def test_fetch_url_disabled(monkeypatch):
    monkeypatch.setattr(settings, "web_fetch_enabled", False)
    assert "error" in await wt.fetch_url("http://example.com")


async def test_fetch_url_blocks_private_hosts(monkeypatch):
    monkeypatch.setattr(settings, "web_fetch_enabled", True)
    assert "error" in await wt.fetch_url("http://127.0.0.1:7000/health")
    assert "error" in await wt.fetch_url("http://192.168.1.1/")
    assert "error" in await wt.fetch_url("http://localhost/x")


async def test_fetch_url_rejects_non_http(monkeypatch):
    monkeypatch.setattr(settings, "web_fetch_enabled", True)
    assert "error" in await wt.fetch_url("file:///etc/passwd")
    assert "error" in await wt.fetch_url("ftp://example.com/x")


async def test_web_search_requires_key(monkeypatch):
    monkeypatch.setattr(settings, "brave_api_key", "")
    assert "error" in await wt.web_search("anything")


async def test_run_python_disabled(monkeypatch):
    monkeypatch.setattr(settings, "code_exec_enabled", False)
    assert "error" in await wt.run_python("print(1)")


async def test_run_python_enabled(monkeypatch):
    monkeypatch.setattr(settings, "code_exec_enabled", True)
    monkeypatch.setattr(settings, "code_exec_timeout", 15)
    res = await wt.run_python("print(6 * 7)")
    assert res.get("exit_code") == 0
    assert "42" in res.get("stdout", "")


def test_registry_gates_run_python(monkeypatch):
    monkeypatch.setattr(settings, "code_exec_enabled", False)
    names = {t.name for t in build_default_registry().list()}
    assert "run_python" not in names
    assert {"fetch_url", "web_search"} <= names

    monkeypatch.setattr(settings, "code_exec_enabled", True)
    assert "run_python" in {t.name for t in build_default_registry().list()}

from __future__ import annotations

import json

import sensei.agents.toolbox as tb
import sensei.agents.webtools as webtools
import sensei.rag.store as store_mod
from sensei.agents.runner import run_agent
from sensei.agents.toolbox import build_default_registry, crawl_site, ingest_url
from sensei.config import settings
from sensei.models.base import ChatCompletion, Role, UsageStats
from sensei.rag.store import DocumentStore


class _ScriptedProvider:
    def __init__(self, responses):
        self._responses = list(responses)

    async def chat(self, messages, model=None, temperature=0.7, max_tokens=4096, stream=False):
        return ChatCompletion(
            id="x", model="fake", content=self._responses.pop(0), role=Role.assistant, usage=UsageStats()
        )


async def test_ingest_url_indexes(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_store", DocumentStore(tmp_path / "rag.json"))

    async def fake_core(url, max_chars=200_000):
        return {"url": url, "status": 200, "content": "Exampleland's capital is Exampleton, a fine city."}

    monkeypatch.setattr(webtools, "_fetch_core", fake_core)
    res = await ingest_url("http://example.com/wiki")
    assert res["indexed_chunks"] >= 1
    assert store_mod.get_store().search("capital Exampleton", 1)


async def test_ingest_url_passes_errors(monkeypatch):
    async def fake_core(url, max_chars=200_000):
        return {"error": "Refusing private/local address"}

    monkeypatch.setattr(webtools, "_fetch_core", fake_core)
    assert "error" in await ingest_url("http://localhost")


async def test_crawl_site_respects_disabled_flag(monkeypatch):
    monkeypatch.setattr(settings, "web_fetch_enabled", False)
    assert "error" in await crawl_site("http://example.com")


def test_registry_has_research_tools():
    names = {t.name for t in build_default_registry().list()}
    assert {"ingest_url", "crawl_site", "fetch_url", "web_search", "rag_search"} <= names


async def test_agent_research_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_root", str(tmp_path))
    monkeypatch.setattr(store_mod, "_store", DocumentStore(tmp_path / "rag.json"))

    async def fake_crawl(url, max_pages=8):
        store_mod.get_store().add_document(url, "The capital of Exampleland is Exampleton.")
        return {"pages_indexed": 1}

    monkeypatch.setattr(tb, "crawl_site", fake_crawl)

    provider = _ScriptedProvider([
        json.dumps({"tool": "crawl_site", "args": {"url": "http://example.com"}}),
        json.dumps({"tool": "rag_search", "args": {"query": "capital of Exampleland"}}),
        json.dumps({"answer": "The capital is Exampleton."}),
    ])
    result = await run_agent("what is the capital of Exampleland?", provider=provider, max_steps=5)
    assert result["stopped"] == "done"
    assert [s["tool"] for s in result["steps"]] == ["crawl_site", "rag_search"]
    assert "Exampleton" in json.dumps(result["steps"][1]["result"])

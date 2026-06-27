from __future__ import annotations

from fastapi.testclient import TestClient

import sensei.rag.store as rag_store
import sensei.watch as watchmod
from sensei.main import app
from sensei.rag.store import DocumentStore
from sensei.watch import WatchStore, check_watches


def test_watch_store_crud(tmp_path):
    s = WatchStore(tmp_path / "watch.json")
    wid = s.add("https://example.com", interval_minutes=15)
    assert len(s.list()) == 1
    assert s.list()[0]["url"] == "https://example.com"
    # Persists.
    assert len(WatchStore(tmp_path / "watch.json").list()) == 1
    assert s.remove(wid) is True
    assert s.list() == []


def test_due_respects_interval(tmp_path):
    import time

    s = WatchStore(tmp_path / "watch.json")
    wid = s.add("https://example.com", interval_minutes=10)
    assert len(s.due(time.time())) == 1  # never checked -> due
    s.update(wid, last_checked=time.time())
    assert s.due(time.time()) == []  # just checked -> not due


async def test_check_detects_change_and_indexes(tmp_path, monkeypatch):
    monkeypatch.setattr(watchmod, "_store", WatchStore(tmp_path / "watch.json"))
    monkeypatch.setattr(rag_store, "_store", DocumentStore(tmp_path / "rag.json"))

    content = {"v": "version one of the watched page with enough words to index here"}

    async def fake_fetch(url):
        return {"content": content["v"]}

    monkeypatch.setattr(watchmod, "fetch_url", fake_fetch)
    watchmod.get_watch_store().add("https://example.com/page", interval_minutes=1)

    # First check = baseline (no change reported) but indexed into RAG.
    assert await check_watches(force=True) == []
    assert rag_store.get_store().search("watched page", 1)

    # No change yet.
    assert await check_watches(force=True) == []

    # Now the page changes.
    content["v"] = "version two is completely different fresh content for the indexer"
    changes = await check_watches(force=True)
    assert len(changes) == 1 and changes[0]["url"] == "https://example.com/page"
    assert rag_store.get_store().search("completely different fresh", 1)


def test_watch_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(watchmod, "_store", WatchStore(tmp_path / "watch.json"))
    client = TestClient(app)
    wid = client.post("/api/watch", json={"url": "https://example.com", "interval_minutes": 30}).json()["id"]
    assert client.get("/api/watch").json()["watches"][0]["url"] == "https://example.com"
    assert client.delete(f"/api/watch/{wid}").json()["removed"] is True

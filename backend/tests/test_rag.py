from __future__ import annotations

from fastapi.testclient import TestClient

import sensei.rag.store as store_mod
from sensei.main import app
from sensei.rag.store import DocumentStore, chunk_text


def test_chunking_splits_and_hard_splits():
    text = "para one.\n\npara two is here.\n\n" + "x" * 2000
    chunks = chunk_text(text, target=200)
    assert len(chunks) >= 3  # two paras + hard-split of the long blob
    assert max(len(c) for c in chunks) <= 200 * 2


def test_store_relevance_and_persistence(tmp_path):
    path = tmp_path / "rag.json"
    s = DocumentStore(path)
    s.add_document("networking", "Configure the reverse proxy with Nginx or Caddy. Disable buffering for SSE.")
    s.add_document("security", "The vault encrypts API keys using AES. Redaction strips secrets before sending.")

    res = s.search("where are api keys stored in the vault", 1)
    assert res and res[0]["doc"] == "security"

    # Persists to disk.
    assert DocumentStore(path).search("api keys vault", 1)[0]["doc"] == "security"

    names = [d["name"] for d in s.list_documents()]
    assert names == ["networking", "security"]
    assert s.delete_document("security") >= 1
    assert s.search("api keys", 3) == []  # only networking left, no match


def test_search_empty_store(tmp_path):
    assert DocumentStore(tmp_path / "rag.json").search("anything") == []


def test_rag_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_store", DocumentStore(tmp_path / "rag.json"))
    client = TestClient(app)

    r = client.post(
        "/api/rag/documents",
        json={"name": "doc1", "content": "Sensei compresses prompts. The gateway speaks OpenAI and Anthropic."},
    )
    assert r.status_code == 200 and r.json()["chunks"] >= 1
    assert client.get("/api/rag/documents").json()["documents"][0]["name"] == "doc1"

    q = client.post("/api/rag/query", json={"query": "what does the gateway speak", "k": 2})
    assert q.status_code == 200 and len(q.json()["results"]) >= 1

    assert client.delete("/api/rag/documents/doc1").json()["removed_chunks"] >= 1


def test_rag_chat_requires_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_store", DocumentStore(tmp_path / "rag.json"))
    client = TestClient(app)
    resp = client.post("/api/rag/chat", json={"message": "anything"})
    assert resp.status_code == 404  # nothing indexed yet

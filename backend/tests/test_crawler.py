from __future__ import annotations

from fastapi.testclient import TestClient

import sensei.agents.crawler as cr
import sensei.rag.store as store_mod
from sensei.main import app
from sensei.rag.store import DocumentStore


def test_links_same_domain_only():
    html = (
        '<a href="/page2">two</a> <a href="https://example.com/p3">3</a> '
        '<a href="https://other.com/x">ext</a> <a href="#frag">f</a> '
        '<a href="mailto:a@b.com">m</a>'
    )
    links = cr._links(html, "https://example.com/", "example.com")
    assert "https://example.com/page2" in links
    assert "https://example.com/p3" in links
    assert all("other.com" not in u for u in links)


async def test_crawl_rejects_private_and_invalid():
    assert "error" in await cr.crawl_to_rag("http://127.0.0.1/")
    assert "error" in await cr.crawl_to_rag("ftp://example.com")


async def test_crawl_indexes_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_store", DocumentStore(tmp_path / "rag.json"))
    monkeypatch.setattr(cr, "_is_public_host", lambda h: True)

    pages = {
        "http://example.com/": '<a href="/page2">two</a> This is the home page with plenty of indexable content words to store here.',
        "http://example.com/page2": "Second page also has plenty of indexable content words to store in the knowledge base here.",
    }

    async def fake_fetch(client, url):
        url = url.split("#")[0]
        return (pages[url], url) if url in pages else None

    async def fake_robots(client, base):
        return []

    monkeypatch.setattr(cr, "_fetch", fake_fetch)
    monkeypatch.setattr(cr, "_robots_disallow", fake_robots)

    result = await cr.crawl_to_rag("http://example.com/", max_pages=10, max_depth=2)
    assert result["pages_indexed"] == 2
    docs = {d["name"] for d in store_mod.get_store().list_documents()}
    assert "http://example.com/" in docs and "http://example.com/page2" in docs
    # And the crawled content is now searchable.
    assert store_mod.get_store().search("second page content", 1)


def test_crawl_endpoint_rejects_private():
    client = TestClient(app)
    resp = client.post("/api/rag/crawl", json={"url": "http://localhost/x"})
    assert resp.status_code == 200
    assert "error" in resp.json()

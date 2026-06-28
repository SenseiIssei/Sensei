from __future__ import annotations

import json

from fastapi.testclient import TestClient

from sensei.agents.structured import extract_tables
from sensei.main import app
from sensei.models.base import ChatCompletion, Role, UsageStats


def test_extract_tables_header_keyed():
    html = """
    <table>
      <tr><th>Name</th><th>Price</th></tr>
      <tr><td>Widget</td><td>$10</td></tr>
      <tr><td>Gadget</td><td>$20</td></tr>
    </table>
    """
    tables = extract_tables(html)
    assert len(tables) == 1
    t = tables[0]
    assert t["headers"] == ["Name", "Price"]
    assert t["rows"][0] == {"Name": "Widget", "Price": "$10"}
    assert t["rows"][1]["Price"] == "$20"


def test_extract_tables_without_header():
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    tables = extract_tables(html)
    assert tables[0]["headers"] == []
    assert tables[0]["rows"] == [["a", "b"], ["c", "d"]]


def test_extract_endpoint_tables(monkeypatch):
    import sensei.agents.webtools as webtools

    async def _fake_fetch(url, max_chars=200_000, extract=True):
        return {"url": url, "status": 200, "content": "<table><tr><th>K</th></tr><tr><td>v</td></tr></table>"}

    monkeypatch.setattr(webtools, "_fetch_core", _fake_fetch)
    client = TestClient(app)
    resp = client.post("/api/extract", json={"url": "https://x.test", "tables": True})
    assert resp.status_code == 200
    assert resp.json()["tables"][0]["rows"][0] == {"K": "v"}


def test_extract_endpoint_fields(monkeypatch):
    import sensei.agents.webtools as webtools
    import sensei.models.registry as registry

    async def _fake_fetch(url, max_chars=200_000, extract=True):
        return {"url": url, "status": 200, "content": "Acme Corp was founded in 1999 in Berlin."}

    class _P:
        async def chat(self, messages, **kw):
            return ChatCompletion(
                id="x",
                model="f",
                content=json.dumps({"company": "Acme Corp", "year": 1999, "city": "Berlin"}),
                role=Role.assistant,
                usage=UsageStats(),
            )

    async def _get():
        return _P()

    monkeypatch.setattr(webtools, "_fetch_core", _fake_fetch)
    monkeypatch.setattr(registry, "get_provider", _get)
    client = TestClient(app)
    resp = client.post("/api/extract", json={"url": "https://x.test", "fields": ["company", "year", "city"]})
    assert resp.status_code == 200
    assert resp.json()["fields"] == {"company": "Acme Corp", "year": 1999, "city": "Berlin"}


def test_extract_endpoint_requires_input():
    client = TestClient(app)
    resp = client.post("/api/extract", json={"url": "https://x.test"})
    assert resp.status_code == 400

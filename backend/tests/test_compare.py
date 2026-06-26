from __future__ import annotations

from fastapi.testclient import TestClient

import sensei.routers.chat as chatmod
from sensei.main import app
from sensei.models.base import ChatCompletion, Role, UsageStats


class _FakeProvider:
    async def chat(self, messages, model=None, temperature=0.7, max_tokens=1024):
        return ChatCompletion(
            id="x",
            model=model or "m",
            content=f"reply from {model}",
            role=Role.assistant,
            usage=UsageStats(prompt_tokens=10, completion_tokens=5),
        )


async def _fake_get_provider():
    return _FakeProvider()


def test_compare_runs_all_models(monkeypatch):
    monkeypatch.setattr(chatmod, "get_provider", _fake_get_provider)
    client = TestClient(app)
    resp = client.post("/api/chat/compare", json={"message": "hi", "models": ["model-a", "model-b"]})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 2
    models = {r["model"] for r in data["results"]}
    assert models == {"model-a", "model-b"}
    assert all(r["content"].startswith("reply from") for r in data["results"])
    assert all(r["error"] is None for r in data["results"])


def test_compare_isolates_model_errors(monkeypatch):
    class _FlakyProvider:
        async def chat(self, messages, model=None, **kw):
            if model == "bad":
                raise RuntimeError("provider down")
            return ChatCompletion(id="x", model=model, content="ok", usage=UsageStats())

    async def _get():
        return _FlakyProvider()

    monkeypatch.setattr(chatmod, "get_provider", _get)
    client = TestClient(app)
    resp = client.post("/api/chat/compare", json={"message": "hi", "models": ["good", "bad"]})
    assert resp.status_code == 200
    by_model = {r["model"]: r for r in resp.json()["results"]}
    assert by_model["good"]["content"] == "ok"
    assert by_model["bad"]["error"] is not None  # one failure doesn't sink the rest


def test_compare_requires_models():
    client = TestClient(app)
    resp = client.post("/api/chat/compare", json={"message": "hi", "models": []})
    assert resp.status_code == 400

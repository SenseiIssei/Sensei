"""Tests for the first-run setup API."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from sensei.config import settings
from sensei.main import app
from sensei.routers import setup as setup_mod


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_ollama(monkeypatch):
    """Default to a machine with nothing configured — the first-run case."""

    async def _none() -> list[str]:
        return []

    monkeypatch.setattr(setup_mod, "_ollama_models", _none)
    # Ollama is in the catalog but has no key field — it is "configured" by
    # being reachable, not by a credential.
    for provider in setup_mod.PROVIDER_CATALOG:
        field = f"{provider}_api_key"
        if hasattr(settings, field):
            monkeypatch.setattr(settings, field, "")


class TestStatus:
    def test_reports_needing_setup_when_nothing_is_reachable(self, client):
        body = client.get("/api/setup/status").json()
        assert body["needs_setup"] is True
        assert body["ready"] is False
        assert body["configured_providers"] == []

    def test_a_configured_api_key_makes_it_ready(self, client, monkeypatch):
        monkeypatch.setattr(settings, "openrouter_api_key", "sk-test")
        body = client.get("/api/setup/status").json()
        assert body["ready"] is True
        assert "openrouter" in body["configured_providers"]

    def test_a_running_ollama_makes_it_ready_without_any_key(self, client, monkeypatch):
        async def _models() -> list[str]:
            return ["llama3.2:3b"]

        monkeypatch.setattr(setup_mod, "_ollama_models", _models)
        body = client.get("/api/setup/status").json()
        assert body["ready"] is True
        assert body["ollama"]["running"] is True
        assert body["ollama"]["models"] == ["llama3.2:3b"]

    def test_includes_hardware_and_a_local_recommendation(self, client):
        body = client.get("/api/setup/status").json()
        hw = body["hardware"]
        assert hw["cpu_count"] >= 1
        assert "usable_vram_mb" in hw
        # Either a concrete suggestion or an honest null — never a guess.
        assert body["recommended_local_model"] is None or "id" in body["recommended_local_model"]


class TestProviderModels:
    def test_unknown_provider_is_rejected(self, client):
        assert client.get("/api/setup/provider-models/not-a-provider").status_code == 400

    def test_without_a_key_it_says_so_instead_of_pretending(self, client):
        body = client.get("/api/setup/provider-models/openrouter").json()
        assert body["source"] == "catalog"
        assert "API key" in body["detail"]
        assert body["models"], "a fallback list should still be offered"

    def test_live_listing_is_used_when_the_provider_answers(self, client, monkeypatch):
        monkeypatch.setattr(settings, "openrouter_api_key", "sk-test")

        class _Resp:
            status_code = 200

            @staticmethod
            def json() -> dict:
                return {"data": [{"id": "zeta/model-2"}, {"id": "alpha/model-1"}]}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, *a, **kw):
                return _Resp()

        monkeypatch.setattr(setup_mod.httpx, "AsyncClient", lambda **kw: _Client())

        body = client.get("/api/setup/provider-models/openrouter").json()
        assert body["source"] == "live"
        assert body["models"] == ["alpha/model-1", "zeta/model-2"]  # sorted

    def test_a_rejected_key_is_reported_plainly(self, client, monkeypatch):
        monkeypatch.setattr(settings, "openrouter_api_key", "sk-bad")

        class _Resp:
            status_code = 401

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, *a, **kw):
                return _Resp()

        monkeypatch.setattr(setup_mod.httpx, "AsyncClient", lambda **kw: _Client())

        body = client.get("/api/setup/provider-models/openrouter").json()
        assert body["source"] == "catalog"
        assert "rejected" in body["detail"]

    def test_a_network_failure_falls_back_rather_than_500ing(self, client, monkeypatch):
        monkeypatch.setattr(settings, "openrouter_api_key", "sk-test")

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, *a, **kw):
                raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(setup_mod.httpx, "AsyncClient", lambda **kw: _Client())

        resp = client.get("/api/setup/provider-models/openrouter")
        assert resp.status_code == 200
        assert resp.json()["source"] == "catalog"

    def test_ollama_reports_how_to_start_it(self, client):
        body = client.get("/api/setup/provider-models/ollama").json()
        assert body["source"] == "catalog"
        assert "ollama serve" in body["detail"]

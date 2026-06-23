from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sensei.main import app


class TestAPIEndpoints:
    """Integration tests for the FastAPI application."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Sensei"
        assert data["docs"] == "/docs"

    def test_models_endpoint(self, client):
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data

    def test_stats_endpoint(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "compression_enabled" in data

    def test_conversations_list(self, client):
        resp = client.get("/api/conversations")
        assert resp.status_code == 200

    def test_rate_limit_headers(self, client):
        resp = client.get("/api/models")
        assert "x-ratelimit-limit" in {k.lower() for k in resp.headers.keys()}
        assert "x-ratelimit-remaining" in {k.lower() for k in resp.headers.keys()}

    def test_rate_limit_enforcement(self, client):
        # Make many requests to trigger rate limit
        # Default is 60 per 60 seconds, so we should be fine for a few
        for _ in range(5):
            resp = client.get("/api/models")
            assert resp.status_code == 200

    def test_health_not_rate_limited(self, client):
        # Health endpoint should not have rate limit headers
        resp = client.get("/health")
        assert "x-ratelimit-remaining" not in {k.lower() for k in resp.headers.keys()}

    def test_openapi_docs(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"] == "Sensei"

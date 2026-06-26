from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sensei.main import app
from sensei.routers.gateway import compress_request_messages


def _compressible_json() -> str:
    return json.dumps(
        [
            {"id": i, "name": f"user{i}", "active": True, "email": None, "role": "member"}
            for i in range(8)
        ]
    )


class TestCompressRequestMessages:
    def test_reduces_tokens_and_preserves_structure(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": _compressible_json()},
            {"role": "assistant", "content": "ok"},
        ]
        out, savings = compress_request_messages(messages)

        assert savings["compression_enabled"] is True
        assert savings["tokens_saved"] > 0
        assert savings["blocks_compressed"] == 1
        # Structure preserved: same count, same roles, in order.
        assert [m["role"] for m in out] == ["system", "user", "assistant"]
        # System and short messages untouched.
        assert out[0]["content"] == "You are a helpful assistant."
        assert out[2]["content"] == "ok"
        # The long user message was actually compressed.
        assert len(out[1]["content"]) < len(messages[1]["content"])

    def test_skips_structured_content(self):
        # Vision-style content (list of blocks) must pass through untouched.
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        ]
        out, savings = compress_request_messages(messages)
        assert out == messages
        assert savings["blocks_compressed"] == 0


class TestGatewayEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_v1_models(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 1
        assert "id" in data["data"][0]

    def test_chat_completions_invalid_messages(self, client):
        resp = client.post("/v1/chat/completions", json={"messages": "not-a-list"})
        assert resp.status_code == 400
        assert resp.json()["error"]["type"] == "invalid_request_error"

    def test_chat_completions_requires_upstream_key(self, client):
        # No upstream API key is configured in the test environment, so the
        # gateway should fail cleanly (502) rather than crash.
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": _compressible_json()}]},
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["type"] == "upstream_not_configured"
        # Savings are computed before forwarding, so the header is present.
        assert "x-sensei-tokens-saved" in {k.lower() for k in resp.headers}

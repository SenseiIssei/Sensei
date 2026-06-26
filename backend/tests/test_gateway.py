from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sensei.main import app
from sensei.routers.gateway import compress_anthropic_request, compress_request_messages


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

    def test_chat_completions_requires_upstream_key(self, client, monkeypatch):
        # Force "no key" regardless of any local .env so the test is deterministic.
        from sensei.config import settings

        monkeypatch.setattr(settings, "api_provider", "openrouter")
        monkeypatch.setattr(settings, "openrouter_api_key", "")
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": _compressible_json()}]},
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["type"] == "upstream_not_configured"
        # Savings are computed before forwarding, so the header is present.
        assert "x-sensei-tokens-saved" in {k.lower() for k in resp.headers}

    def test_messages_invalid(self, client):
        resp = client.post("/v1/messages", json={"messages": "nope"})
        assert resp.status_code == 400

    def test_messages_requires_key(self, client, monkeypatch):
        from sensei.config import settings

        monkeypatch.setattr(settings, "anthropic_api_key", "")
        resp = client.post(
            "/v1/messages",
            json={
                "model": "claude-3-5-sonnet",
                "max_tokens": 100,
                "system": "You are helpful.",
                "messages": [{"role": "user", "content": _compressible_json()}],
            },
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["type"] == "upstream_not_configured"
        assert "x-sensei-tokens-saved" in {k.lower() for k in resp.headers}


class TestCompressAnthropic:
    def test_compresses_system_and_messages(self, monkeypatch):
        from sensei.config import settings

        monkeypatch.setattr(settings, "gateway_compress_system", True)
        system, messages, savings = compress_anthropic_request(
            _compressible_json(),  # a big "system" prompt
            [
                {"role": "user", "content": _compressible_json()},
                {"role": "assistant", "content": [{"type": "text", "text": _compressible_json()}]},
            ],
        )
        assert savings["tokens_saved"] > 0
        assert savings["blocks_compressed"] == 3  # system + user str + assistant block
        assert len(system) < len(_compressible_json())
        # Block structure preserved.
        assert messages[1]["content"][0]["type"] == "text"

    def test_passes_through_non_text_blocks(self):
        _, messages, savings = compress_anthropic_request(
            None,
            [{"role": "user", "content": [{"type": "image", "source": {"x": 1}}]}],
        )
        assert messages[0]["content"][0]["type"] == "image"
        assert savings["blocks_compressed"] == 0

    def test_compresses_tool_results(self):
        # Claude-Code-style: a tool_result block carrying a big JSON payload.
        big = _compressible_json()
        _, messages, savings = compress_anthropic_request(
            "You are an agent.",
            [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": big}]}],
        )
        assert savings["tokens_saved"] > 0
        block = messages[0]["content"][0]
        assert block["type"] == "tool_result"  # block preserved
        assert len(block["content"]) < len(big)  # payload compressed

    def test_compresses_tool_result_text_blocks(self):
        big = _compressible_json()
        _, messages, _ = compress_anthropic_request(
            None,
            [{
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t2",
                             "content": [{"type": "text", "text": big}]}],
            }],
        )
        inner = messages[0]["content"][0]["content"][0]
        assert inner["type"] == "text"
        assert len(inner["text"]) < len(big)

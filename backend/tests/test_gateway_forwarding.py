"""The gateway end to end: what reaches the provider, and what comes back.

Every test here replaces the pooled upstream client with an
``httpx.MockTransport``, so a request goes through routing, compression,
policy, retries and response handling exactly as in production, and the
"provider" is a function that records what it was sent.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from sensei import savings as savings_mod
from sensei.config import settings
from sensei.main import app
from sensei.routers import gateway

Handler = Callable[[httpx.Request], httpx.Response]


def _rows(n: int = 30) -> str:
    return json.dumps(
        [{"id": i, "name": f"user{i}", "active": True, "role": "member"} for i in range(n)]
    )


PYTHON_FILE = '''import os
import sys


def colour():
    """Return the brand colour."""
    # a comment the Edit tool would need to match
    return "#16a34a"


def url():
    return "https://example.com/#top"  # trailing comment
'''


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Route every upstream base URL to a handler; collect what was sent."""
    sent: list[httpx.Request] = []
    handlers: dict[str, Handler] = {}

    def factory(base_url: str) -> httpx.AsyncClient:
        base = base_url.rstrip("/")

        def dispatch(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            handler = handlers.get(base) or handlers.get("*")
            if handler is None:
                raise httpx.ConnectError("no route", request=request)
            return handler(request)

        return httpx.AsyncClient(base_url=base, transport=httpx.MockTransport(dispatch))

    monkeypatch.setattr(gateway, "_pooled_client", factory)
    monkeypatch.setattr(settings, "upstream_retry_max_wait", 0.0)
    monkeypatch.setattr(settings, "redaction_enabled", False)
    monkeypatch.setattr(settings, "output_shaper", False)
    monkeypatch.setattr(settings, "gateway_preserve_cache", False)
    monkeypatch.setattr(settings, "fallback_enabled", False)
    monkeypatch.setattr(settings, "savings_persist", True)
    monkeypatch.setattr(settings, "savings_db", str(tmp_path / "ledger.db"))
    savings_mod.reset_savings_tracker()
    savings_mod.get_savings_tracker().ledger.clear()
    yield sent, handlers
    savings_mod.reset_savings_tracker()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


# ─── Responses API (Codex) ───────────────────────────────────────────────────


class TestResponsesCompression:
    def test_tool_output_json_is_compressed(self):
        body = {
            "model": "gpt-6.1-sol",
            "input": [
                {"type": "message", "role": "user", "content": "list users"},
                {"type": "function_call", "call_id": "c1", "name": "q", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "c1", "output": _rows()},
            ],
        }
        out, savings = gateway.compress_responses_request(body)
        assert savings["tokens_saved"] > 0
        assert len(out["input"][2]["output"]) < len(body["input"][2]["output"])
        # Calls and item ids are validated by the API — never rewritten.
        assert out["input"][1] == body["input"][1]
        assert out["input"][2]["call_id"] == "c1"

    def test_reasoning_items_pass_untouched(self):
        reasoning = {"type": "reasoning", "id": "rs_1", "encrypted_content": "gAAAA" * 200}
        body = {"input": [reasoning, {"role": "user", "content": _rows()}]}
        out, _ = gateway.compress_responses_request(body)
        assert out["input"][0] is reasoning

    def test_code_read_by_the_agent_stays_exact(self):
        body = {"input": [{"type": "function_call_output", "call_id": "c", "output": PYTHON_FILE}]}
        out, _ = gateway.compress_responses_request(body)
        assert out["input"][0]["output"] == PYTHON_FILE

    def test_text_parts_are_compressed(self):
        body = {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": _rows()},
                        {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
                    ],
                }
            ]
        }
        out, savings = gateway.compress_responses_request(body)
        parts = out["input"][0]["content"]
        assert len(parts[0]["text"]) < len(_rows())
        assert parts[1] == body["input"][0]["content"][1]
        assert savings["blocks_compressed"] == 1

    def test_endpoint_forwards_to_provider_responses(self, client, upstream, monkeypatch):
        sent, handlers = upstream
        monkeypatch.setattr(settings, "api_provider", "openai")
        handlers["*"] = lambda r: httpx.Response(
            200,
            json={
                "id": "resp_1",
                "output": [],
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 50,
                    "input_tokens_details": {"cached_tokens": 800},
                },
            },
        )
        resp = client.post(
            "/v1/responses",
            json={"model": "gpt-6.1-sol", "input": [{"role": "user", "content": _rows()}]},
            headers={"Authorization": "Bearer sk-test", "User-Agent": "codex_cli_rs/0.140"},
        )
        assert resp.status_code == 200
        assert sent[0].url.path.endswith("/responses")
        assert sent[0].headers["authorization"] == "Bearer sk-test"
        assert int(resp.headers["x-sensei-tokens-saved"]) > 0

        totals = savings_mod.get_savings_tracker().lifetime()
        assert totals["cache"]["cache_read_tokens"] == 800
        assert totals["cache"]["prompt_tokens_billed"] == 1000
        assert totals["cache"]["hit_rate"] == 0.8

    def test_compact_is_compressed_and_not_counted_as_a_turn(self, client, upstream, monkeypatch):
        sent, handlers = upstream
        monkeypatch.setattr(settings, "api_provider", "openai")
        handlers["*"] = lambda r: httpx.Response(200, json={"output": []})
        resp = client.post(
            "/v1/responses/input_tokens",
            json={"model": "m", "input": [{"role": "user", "content": _rows()}]},
            headers={"Authorization": "Bearer sk-test"},
        )
        assert resp.status_code == 200
        assert sent[0].url.path.endswith("/responses/input_tokens")
        assert len(_body(sent[0])["input"][0]["content"]) < len(_rows())
        assert savings_mod.get_savings_tracker().lifetime()["requests"] == 0


# ─── Anthropic Messages (Claude Code) ────────────────────────────────────────


class TestEditTargets:
    def test_code_in_a_tool_result_is_not_rewritten(self):
        messages = [
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t", "content": PYTHON_FILE}],
            }
        ]
        _, out, _ = gateway.compress_anthropic_request(None, messages)
        assert out[0]["content"][0]["content"] == PYTHON_FILE

    def test_a_line_numbered_file_view_is_not_rewritten(self):
        view = "\n".join(f"{i:>6}→{line}" for i, line in enumerate(_rows(5).split(","), 1))
        messages = [
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t", "content": view}],
            }
        ]
        _, out, _ = gateway.compress_anthropic_request(None, messages)
        assert out[0]["content"][0]["content"] == view

    def test_json_in_a_tool_result_is_still_compressed(self):
        messages = [
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t", "content": _rows()}],
            }
        ]
        _, out, savings = gateway.compress_anthropic_request(None, messages)
        assert savings["tokens_saved"] > 0
        assert len(out[0]["content"][0]["content"]) < len(_rows())

    def test_aggressive_mode_rewrites_code_too(self, monkeypatch):
        monkeypatch.setattr(settings, "code_compression", "aggressive")
        gateway._content_router = None  # pick up the setting
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t", "content": PYTHON_FILE}
                    ],
                }
            ]
            _, out, _ = gateway.compress_anthropic_request(None, messages)
            assert "a comment the Edit tool" not in out[0]["content"][0]["content"]
        finally:
            gateway._content_router = None

    def test_openai_tool_messages_are_edit_targets(self):
        messages = [{"role": "tool", "tool_call_id": "c", "content": PYTHON_FILE}]
        out, _ = gateway.compress_request_messages(messages)
        assert out[0]["content"] == PYTHON_FILE


class TestForwarding:
    def test_count_tokens_is_forwarded_compressed(self, client, upstream):
        sent, handlers = upstream
        handlers["*"] = lambda r: httpx.Response(200, json={"input_tokens": 42})
        resp = client.post(
            "/v1/messages/count_tokens",
            json={"model": "claude-sonnet-5-5", "messages": [{"role": "user", "content": _rows()}]},
            headers={"x-api-key": "sk-ant-test"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"input_tokens": 42}
        assert sent[0].url.path.endswith("/messages/count_tokens")
        assert len(_body(sent[0])["messages"][0]["content"]) < len(_rows())
        # A count is not a request that cost anything.
        assert savings_mod.get_savings_tracker().lifetime()["requests"] == 0

    def test_429_is_retried_then_succeeds(self, client, upstream):
        sent, handlers = upstream
        replies = iter(
            [
                httpx.Response(429, headers={"retry-after": "0"}, json={"error": {}}),
                httpx.Response(200, json={"id": "msg", "content": [], "usage": {}}),
            ]
        )
        handlers["*"] = lambda r: next(replies)
        resp = client.post(
            "/v1/messages",
            json={"model": "m", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]},
            headers={"x-api-key": "k"},
        )
        assert resp.status_code == 200
        assert len(sent) == 2

    def test_a_streaming_error_keeps_its_status(self, client, upstream, monkeypatch):
        """A 429 on a stream used to arrive as 200 text/event-stream."""
        _sent, handlers = upstream
        monkeypatch.setattr(settings, "upstream_retries", 0)
        handlers["*"] = lambda r: httpx.Response(
            429,
            headers={"retry-after": "30", "anthropic-ratelimit-requests-remaining": "0"},
            json={"type": "error", "error": {"type": "rate_limit_error"}},
        )
        resp = client.post(
            "/v1/messages",
            json={"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
            headers={"x-api-key": "k"},
        )
        assert resp.status_code == 429
        assert resp.json()["error"]["type"] == "rate_limit_error"
        assert resp.headers["retry-after"] == "30"
        assert resp.headers["anthropic-ratelimit-requests-remaining"] == "0"

    def test_streamed_usage_lands_in_the_ledger(self, client, upstream):
        _sent, handlers = upstream
        events = [
            {
                "type": "message_start",
                "message": {
                    "usage": {
                        "input_tokens": 10,
                        "cache_read_input_tokens": 900,
                        "cache_creation_input_tokens": 90,
                    }
                },
            },
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}},
            {"type": "message_delta", "usage": {"output_tokens": 7}},
        ]
        stream = "".join(f"event: x\ndata: {json.dumps(e)}\n\n" for e in events)
        handlers["*"] = lambda r: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=stream.encode()
        )
        resp = client.post(
            "/v1/messages",
            json={"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
            headers={"x-api-key": "k"},
        )
        assert resp.status_code == 200
        assert "hello" in resp.text
        cache = savings_mod.get_savings_tracker().lifetime()["cache"]
        assert cache["cache_read_tokens"] == 900
        assert cache["cache_write_tokens"] == 90
        assert cache["prompt_tokens_billed"] == 1000

    def test_unreachable_provider_is_a_502(self, client, upstream, monkeypatch):
        monkeypatch.setattr(settings, "upstream_retries", 1)
        resp = client.post(
            "/v1/messages",
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            headers={"x-api-key": "k"},
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["type"] == "upstream_error"

    def test_local_fallback_answers_when_the_provider_is_down(self, client, upstream, monkeypatch):
        sent, handlers = upstream
        monkeypatch.setattr(settings, "fallback_enabled", True)
        monkeypatch.setattr(settings, "fallback_base_url", "http://localhost:11434")
        monkeypatch.setattr(settings, "fallback_model", "qwen3.8:27b")
        monkeypatch.setattr(settings, "upstream_retries", 0)
        handlers[settings.anthropic_api_base_url.rstrip("/")] = lambda r: httpx.Response(
            529, json={"type": "error", "error": {"type": "overloaded_error"}}
        )
        handlers["http://localhost:11434/v1"] = lambda r: httpx.Response(
            200, json={"id": "local", "content": [{"type": "text", "text": "ok"}], "usage": {}}
        )
        resp = client.post(
            "/v1/messages",
            json={"model": "claude-sonnet-5-5", "messages": [{"role": "user", "content": "hi"}]},
            headers={"x-api-key": "sk-ant-secret"},
        )
        assert resp.status_code == 200
        assert resp.headers["x-sensei-fallback"] == "qwen3.8:27b"
        local = sent[-1]
        assert _body(local)["model"] == "qwen3.8:27b"
        # The provider key never leaves for another server.
        assert "sk-ant-secret" not in str(local.headers)

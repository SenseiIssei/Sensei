# ruff: noqa: F811 - the shared fixtures are imported, then named as test parameters
"""Regression tests for the review of the cache-aware gateway (PR #162).

Each class is one finding. The fixtures are the ones from
``test_gateway_cache_aware``: a mock upstream, an isolated ledger and an
isolated gateway-state database per test.
"""

from __future__ import annotations

import json

import anyio
import httpx
import pytest
from test_gateway_cache_aware import (  # noqa: F401 - fixtures
    KEY,
    TOOLS,
    _anthropic_reply,
    _body,
    _no_cc,
    _rows,
    _turns,
    client,
    intercept,
    upstream,
)

from sensei.config import settings
from sensei.gateway import ccr, extras, session
from sensei.gateway.intercept import Retriever
from sensei.gateway.session import Plan, canon, live_zone
from sensei.gateway.state import state
from sensei.routers import gateway


def _retrieve_then(final_text: str, cid: str):
    """An upstream that calls sensei_retrieve once, then answers ``final_text``."""
    replies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _body(request)
        last = body["messages"][-1]["content"]
        answered = isinstance(last, list) and any(
            isinstance(b, dict) and b.get("tool_use_id") == "r-hidden" for b in last
        )
        replies.append(body)
        if not answered and len(replies) == 1:
            return httpx.Response(
                200,
                json={
                    "id": "m1",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "r-hidden",
                            "name": ccr.TOOL_NAME,
                            "input": {"ccr": cid},
                        }
                    ],
                    "stop_reason": "tool_use",
                    "usage": {"input_tokens": 5, "output_tokens": 5},
                },
            )
        return _anthropic_reply(final_text)

    return handler, replies


def _conversation(first: str) -> list[dict]:
    return [
        {"role": "user", "content": [{"type": "text", "text": first}]},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": _rows()}],
        },
    ]


def _hidden_calls(body: dict) -> int:
    return sum(
        1
        for m in body["messages"]
        if m["role"] == "assistant"
        for b in m["content"]
        if isinstance(b, dict) and b.get("name") == ccr.TOOL_NAME
    )


# ── 1. Expansions never cross conversations, credentials or positions ───────


class TestExpansionScope:
    def _merged(self, client, upstream, first: str, headers=KEY) -> list:
        _sent, handlers = upstream
        handler, _ = _retrieve_then("Done.", ccr.ccr_id(_rows()))
        handlers["*"] = handler
        resp = client.post(
            "/v1/messages",
            json={"model": "m", "tools": TOOLS, "messages": _conversation(first)},
            headers=headers,
        )
        return resp.json()["content"]

    def test_another_conversation_with_the_same_reply_is_untouched(
        self, client, upstream, intercept
    ):
        sent, handlers = upstream
        merged = self._merged(client, upstream, "task A")
        assert merged == [{"type": "text", "text": "Done."}]

        other = [
            *_conversation("task B"),
            {"role": "assistant", "content": merged},
            {"role": "user", "content": "next"},
        ]
        handlers["*"] = lambda r: _anthropic_reply()
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": other}, headers=KEY
        )
        body = _body(sent[-1])
        assert _hidden_calls(body) == 0
        assert "r-hidden" not in canon(body)

    def test_another_credential_is_untouched(self, client, upstream, intercept):
        sent, handlers = upstream
        merged = self._merged(client, upstream, "task A")
        same = [
            *_conversation("task A"),
            {"role": "assistant", "content": merged},
            {"role": "user", "content": "next"},
        ]
        handlers["*"] = lambda r: _anthropic_reply()
        client.post(
            "/v1/messages",
            json={"model": "m", "tools": TOOLS, "messages": same},
            headers={**KEY, "x-api-key": "sk-ant-someone-else"},
        )
        assert _hidden_calls(_body(sent[-1])) == 0

    def test_a_repeated_reply_expands_only_where_it_happened(self, client, upstream, intercept):
        sent, handlers = upstream
        merged = self._merged(client, upstream, "task A")
        history = [
            *_conversation("task A"),
            {"role": "assistant", "content": merged},
            {"role": "user", "content": "again"},
            {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
            {"role": "user", "content": "next"},
        ]
        handlers["*"] = lambda r: _anthropic_reply()
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": history}, headers=KEY
        )
        body = _body(sent[-1])
        assert _hidden_calls(body) == 1
        ids = [
            b.get("id")
            for m in body["messages"]
            for b in m["content"]
            if isinstance(b, dict) and b.get("id")
        ]
        assert len(ids) == len(set(ids))


# ── 2. A client tool before ours means the call goes to the client ──────────


def _sse(*events: tuple[str, dict]) -> bytes:
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()


def test_client_tool_before_ours_in_a_stream_is_not_hidden(client, upstream, intercept):
    _, handlers = upstream
    calls = []
    body = _sse(
        (
            "message_start",
            {"type": "message_start", "message": {"id": "m", "usage": {"input_tokens": 1}}},
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "b1", "name": "Bash", "input": {}},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "r1",
                    "name": ccr.TOOL_NAME,
                    "input": {},
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"ccr": "0123456789abcdef"}',
                },
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 3},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    )

    def handler(request):
        calls.append(1)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    handlers["*"] = handler
    resp = client.post(
        "/v1/messages",
        json={"model": "m", "stream": True, "tools": TOOLS, "messages": _conversation("x")},
        headers=KEY,
    )
    assert len(calls) == 1
    assert "Bash" in resp.text and ccr.TOOL_NAME in resp.text


# ── 3. What the provider saw survives a restart ─────────────────────────────


def _restart() -> None:
    live_zone.clear()
    ccr.store.clear()
    state.forget_memory()


class TestRestart:
    def test_answered_retrieve_stays_the_same(self, client, upstream):
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        cid = ccr.store.put(_rows())
        history = [
            *_conversation("task"),
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "r1", "name": ccr.TOOL_NAME, "input": {"ccr": cid}}
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "r1",
                        "content": "No such tool",
                        "is_error": True,
                    }
                ],
            },
        ]
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": history}, headers=KEY
        )
        first = _body(sent[-1])["messages"]
        assert first[-1]["content"][0]["content"] == _rows()

        _restart()
        later = [
            *history,
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            {"role": "user", "content": "go on"},
        ]
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": later}, headers=KEY
        )
        assert _no_cc(_body(sent[-1])["messages"][: len(first)]) == _no_cc(first)

    def test_hidden_exchange_is_restored_after_a_restart(self, client, upstream, intercept):
        sent, handlers = upstream
        handler, _ = _retrieve_then("Done.", ccr.ccr_id(_rows()))
        handlers["*"] = handler
        merged = client.post(
            "/v1/messages",
            json={"model": "m", "tools": TOOLS, "messages": _conversation("task")},
            headers=KEY,
        ).json()["content"]
        _restart()
        handlers["*"] = lambda r: _anthropic_reply()
        later = [
            *_conversation("task"),
            {"role": "assistant", "content": merged},
            {"role": "user", "content": "next"},
        ]
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": later}, headers=KEY
        )
        assert _hidden_calls(_body(sent[-1])) == 1

    def test_shaper_blocks_survive_a_cold_start(self, client, upstream, monkeypatch):
        monkeypatch.setattr(settings, "output_shaper", True)
        monkeypatch.setattr(settings, "output_holdout", 0.0)
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        turns = _turns(4)
        for msgs in turns[1:3]:
            client.post("/v1/messages", json={"model": "m", "messages": msgs}, headers=KEY)
        before = _body(sent[-1])["messages"]
        _restart()
        client.post("/v1/messages", json={"model": "m", "messages": turns[3]}, headers=KEY)
        assert _no_cc(_body(sent[-1])["messages"][: len(before)]) == _no_cc(before)

    def test_preserve_cache_is_reproduced_after_a_cold_start(self, client, upstream, monkeypatch):
        monkeypatch.setattr(settings, "gateway_preserve_cache", True)
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        turns = _turns(4)
        for msgs in turns[1:3]:
            client.post("/v1/messages", json={"model": "m", "messages": msgs}, headers=KEY)
        before = _body(sent[-1])["messages"]
        _restart()
        client.post("/v1/messages", json={"model": "m", "messages": turns[3]}, headers=KEY)
        assert _no_cc(_body(sent[-1])["messages"][: len(before)]) == _no_cc(before)

    def test_interception_is_off_by_default(self, client, upstream):
        _, handlers = upstream
        handler, replies = _retrieve_then("Done.", ccr.ccr_id(_rows()))
        handlers["*"] = handler
        data = client.post(
            "/v1/messages",
            json={"model": "m", "tools": TOOLS, "messages": _conversation("task")},
            headers=KEY,
        ).json()
        assert data["content"][0]["name"] == ccr.TOOL_NAME
        assert len(replies) == 1


# ── 4. Hidden rounds go through redaction and the block-list ────────────────

SECRET = "AKIA" + "Q" * 16  # shaped like an AWS key; built so no scanner flags it


class TestHiddenRoundPolicy:
    def _rows_with_secret(self) -> str:
        return json.dumps(
            [{"id": i, "note": SECRET if i == 3 else "x" * 20, "ok": True} for i in range(60)]
        )

    def test_follow_up_is_redacted(self, client, upstream, intercept, monkeypatch):
        monkeypatch.setattr(settings, "redaction_enabled", True)
        _, handlers = upstream
        original = self._rows_with_secret()
        cid = ccr.store.put(original)
        handler, replies = _retrieve_then("Done.", cid)
        handlers["*"] = handler
        client.post(
            "/v1/messages",
            json={"model": "m", "tools": TOOLS, "messages": _conversation("t")},
            headers=KEY,
        )
        assert len(replies) == 2
        assert SECRET not in canon(replies[1])

    def test_blocked_follow_up_is_not_sent(self, client, upstream, intercept, monkeypatch):
        monkeypatch.setattr(settings, "blocked_patterns", "forbidden-word")
        _, handlers = upstream
        cid = ccr.store.put("forbidden-word " * 100)
        handler, replies = _retrieve_then("Done.", cid)
        handlers["*"] = handler
        data = client.post(
            "/v1/messages",
            json={"model": "m", "tools": TOOLS, "messages": _conversation("t")},
            headers=KEY,
        ).json()
        assert len(replies) == 1
        assert data["content"][0]["name"] == ccr.TOOL_NAME

    def test_responses_reasoning_is_never_hidden(self, client, upstream, intercept, monkeypatch):
        monkeypatch.setattr(settings, "api_provider", "openai")
        _, handlers = upstream
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(
                200,
                json={
                    "id": "r1",
                    "output": [
                        {"type": "reasoning", "id": "rs1", "encrypted_content": "x"},
                        {
                            "type": "function_call",
                            "call_id": "c9",
                            "name": ccr.TOOL_NAME,
                            "arguments": "{}",
                        },
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )

        handlers["*"] = handler
        data = client.post(
            "/v1/responses",
            json={
                "model": "g",
                "tools": [{"type": "function", "name": "sh", "parameters": {}}],
                "input": [{"role": "user", "content": "q"}],
            },
            headers={"Authorization": "Bearer k"},
        ).json()
        assert len(calls) == 1
        assert [o["type"] for o in data["output"]] == ["reasoning", "function_call"]


# ── 5. The frozen boundary ──────────────────────────────────────────────────


class TestFrozen:
    def _plan(self, **kw) -> Plan:
        base = {
            "key": "k",
            "cause": "hit",
            "reuse": 0,
            "groups": [],
            "hashes": [],
            "stripped": [],
            "marks": [[], [], []],
            "head": "",
            "cache_ttl": 300,
            "size": 0,
        }
        base.update(kw)
        return Plan(**base)

    def test_cold_openai_freezes_everything(self):
        msgs = [{"role": "user"}] * 3
        assert session.LiveZone._frozen(self._plan(cause="cold_start", api="openai"), msgs) == 3

    def test_the_marked_message_itself_is_frozen(self):
        plan = self._plan(api="anthropic", marks=[[], [((), {"type": "ephemeral"})], []])
        assert session.LiveZone._frozen(plan, [{"role": "user"}] * 3) == 2

    def test_reasoning_items_bind_like_thinking(self):
        assert session.has_thinking({"type": "reasoning", "encrypted_content": "x"})
        plan = self._plan(api="responses", previous_cached=0)
        msgs = [{"role": "user"}, {"type": "reasoning"}, {"role": "user"}]
        assert session.LiveZone._frozen(plan, msgs) == 2

    def test_chat_cold_start_keeps_superseded_reads(self, client, upstream, monkeypatch):
        monkeypatch.setattr(settings, "api_provider", "openai")
        sent, handlers = upstream
        handlers["*"] = lambda r: httpx.Response(200, json={"choices": [], "usage": {}})
        source = "\n".join(f"line {i} of the file" for i in range(80))
        msgs = [
            {"role": "user", "content": "fix"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "r",
                        "type": "function",
                        "function": {"name": "Read", "arguments": json.dumps({"file_path": "/a"})},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "r", "content": source},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "e",
                        "type": "function",
                        "function": {"name": "Edit", "arguments": json.dumps({"file_path": "/a"})},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "e", "content": "ok"},
        ]
        client.post(
            "/v1/chat/completions",
            json={"model": "g", "messages": msgs},
            headers={"Authorization": "Bearer k"},
        )
        assert "stale Read" not in canon(_body(sent[-1]))


# ── 6. A client hanging up mid-splice closes the follow-up connection ───────


class _Tracked(httpx.AsyncByteStream):
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.closed = False

    async def __aiter__(self):
        yield self.data

    async def aclose(self) -> None:
        self.closed = True


def test_disconnect_closes_the_follow_up(monkeypatch):
    monkeypatch.setattr(settings, "gateway_retrieve_in_streams", True)
    cid = ccr.store.put(_rows())
    first = _sse(
        ("message_start", {"type": "message_start", "message": {"id": "m", "usage": {}}}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "r1",
                    "name": ccr.TOOL_NAME,
                    "input": {},
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": json.dumps({"ccr": cid})},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {}},
        ),
        ("message_stop", {"type": "message_stop"}),
    )
    second = _Tracked(
        _sse(
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "two"},
                },
            ),
        )
    )
    headers = {"content-type": "text/event-stream"}

    async def send(payload):
        return httpx.Response(200, headers=headers, stream=second)

    async def scenario():
        retriever = Retriever("anthropic", {"messages": [{"role": "user", "content": "q"}]}, send)
        relay = gateway._relay(
            httpx.Response(200, headers=headers, content=first), retriever, None, None
        )
        async for chunk in relay:
            if b"two" in chunk:
                break
        await relay.aclose()  # what the server does when the client hangs up

    anyio.run(scenario)
    assert second.closed


# ── 7. The budget meter stays bounded ───────────────────────────────────────


def test_budget_meter_is_idle_without_budgets(monkeypatch):
    extras.budget_meter.clear()
    monkeypatch.setattr(settings, "gateway_tool_budgets", "")
    extras.budget_meter.add("anything", 100)
    assert extras.budget_meter.used("anything") == 0

    monkeypatch.setattr(settings, "gateway_tool_budgets", "x=10")
    for i in range(1000):
        extras.budget_meter.add(f"client-{i}", 1)
    assert len(extras.budget_meter._events) <= extras.BudgetMeter.MAX_TOOLS
    extras.budget_meter.clear()


# ── 8. Chat shaping stays inside the user's message ─────────────────────────


def test_chat_shaper_appends_to_the_user_message(client, upstream, monkeypatch):
    from sensei import output_shaping

    monkeypatch.setattr(settings, "output_shaper", True)
    monkeypatch.setattr(settings, "output_holdout", 0.0)
    monkeypatch.setattr(settings, "api_provider", "openai")
    sent, handlers = upstream
    handlers["*"] = lambda r: httpx.Response(200, json={"choices": [], "usage": {}})
    client.post(
        "/v1/chat/completions",
        json={
            "model": "g",
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}],
        },
        headers={"Authorization": "Bearer k"},
    )
    messages = _body(sent[-1])["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[-1]["content"].endswith(output_shaping.instruction())

    tool_tail = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "t", "type": "function", "function": {"name": "sh", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "t", "content": "out"},
    ]
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "g", "messages": tool_tail},
        headers={"Authorization": "Bearer k"},
    )
    messages = _body(sent[-1])["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "tool"]
    assert "x-sensei-output-shaped" not in resp.headers


@pytest.fixture(autouse=True)
def _no_leftover_state():
    yield
    state.close()

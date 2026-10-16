"""The cache-aware gateway, end to end through the HTTP routes.

Every test runs the real routing, compression and forwarding with the upstream
replaced by an ``httpx.MockTransport``, and inspects what the "provider" was
sent. The properties under test are the ones a provider can observe:

- the forwarded history is append-only across turns (prompt cache, and the
  thinking-block binding on current Claude models);
- `sensei_retrieve` exists exactly when it can be answered, and is answered
  without the client seeing it;
- a Claude subscription request keeps its tools and cache markers as sent.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from sensei import savings as savings_mod
from sensei.config import settings
from sensei.gateway import ccr, extras, session, tools
from sensei.gateway.session import canon, live_zone, strip_cache_control
from sensei.gateway.state import state
from sensei.main import app
from sensei.routers import gateway

Handler = Callable[[httpx.Request], httpx.Response]


def _rows(n: int = 60, tag: str = "") -> str:
    return json.dumps(
        [
            {"id": i, "name": f"user{i}{tag}", "active": True, "role": "member", "team": "core"}
            for i in range(n)
        ]
    )


def _log(n: int = 200, tag: str = "") -> str:
    return "\n".join(
        f"2026-10-16 12:00:{s % 60:02d} INFO worker={s % 4} item={s} {tag} status=ok"
        for s in range(n)
    )


TOOLS = [
    {
        "name": "Bash",
        "description": "Run a shell command.",
        "input_schema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "BashInput",
            "properties": {
                "command": {"type": "string", "description": "The command", "examples": ["ls"]},
                "title": {"type": "string", "description": "A parameter that is called title"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "Read",
        "description": "Read a file.",
        "input_schema": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
]


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch, tmp_path):
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
    for name, value in {
        "upstream_retry_max_wait": 0.0,
        "redaction_enabled": False,
        "output_shaper": False,
        "gateway_preserve_cache": False,
        "fallback_enabled": False,
        "savings_persist": True,
        "savings_db": str(tmp_path / "ledger.db"),
        "gateway_live_zone": True,
        "gateway_retrieve_tool": True,
        "gateway_retrieve_intercept": False,
        "gateway_state_persist": True,
        "gateway_state_db": str(tmp_path / "gateway-state.db"),
        "gateway_tool_schema_compaction": True,
        "gateway_tool_search": False,
        "gateway_dedup": True,
        "gateway_stale_reads": True,
        "gateway_model_router": "",
        "gateway_response_cache": False,
        "gateway_tool_budgets": "",
        "gateway_ccr_min_saved_tokens": 50,
        "compression_enabled": True,
        "gateway_compress_system": True,
        "anthropic_api_base_url": "https://api.anthropic.com/v1",
    }.items():
        monkeypatch.setattr(settings, name, value)
    savings_mod.reset_savings_tracker()
    savings_mod.get_savings_tracker().ledger.clear()
    live_zone.clear()
    ccr.store.clear()
    state.close()
    state.clear()
    extras.response_cache.clear()
    extras.budget_meter.clear()
    yield sent, handlers
    savings_mod.reset_savings_tracker()
    live_zone.clear()


@pytest.fixture
def intercept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gateway_retrieve_intercept", True)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def _anthropic_reply(text: str = "ok", **usage) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 10, **usage},
        },
    )


KEY = {"x-api-key": "sk-ant-test", "anthropic-version": "2023-06-01"}


def _turns(n: int) -> list[list[dict]]:
    """A Claude Code shaped conversation, with the cache marker on the last
    block of the last message only — moved every turn, as Claude Code does."""
    history: list[dict] = [
        {"role": "user", "content": [{"type": "text", "text": "look at the users"}]}
    ]
    turns = []
    for t in range(n):
        if t:
            history.append(
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": f"checking {t}"},
                        {
                            "type": "tool_use",
                            "id": f"tu{t}",
                            "name": "Bash",
                            "input": {"command": "x"},
                        },
                    ],
                }
            )
            history.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"tu{t}",
                            "content": _log(tag=f"t{t}"),
                        }
                    ],
                }
            )
        msgs = json.loads(json.dumps(history))
        last = msgs[-1]
        if isinstance(last["content"], str):
            last["content"] = [{"type": "text", "text": last["content"]}]
        last["content"][-1]["cache_control"] = {"type": "ephemeral"}
        turns.append(msgs)
    return turns


def _no_cc(messages: list) -> str:
    return canon(strip_cache_control(messages)[0])


# ─── live zone ──────────────────────────────────────────────────────────────


class TestLiveZone:
    def test_prefix_is_byte_identical_and_attributed(self, client, upstream):
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        causes = []
        for msgs in _turns(4):
            resp = client.post(
                "/v1/messages",
                json={
                    "model": "m",
                    "max_tokens": 10,
                    "system": "sys",
                    "tools": TOOLS,
                    "messages": msgs,
                },
                headers=KEY,
            )
            assert resp.status_code == 200
            causes.append(resp.headers["x-sensei-live-zone"])
        assert causes == ["cold_start", "hit", "hit", "hit"]

        bodies = [_body(r) for r in sent]
        for prev, cur in itertools.pairwise(bodies):
            n = len(prev["messages"])
            assert _no_cc(cur["messages"][:n]) == _no_cc(prev["messages"])
            assert canon(cur["tools"]) == canon(prev["tools"])
            assert canon(cur["system"]) == canon(prev["system"])
        # Markers do not pile up as the client moves them.
        for body in bodies:
            assert len(strip_cache_control(body["messages"])[1]) == 1

    def test_replays_bytes_even_when_the_compressor_changes(self, client, upstream, monkeypatch):
        """The point of remembering: a Sensei upgrade that changes a
        compressor mid-conversation must not rewrite what was already sent."""
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        turns = _turns(3)
        client.post("/v1/messages", json={"model": "m", "messages": turns[1]}, headers=KEY)
        first = _body(sent[-1])["messages"]

        real = gateway._compress_text

        def different(text, *, edit_target=False):
            out = real(text, edit_target=edit_target)
            return (out[0] + " [v2]", *out[1:]) if isinstance(out[0], str) and out[4] else out

        monkeypatch.setattr(gateway, "_compress_text", different)
        client.post("/v1/messages", json={"model": "m", "messages": turns[2]}, headers=KEY)
        second = _body(sent[-1])["messages"]
        assert _no_cc(second[: len(first)]) == _no_cc(first)
        assert "[v2]" in canon(second[len(first) :])

    def test_ttl_and_prefix_change_are_told_apart(self, client, upstream, monkeypatch):
        _, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        now = [1_000_000.0]
        monkeypatch.setattr(session, "clock", lambda: now[0])
        turns = _turns(4)
        post = lambda msgs: client.post(  # noqa: E731
            "/v1/messages", json={"model": "m", "messages": msgs}, headers=KEY
        ).headers["x-sensei-live-zone"]
        assert post(turns[1]) == "cold_start"
        now[0] += 400  # past the 5-minute cache
        assert post(turns[2]) == "ttl"
        edited = json.loads(json.dumps(turns[3]))
        edited[1]["content"][0]["text"] = "rewritten by the client"
        assert post(edited) == "prefix_change"

        stats = client.get("/api/gateway/stats").json()
        assert stats["live_zone"]["causes"] == {"cold_start": 1, "ttl": 1, "prefix_change": 1}
        ledger = stats["ledger"]
        assert ledger["ttl"]["requests"] == 1 and ledger["prefix_change"]["requests"] == 1

    def test_one_hour_markers_extend_the_assumed_cache(self, client, upstream, monkeypatch):
        _, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        now = [1_000_000.0]
        monkeypatch.setattr(session, "clock", lambda: now[0])
        turns = _turns(3)
        for msgs in turns:
            msgs[-1]["content"][-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
        client.post("/v1/messages", json={"model": "m", "messages": turns[1]}, headers=KEY)
        now[0] += 1200
        resp = client.post("/v1/messages", json={"model": "m", "messages": turns[2]}, headers=KEY)
        assert resp.headers["x-sensei-live-zone"] == "hit"

    def test_assistant_turns_and_thinking_are_never_rewritten(self, client, upstream):
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        assistant = {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig-abc"},
                {"type": "text", "text": _log(tag="assistant")},
            ],
        }
        msgs = [{"role": "user", "content": "go"}, assistant, {"role": "user", "content": _log()}]
        client.post("/v1/messages", json={"model": "m", "messages": msgs}, headers=KEY)
        forwarded = _body(sent[-1])["messages"]
        assert forwarded[1] == assistant
        assert len(canon(forwarded[2])) < len(canon(msgs[2]))

    def test_off_compresses_statelessly(self, client, upstream, monkeypatch):
        monkeypatch.setattr(settings, "gateway_live_zone", False)
        _, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        turns = _turns(2)
        for msgs in turns:
            resp = client.post("/v1/messages", json={"model": "m", "messages": msgs}, headers=KEY)
            assert "x-sensei-live-zone" not in resp.headers
        assert live_zone.stats()["conversations"] == 0

    def test_count_tokens_is_a_dry_run(self, client, upstream):
        _sent, handlers = upstream
        handlers["*"] = lambda r: httpx.Response(200, json={"input_tokens": 5})
        resp = client.post(
            "/v1/messages/count_tokens", json={"model": "m", "messages": _turns(2)[1]}, headers=KEY
        )
        assert resp.status_code == 200
        assert live_zone.stats()["conversations"] == 0


# ─── retrieve ───────────────────────────────────────────────────────────────


def _marker_id(body: dict) -> str:
    match = ccr.MARKER_RE.search(canon(body["messages"]))
    assert match, "expected a retrieve marker in the forwarded request"
    return match.group(2)


class TestRetrieve:
    def _msgs(self) -> list[dict]:
        return [
            {"role": "user", "content": "list users"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "q"}}
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": _rows()}],
            },
        ]

    def test_markers_and_tool_appear_together(self, client, upstream):
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        client.post(
            "/v1/messages",
            json={"model": "m", "tools": TOOLS, "messages": self._msgs()},
            headers=KEY,
        )
        body = _body(sent[-1])
        cid = _marker_id(body)
        assert ccr.store.get(cid) == _rows()
        assert [t["name"] for t in body["tools"]][-1] == ccr.TOOL_NAME

    def test_no_tools_means_no_injection_and_no_marker(self, client, upstream):
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        client.post("/v1/messages", json={"model": "m", "messages": self._msgs()}, headers=KEY)
        body = _body(sent[-1])
        assert "tools" not in body
        assert not ccr.MARKER_RE.search(canon(body))

    def test_call_is_answered_server_side(self, client, upstream, intercept):
        sent, handlers = upstream
        replies = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = _body(request)
            if not replies:
                replies.append(1)
                cid = _marker_id(body)
                return httpx.Response(
                    200,
                    json={
                        "id": "m1",
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "let me look"},
                            {
                                "type": "tool_use",
                                "id": "r1",
                                "name": ccr.TOOL_NAME,
                                "input": {"ccr": cid},
                            },
                        ],
                        "stop_reason": "tool_use",
                        "usage": {"input_tokens": 50, "output_tokens": 7},
                    },
                )
            last = body["messages"][-1]["content"][0]
            assert last["type"] == "tool_result" and last["content"] == _rows()
            return _anthropic_reply("found user42", output_tokens=5)

        handlers["*"] = handler
        resp = client.post(
            "/v1/messages",
            json={"model": "m", "tools": TOOLS, "messages": self._msgs()},
            headers=KEY,
        )
        data = resp.json()
        assert resp.headers["x-sensei-retrieve-rounds"] == "1"
        assert [b["type"] for b in data["content"]] == ["text", "text"]
        assert data["content"][1]["text"] == "found user42"
        assert data["usage"]["output_tokens"] == 12
        assert data["sensei"]["retrieve"]["rounds"] == 1
        assert len(sent) == 2

        # Next turn: the client sends the merged message back; the provider
        # sees the real exchange again.
        follow = [
            *self._msgs(),
            {"role": "assistant", "content": data["content"]},
            {"role": "user", "content": "thanks"},
        ]
        handlers["*"] = lambda r: _anthropic_reply()
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": follow}, headers=KEY
        )
        forwarded = _body(sent[-1])["messages"]
        assert [m["role"] for m in forwarded] == [
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
        ]
        assert forwarded[3]["content"][1]["name"] == ccr.TOOL_NAME

    def test_mixed_calls_reach_the_client_and_are_answered_next_turn(self, client, upstream):
        sent, handlers = upstream
        handlers["*"] = lambda r: httpx.Response(
            200,
            json={
                "id": "m1",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "r1",
                        "name": ccr.TOOL_NAME,
                        "input": {"ccr": ccr.ccr_id(_rows())},
                    },
                    {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "ls"}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 5, "output_tokens": 5},
            },
        )
        resp = client.post(
            "/v1/messages",
            json={"model": "m", "tools": TOOLS, "messages": self._msgs()},
            headers=KEY,
        )
        content = resp.json()["content"]
        assert {b["name"] for b in content} == {ccr.TOOL_NAME, "Bash"}

        follow = [
            *self._msgs(),
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "r1",
                        "content": "No such tool",
                        "is_error": True,
                    },
                    {"type": "tool_result", "tool_use_id": "b1", "content": "a.txt"},
                ],
            },
        ]
        handlers["*"] = lambda r: _anthropic_reply()
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": follow}, headers=KEY
        )
        results = _body(sent[-1])["messages"][-1]["content"]
        assert results[0]["content"] == _rows()
        assert results[1]["content"] == "a.txt"

    def test_streamed_call_is_spliced_out(self, client, upstream, intercept):
        _, handlers = upstream
        cid = ccr.ccr_id(_rows())

        def ev(name, data):
            return f"event: {name}\ndata: {json.dumps(data)}\n\n"

        round1 = "".join(
            [
                ev(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {"id": "m1", "usage": {"input_tokens": 9}},
                    },
                ),
                ev(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    },
                ),
                ev(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "one"},
                    },
                ),
                ev("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ev(
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
                ev(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 1,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": json.dumps({"ccr": cid}),
                        },
                    },
                ),
                ev("content_block_stop", {"type": "content_block_stop", "index": 1}),
                ev(
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "tool_use"},
                        "usage": {"output_tokens": 4},
                    },
                ),
                ev("message_stop", {"type": "message_stop"}),
            ]
        )
        round2 = "".join(
            [
                ev(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {"id": "m2", "usage": {"input_tokens": 99}},
                    },
                ),
                ev(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    },
                ),
                ev(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "two"},
                    },
                ),
                ev("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ev(
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn"},
                        "usage": {"output_tokens": 3},
                    },
                ),
                ev("message_stop", {"type": "message_stop"}),
            ]
        )
        calls = []

        def handler(request):
            calls.append(_body(request))
            text = round1 if len(calls) == 1 else round2
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=text.encode()
            )

        handlers["*"] = handler
        resp = client.post(
            "/v1/messages",
            json={"model": "m", "stream": True, "tools": TOOLS, "messages": self._msgs()},
            headers=KEY,
        )
        text = resp.text
        assert ccr.TOOL_NAME not in text
        events = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]
        starts = [e for e in events if e["type"] == "content_block_start"]
        assert [e["index"] for e in starts] == [0, 1]
        assert [e["type"] for e in events].count("message_start") == 1
        delta = next(e for e in events if e["type"] == "message_delta")
        assert delta["usage"]["output_tokens"] == 7
        assert calls[1]["messages"][-1]["content"][0]["content"] == _rows()

    def test_chat_completions_round_trip(self, client, upstream, intercept, monkeypatch):
        monkeypatch.setattr(settings, "api_provider", "openai")
        sent, handlers = upstream
        cid = ccr.ccr_id(_rows())
        replies = []

        def handler(request):
            body = _body(request)
            if not replies:
                replies.append(1)
                assert body["tools"][-1]["function"]["name"] == ccr.TOOL_NAME
                return httpx.Response(
                    200,
                    json={
                        "id": "c1",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "tool_calls",
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "x1",
                                            "type": "function",
                                            "function": {
                                                "name": ccr.TOOL_NAME,
                                                "arguments": json.dumps({"ccr": cid}),
                                            },
                                        }
                                    ],
                                },
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                    },
                )
            assert body["messages"][-1] == {
                "role": "tool",
                "tool_call_id": "x1",
                "content": _rows(),
            }
            return httpx.Response(
                200,
                json={
                    "id": "c2",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "done"},
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 2},
                },
            )

        handlers["*"] = handler
        msgs = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "t", "type": "function", "function": {"name": "sh", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "t", "content": _rows()},
        ]
        fn_tools = [
            {
                "type": "function",
                "function": {"name": "sh", "parameters": {"type": "object", "title": "x"}},
            }
        ]
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt", "tools": fn_tools, "messages": msgs},
            headers={"Authorization": "Bearer sk-test"},
        )
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "done"
        assert data["usage"]["completion_tokens"] == 5
        assert "title" not in _body(sent[0])["tools"][0]["function"]["parameters"]

    def test_responses_round_trip(self, client, upstream, intercept, monkeypatch):
        monkeypatch.setattr(settings, "api_provider", "openai")
        _, handlers = upstream
        cid = ccr.ccr_id(_rows())
        calls = []

        def handler(request):
            calls.append(_body(request))
            if len(calls) == 1:
                return httpx.Response(
                    200,
                    json={
                        "id": "r1",
                        "output": [
                            {
                                "type": "function_call",
                                "call_id": "c9",
                                "name": ccr.TOOL_NAME,
                                "arguments": json.dumps({"ccr": cid}),
                            }
                        ],
                        "usage": {"input_tokens": 10, "output_tokens": 2},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "id": "r2",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "ok"}],
                        }
                    ],
                    "usage": {"input_tokens": 30, "output_tokens": 3},
                },
            )

        handlers["*"] = handler
        body = {
            "model": "gpt",
            "tools": [{"type": "function", "name": "shell", "parameters": {"type": "object"}}],
            "input": [
                {"role": "user", "content": "q"},
                {"type": "function_call", "call_id": "c1", "name": "shell", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "c1", "output": _rows()},
            ],
        }
        resp = client.post("/v1/responses", json=body, headers={"Authorization": "Bearer sk-test"})
        data = resp.json()
        assert [o["type"] for o in data["output"]] == ["message"]
        assert calls[1]["input"][-1] == {
            "type": "function_call_output",
            "call_id": "c9",
            "output": _rows(),
        }
        assert data["usage"]["output_tokens"] == 5

    def test_unknown_ids_say_so(self):
        assert (
            ccr.resolve({"ccr": "0123456789abcdef"})
            == "[sensei: ccr=0123456789abcdef expired or unknown]"
        )

    def test_long_originals_page(self, monkeypatch):
        monkeypatch.setattr(settings, "gateway_retrieve_max_chars", 1000)
        text = "x" * 2500
        cid = ccr.store.put(text)
        page = ccr.resolve({"ccr": cid})
        assert page.startswith("x" * 1000) and "offset=1000" in page
        assert ccr.resolve({"ccr": cid, "offset": 2000}) == "x" * 500


# ─── Claude subscription (OAuth) ────────────────────────────────────────────


class TestOAuthPassthrough:
    def test_tools_and_markers_go_upstream_as_sent(self, client, upstream, monkeypatch):
        monkeypatch.setattr(settings, "gateway_tool_search", True)
        monkeypatch.setattr(settings, "gateway_tool_search_min_tools", 2)
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        many = [{**TOOLS[0], "name": f"mcp__t{i}"} for i in range(14)]
        many[-1] = {**many[-1], "cache_control": {"type": "ephemeral"}}
        msgs = _turns(2)[1]
        resp = client.post(
            "/v1/messages",
            json={"model": "m", "tools": many, "messages": msgs},
            headers={
                "authorization": "Bearer sk-ant-oat01-test",
                "anthropic-beta": "oauth-2025-04-20,claude-code-20250219",
            },
        )
        assert resp.status_code == 200
        body = _body(sent[-1])
        assert body["tools"] == many
        assert sent[-1].headers["authorization"] == "Bearer sk-ant-oat01-test"
        assert "oauth-2025-04-20" in sent[-1].headers["anthropic-beta"]
        assert not ccr.MARKER_RE.search(canon(body["messages"]))
        # Messages are still compressed, and the client's marker stays put.
        assert strip_cache_control(body["messages"])[1] == strip_cache_control(msgs)[1]

    def test_detection(self):
        from sensei.gateway.pipeline import is_oauth

        assert is_oauth({"authorization": "Bearer sk-ant-oat01-x"})
        assert is_oauth({"x-api-key": "k", "anthropic-beta": "oauth-2025-04-20"})
        assert not is_oauth({"x-api-key": "sk-ant-api"})


# ─── tools ──────────────────────────────────────────────────────────────────


class TestToolCompaction:
    def test_annotations_go_parameters_named_like_them_stay(self):
        out = tools.compact_tool("anthropic", TOOLS[0])
        schema = out["input_schema"]
        assert "$schema" not in schema and "title" not in schema
        assert "examples" not in schema["properties"]["command"]
        assert "title" in schema["properties"]
        assert schema["required"] == ["command"]

    def test_server_tools_pass(self):
        server = {"type": "web_search_20260209", "name": "web_search"}
        assert tools.compact_tool("anthropic", server) is server

    def test_deterministic(self):
        assert canon(tools.compact_tool("anthropic", TOOLS[0])) == canon(
            tools.compact_tool("anthropic", json.loads(json.dumps(TOOLS[0])))
        )

    def test_description_shortening_is_opt_in(self, monkeypatch):
        tool = {
            **TOOLS[1],
            "description": "Read a file. It returns lines.\n\nLong usage notes here.",
        }
        assert tools.compact_tool("anthropic", tool)["description"] == tool["description"]
        monkeypatch.setattr(settings, "gateway_tool_description_max_chars", 20)
        assert tools.compact_tool("anthropic", tool)["description"] == "Read a file."


class TestToolSearch:
    def _many(self, n: int = 14) -> list[dict]:
        base = [dict(TOOLS[0]), dict(TOOLS[1])]
        extra = [{**TOOLS[1], "name": f"mcp__srv__t{i}"} for i in range(n - 2)]
        out = base + extra
        out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
        return out

    def test_defers_non_core_and_moves_the_marker(self, monkeypatch):
        monkeypatch.setattr(settings, "gateway_tool_search", True)
        out, deferred = tools.apply_tool_search(self._many(), first_party=True)
        assert deferred == 12
        resident = [t for t in out if not t.get("defer_loading")]
        assert [t["name"] for t in resident] == ["Bash", "Read", "tool_search_tool_regex"]
        assert resident[1]["cache_control"] == {"type": "ephemeral"}
        assert not any("cache_control" in t for t in out if t.get("defer_loading"))

    def test_stands_down(self, monkeypatch):
        monkeypatch.setattr(settings, "gateway_tool_search", True)
        many = self._many()
        assert tools.apply_tool_search(many, first_party=False)[1] == 0
        assert tools.apply_tool_search(many[:5], first_party=True)[1] == 0
        already = [*many[:-1], {**many[-1], "defer_loading": True}]
        assert tools.apply_tool_search(already, first_party=True)[1] == 0
        monkeypatch.setattr(settings, "gateway_tool_search", False)
        assert tools.apply_tool_search(many, first_party=True)[1] == 0


# ─── cross-turn ─────────────────────────────────────────────────────────────


def _bash_turn(i: int, output: str) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": f"b{i}", "name": "Bash", "input": {"command": "cat f"}}
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": f"b{i}", "content": output}],
        },
    ]


SOURCE = "\n".join(f"def f{i}(x):\n    return x + {i}  # keep" for i in range(40))


class TestDedup:
    def test_repeat_becomes_a_reference_in_the_new_message_only(self, client, upstream):
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        first = [{"role": "user", "content": "go"}, *_bash_turn(1, SOURCE)]
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": first}, headers=KEY
        )
        second = [*first, *_bash_turn(2, SOURCE)]
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": second}, headers=KEY
        )
        forwarded = _body(sent[-1])["messages"]
        assert forwarded[2]["content"][0]["content"] == SOURCE  # earlier copy untouched
        assert forwarded[4]["content"][0]["content"].startswith(
            "[sensei: identical to the earlier Bash result b1"
        )

    def test_partial_repeat(self):
        from sensei.gateway.dedup import DedupIndex

        index = DedupIndex(4, 100)
        index.add(SOURCE, "Read result r1")
        changed = "header line\n" + SOURCE + "\nfooter"
        out = index.apply(changed)
        assert out.startswith(
            "header line\n[sensei: 80 lines identical to lines 1-80 of the earlier Read result r1"
        )
        assert out.endswith("footer")


def _read_edit(path: str = "/x/a.py") -> list[dict]:
    return [
        {"role": "user", "content": "fix it"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": path}}
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "r", "content": SOURCE}],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "e", "name": "Edit", "input": {"file_path": path}}
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "e", "content": "ok"}]},
    ]


class TestStaleReads:
    def test_stubbed_where_nothing_is_cached(self, client, upstream):
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        client.post(
            "/v1/messages",
            json={"model": "m", "tools": TOOLS, "messages": _read_edit()},
            headers=KEY,
        )
        result = _body(sent[-1])["messages"][2]["content"][0]["content"]
        assert result.startswith("[sensei: stale Read of /x/a.py")
        assert ccr.store.get(ccr.MARKER_RE.search(result).group(2)) == SOURCE

    def test_left_alone_under_thinking_or_cache_markers(self, client, upstream):
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        msgs = _read_edit()
        msgs[3]["content"].insert(0, {"type": "thinking", "thinking": "", "signature": "s"})
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": msgs}, headers=KEY
        )
        assert _body(sent[-1])["messages"][2]["content"][0]["content"] == SOURCE

        msgs = _read_edit("/x/b.py")
        msgs[-1]["content"][0]["cache_control"] = {"type": "ephemeral"}
        client.post(
            "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": msgs}, headers=KEY
        )
        assert _body(sent[-1])["messages"][2]["content"][0]["content"] == SOURCE


# ─── output shaping ─────────────────────────────────────────────────────────


class TestShaperTail:
    def test_instruction_stays_in_the_history(self, client, upstream, monkeypatch):
        from sensei import output_shaping

        monkeypatch.setattr(settings, "output_shaper", True)
        monkeypatch.setattr(settings, "output_holdout", 0.0)
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        turns = _turns(3)
        for msgs in turns[1:]:
            resp = client.post(
                "/v1/messages", json={"model": "m", "system": "sys", "messages": msgs}, headers=KEY
            )
            assert resp.headers["x-sensei-output-shaped"] == "true"
        first, second = (_body(r) for r in sent)
        assert first["system"] == second["system"] == "sys"
        assert first["messages"][-1]["content"][-1]["text"] == output_shaping.instruction()
        n = len(first["messages"])
        assert _no_cc(second["messages"][:n]) == _no_cc(first["messages"])

    def test_responses_are_shaped_too(self, client, upstream, monkeypatch):
        from sensei import output_shaping

        monkeypatch.setattr(settings, "output_shaper", True)
        monkeypatch.setattr(settings, "output_holdout", 0.0)
        monkeypatch.setattr(settings, "api_provider", "openai")
        sent, handlers = upstream
        handlers["*"] = lambda r: httpx.Response(200, json={"output": []})
        client.post(
            "/v1/responses",
            json={"model": "g", "input": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer k"},
        )
        last = _body(sent[-1])["input"][-1]
        assert last == {
            "type": "message",
            "role": "developer",
            "content": output_shaping.instruction(),
        }


# ─── opt-in extras ──────────────────────────────────────────────────────────


class TestExtras:
    def test_model_router(self, client, upstream, monkeypatch):
        monkeypatch.setattr(
            settings,
            "gateway_model_router",
            json.dumps(
                [
                    {
                        "to_model": "small",
                        "from_models": ["big"],
                        "max_input_tokens": 500,
                        "require_no_tools": True,
                    }
                ]
            ),
        )
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        resp = client.post(
            "/v1/messages",
            json={"model": "big", "messages": [{"role": "user", "content": "hi"}]},
            headers=KEY,
        )
        assert _body(sent[-1])["model"] == "small"
        assert resp.headers["x-sensei-routed-from"] == "big"
        client.post(
            "/v1/messages",
            json={"model": "big", "tools": TOOLS, "messages": [{"role": "user", "content": "hi"}]},
            headers=KEY,
        )
        assert _body(sent[-1])["model"] == "big"

    def test_response_cache(self, client, upstream, monkeypatch):
        monkeypatch.setattr(settings, "gateway_response_cache", True)
        sent, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply("cached?")
        body = {"model": "m", "temperature": 0, "messages": [{"role": "user", "content": "hi"}]}
        first = client.post("/v1/messages", json=body, headers=KEY)
        second = client.post("/v1/messages", json=body, headers=KEY)
        assert len(sent) == 1
        assert second.headers["x-sensei-cache"] == "hit"
        assert second.json()["content"] == first.json()["content"]
        other_key = {**KEY, "x-api-key": "sk-ant-other"}
        client.post("/v1/messages", json=body, headers=other_key)
        assert len(sent) == 2  # never served across credentials
        client.post("/v1/messages", json={**body, "temperature": 1}, headers=KEY)
        client.post("/v1/messages", json={**body, "temperature": 1}, headers=KEY)
        assert len(sent) == 4

    def test_tool_budget(self, client, upstream, monkeypatch):
        monkeypatch.setattr(settings, "gateway_tool_budgets", "Claude Code=50")
        _, handlers = upstream
        handlers["*"] = lambda r: _anthropic_reply()
        headers = {**KEY, "user-agent": "claude-cli/2.1 (external, cli)"}
        body = {"model": "m", "messages": [{"role": "user", "content": _log(40)}]}
        assert client.post("/v1/messages", json=body, headers=headers).status_code == 200
        refused = client.post("/v1/messages", json=body, headers=headers)
        assert refused.status_code == 429
        error = refused.json()["error"]
        assert (
            "Claude Code" in error["message"] and "SENSEI_GATEWAY_TOOL_BUDGETS" in error["message"]
        )
        other = client.post("/v1/messages", json=body, headers={**KEY, "user-agent": "cursor/1"})
        assert other.status_code == 200


def test_plain_streams_pass_byte_for_byte(client, upstream):
    _, handlers = upstream
    raw = (
        b'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":3}}}\n\n'
        b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )
    handlers["*"] = lambda r: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content=raw
    )
    resp = client.post(
        "/v1/messages",
        json={"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
        headers=KEY,
    )
    assert resp.content == raw


def test_chat_stream_is_spliced(client, upstream, intercept, monkeypatch):
    monkeypatch.setattr(settings, "api_provider", "openai")
    _, handlers = upstream
    cid = ccr.ccr_id(_rows())

    def chunk(data):
        return f"data: {json.dumps(data)}\n\n"

    call = {
        "index": 0,
        "id": "x1",
        "type": "function",
        "function": {"name": ccr.TOOL_NAME, "arguments": ""},
    }
    round1 = "".join(
        [
            chunk(
                {
                    "id": "c1",
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": "hm "}}],
                }
            ),
            chunk({"id": "c1", "choices": [{"index": 0, "delta": {"tool_calls": [call]}}]}),
            chunk(
                {
                    "id": "c1",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": json.dumps({"ccr": cid})},
                                    }
                                ]
                            },
                        }
                    ],
                }
            ),
            chunk(
                {"id": "c1", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}
            ),
            "data: [DONE]\n\n",
        ]
    )
    round2 = "".join(
        [
            chunk(
                {
                    "id": "c2",
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": "done"}}],
                }
            ),
            chunk({"id": "c2", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
            "data: [DONE]\n\n",
        ]
    )
    calls = []

    def handler(request):
        calls.append(_body(request))
        text = round1 if len(calls) == 1 else round2
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=text.encode()
        )

    handlers["*"] = handler
    fn_tools = [{"type": "function", "function": {"name": "sh", "parameters": {"type": "object"}}}]
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "g",
            "stream": True,
            "tools": fn_tools,
            "messages": [{"role": "user", "content": _rows()}],
        },
        headers={"Authorization": "Bearer k"},
    )
    text = resp.text
    assert ccr.TOOL_NAME not in text
    chunks = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data: {")]
    assert {c["id"] for c in chunks} == {"c1"}
    content = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert content == "hm done"
    assert text.count("[DONE]") == 1
    assert calls[1]["messages"][-1]["content"] == _rows()


def test_a_response_with_thinking_is_never_hidden(client, upstream, intercept):
    """Thinking is bound to the prefix that produced it, so a round that
    thinks goes to the client as it came: no follow-up, nothing merged."""
    _, handlers = upstream
    cid = ccr.ccr_id(_rows())
    replies = [
        {
            "id": "m1",
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "s1"},
                {"type": "tool_use", "id": "r1", "name": ccr.TOOL_NAME, "input": {"ccr": cid}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 5, "output_tokens": 5},
        },
        {
            "id": "m2",
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "s2"},
                {"type": "text", "text": "answer"},
            ],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 5},
        },
    ]
    handlers["*"] = lambda r: httpx.Response(200, json=replies.pop(0))
    msgs = [
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t", "content": _rows()}],
        }
    ]
    data = client.post(
        "/v1/messages", json={"model": "m", "tools": TOOLS, "messages": msgs}, headers=KEY
    ).json()
    assert [b["type"] for b in data["content"]] == ["thinking", "tool_use"]
    assert data["content"][1]["name"] == ccr.TOOL_NAME
    assert len(replies) == 1  # no follow-up was sent


class TestLinearTime:
    """Tool descriptions and tool output come from servers Sensei does not
    control; nothing that scans them may backtrack."""

    def test_sentence_split_matches_the_regex_it_replaced(self):
        import random
        import re

        oracle = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(\[])")
        rng = random.Random(20261016)
        alphabet = "ab A9.!? \n\t('`\"["
        for _ in range(4000):
            s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            assert tools.split_sentences(s) == oracle.split(s), repr(s)
            assert tools.split_sentences(s, 1) == oracle.split(s, maxsplit=1), repr(s)

    PAYLOADS = {  # noqa: RUF012
        "dot-then-spaces": lambda: "." + " " * 200_000,
        "dot-space-runs": lambda: ". " * 100_000,
        "mixed-whitespace": lambda: "a." + "\t \n" * 70_000 + "a",
        "open-markers": lambda: "[sensei: " * 50_000,
        "unclosed-marker": lambda: "[sensei: " + "x" * 200_000 + "; retrieve ccr=",
    }

    @pytest.mark.parametrize("kind", sorted(PAYLOADS))
    def test_pathological_input_is_fast(self, kind):
        import time

        payload = self.PAYLOADS[kind]()

        started = time.perf_counter()
        tools.first_sentence(payload)
        tools.shorten_description(payload, 100)
        ccr.has_marker(payload)
        ccr.MARKER_RE.findall(payload)
        assert time.perf_counter() - started < 1.0

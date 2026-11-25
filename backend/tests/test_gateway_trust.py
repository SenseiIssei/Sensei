"""What a client may rely on when it points at Sensei instead of the provider.

Its own words arrive unchanged, its account and headers are its own, nothing
that fails inside Sensei fails its turn, and nobody else gets in.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sensei import savings as savings_mod
from sensei.config import settings
from sensei.gateway import pipeline
from sensei.gateway.session import live_zone
from sensei.main import app
from sensei.routers import gateway
from sensei.security.csrf import host_allowed
from sensei.security.rate_limit import rate_limiter

Handler = Callable[[httpx.Request], httpx.Response]

PASTED = '''Please fix `load`. In order to keep the API, the error must stay "Invalid   login".

```python
import os
# IMPORTANT: keep this comment, the linter checks it
def load(path):
    """Load the thing.

    Raises: ValueError when bad.
    """
    x = 1  # noqa: F841
    return open(path).read()   # TODO(ana): close
```
'''

ANTHROPIC = {"x-api-key": "sk-ant-client", "anthropic-version": "2023-06-01"}
OPENAI = {"authorization": "Bearer sk-client"}
# In two parts: secret scanners read this file too.
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


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
            return handler(request) if handler else httpx.Response(200, json={"ok": True})

        return httpx.AsyncClient(base_url=base, transport=httpx.MockTransport(dispatch))

    monkeypatch.setattr(gateway, "_pooled_client", factory)
    monkeypatch.setattr(settings, "savings_db", str(tmp_path / "savings.db"))
    monkeypatch.setattr(settings, "upstream_retries", 0)
    monkeypatch.setattr(savings_mod, "_tracker", None, raising=False)
    live_zone.clear()
    return sent, handlers


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _user(text: object, **extra: object) -> dict:
    return {
        "model": "m",
        "max_tokens": 5,
        "messages": [{"role": "user", "content": text}],
        **extra,
    }


class TestWhatPeopleWriteArrives:
    @pytest.mark.parametrize("path", ["/v1/messages", "/v1/chat/completions"])
    def test_pasted_code_and_wording_are_untouched(self, client, upstream, path) -> None:
        sent, _ = upstream
        client.post(path, json=_user(PASTED), headers={**ANTHROPIC, **OPENAI})
        assert json.loads(sent[0].content)["messages"][0]["content"] == PASTED

    @pytest.mark.parametrize("as_parts", [False, True])
    def test_responses_api_too(self, client, upstream, as_parts) -> None:
        sent, _ = upstream
        content = [{"type": "input_text", "text": PASTED}] if as_parts else PASTED
        body = {"model": "m", "input": [{"role": "user", "content": content}]}
        client.post("/v1/responses", json=body, headers=OPENAI)
        assert json.loads(sent[0].content)["input"][0]["content"] == content

    def test_a_bare_string_input_too(self, client, upstream) -> None:
        sent, _ = upstream
        client.post("/v1/responses", json={"model": "m", "input": PASTED}, headers=OPENAI)
        assert json.loads(sent[0].content)["input"] == PASTED

    def test_the_system_prompt_is_untouched(self, client, upstream) -> None:
        sent, _ = upstream
        rules = "You are a careful assistant. In order to help, it is very important to ask. " * 4
        client.post("/v1/messages", json=_user("hi", system=rules), headers=ANTHROPIC)
        assert json.loads(sent[0].content)["system"] == rules

    def test_tool_output_pasted_by_the_client_still_shrinks(self, client, upstream) -> None:
        """Cline puts command output into user messages. A log is still a log."""
        sent, _ = upstream
        log = "\n".join(
            f"2026-11-25 12:00:{i % 60:02d} INFO worker: heartbeat ok" for i in range(400)
        )
        client.post("/v1/messages", json=_user(log), headers=ANTHROPIC)
        assert len(sent[0].content) < len(log) / 2

    def test_rewriting_is_there_for_whoever_asks(self, client, upstream, monkeypatch) -> None:
        monkeypatch.setattr(settings, "gateway_rewrite_user_text", True)
        sent, _ = upstream
        client.post("/v1/messages", json=_user(PASTED), headers=ANTHROPIC)
        assert json.loads(sent[0].content)["messages"][0]["content"] != PASTED


class TestRetrievedOriginals:
    """An original the model fetched must arrive, or it fetches it again and again."""

    LOG = "\n".join(
        f"2026-11-25 12:00:{i % 60:02d} INFO worker-{i % 7}: heartbeat ok" for i in range(400)
    )

    @staticmethod
    def _tools(api: str, name: str) -> list[dict]:
        if api == "openai":
            return [{"type": "function", "function": {"name": name, "parameters": {}}}]
        return [{"name": name, "input_schema": {"type": "object"}}]

    @pytest.mark.parametrize(
        "name",
        [
            "sensei_retrieve",
            "mcp__sensei__sensei_retrieve",
            "sensei__sensei_retrieve",
            "sensei-sensei_retrieve",
            "mcp__sensei__sensei_compress",
            "mcp__sensei__sensei_call_tool",
        ],
    )
    def test_anthropic(self, client, upstream, name) -> None:
        sent, _ = upstream
        call = {"type": "tool_use", "id": "t1", "name": name, "input": {"ccr_id": "0" * 16}}
        other = {"type": "tool_use", "id": "t2", "name": "Bash", "input": {}}
        results = [
            {"type": "tool_result", "tool_use_id": "t1", "content": self.LOG},
            {"type": "tool_result", "tool_use_id": "t2", "content": "x\n" + self.LOG},
        ]
        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": [call, other]},
            {"role": "user", "content": results},
        ]
        body = {"model": "m", "messages": messages, "tools": self._tools("anthropic", name)}
        client.post("/v1/messages", json=body, headers=ANTHROPIC)
        blocks = json.loads(sent[0].content)["messages"][2]["content"]
        assert blocks[0]["content"] == self.LOG
        assert len(blocks[1]["content"]) < len(self.LOG) / 2, "the other result still shrinks"

    def test_openai_chat(self, client, upstream) -> None:
        sent, _ = upstream
        name = "mcp__sensei__sensei_retrieve"
        call = {"id": "c1", "type": "function", "function": {"name": name, "arguments": "{}"}}
        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": None, "tool_calls": [call]},
            {"role": "tool", "tool_call_id": "c1", "content": self.LOG},
        ]
        body = {"model": "m", "messages": messages, "tools": self._tools("openai", name)}
        client.post("/v1/chat/completions", json=body, headers=OPENAI)
        assert json.loads(sent[0].content)["messages"][2]["content"] == self.LOG

    def test_responses(self, client, upstream) -> None:
        sent, _ = upstream
        name = "mcp__sensei__sensei_retrieve"
        items = [
            {"role": "user", "content": "go"},
            {"type": "function_call", "call_id": "c1", "name": name, "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": self.LOG},
        ]
        client.post("/v1/responses", json={"model": "m", "input": items}, headers=OPENAI)
        assert json.loads(sent[0].content)["input"][2]["output"] == self.LOG

    def test_a_tool_that_only_sounds_like_it(self, client, upstream) -> None:
        sent, _ = upstream
        call = {"type": "tool_use", "id": "t1", "name": "notsensei_retrieve_all", "input": {}}
        messages = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": [call]},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": self.LOG}],
            },
        ]
        client.post("/v1/messages", json={"model": "m", "messages": messages}, headers=ANTHROPIC)
        content = json.loads(sent[0].content)["messages"][2]["content"][0]["content"]
        assert len(content) < len(self.LOG) / 2


class TestNothingInsideSenseiFailsTheTurn:
    @pytest.mark.parametrize(
        ("path", "headers"), [("/v1/messages", ANTHROPIC), ("/v1/chat/completions", OPENAI)]
    )
    def test_half_an_emoji(self, client, upstream, path, headers) -> None:
        """JavaScript agents cut strings by UTF-16 unit and send \\ud83d alone."""
        sent, _ = upstream
        log = "\ud83d cut off\n" + "2026-11-25 12:00:00 INFO ok\n" * 200
        for text in ("short \ud83d text", log):
            raw = json.dumps(_user(text))
            assert client.post(path, content=raw, headers=headers).status_code == 200
            assert "\ud83d" in json.loads(sent[-1].content)["messages"][0]["content"]

    def test_a_crashing_compressor_costs_only_the_saving(
        self, client, upstream, monkeypatch
    ) -> None:
        class Broken:
            def compress(self, *_: object, **__: object) -> None:
                raise RuntimeError("bug")

        monkeypatch.setattr(gateway, "_router", Broken)
        sent, _ = upstream
        assert client.post("/v1/messages", json=_user(PASTED), headers=ANTHROPIC).status_code == 200
        assert json.loads(sent[0].content)["messages"][0]["content"] == PASTED

    def test_a_crashing_pipeline_forwards_the_request(self, client, upstream, monkeypatch) -> None:
        def boom(*_: object, **__: object) -> None:
            raise RuntimeError("bug")

        monkeypatch.setattr(pipeline, "prepare", boom)
        sent, _ = upstream
        body = _user(PASTED)
        r = client.post("/v1/messages", json=body, headers=ANTHROPIC)
        assert r.status_code == 200
        assert json.loads(sent[0].content) == body

    def test_redaction_still_applies_when_the_pipeline_crashed(
        self, client, upstream, monkeypatch
    ) -> None:
        def boom(*_: object, **__: object) -> None:
            raise RuntimeError("bug")

        monkeypatch.setattr(pipeline, "prepare", boom)
        monkeypatch.setattr(settings, "redaction_enabled", True)
        sent, _ = upstream
        client.post("/v1/messages", json=_user(f"key {FAKE_KEY}"), headers=ANTHROPIC)
        assert b"AKIA" not in sent[0].content

    def test_nan_is_a_client_error(self, client, upstream) -> None:
        r = client.post("/v1/messages", content='{"messages":[],"temperature":NaN}')
        assert r.status_code == 400

    def test_a_model_that_is_not_a_string(self, client, upstream) -> None:
        body = {**_user("hi"), "model": 5}
        assert client.post("/v1/messages", json=body, headers=ANTHROPIC).status_code == 200

    def test_an_agent_is_not_rate_limited_by_sensei(self, client, upstream, monkeypatch) -> None:
        monkeypatch.setattr(rate_limiter, "max_requests", 5)
        codes = {
            client.post("/v1/messages", json=_user("hi"), headers=ANTHROPIC).status_code
            for _ in range(20)
        }
        codes |= {client.post("/hooks/claude/post-tool-use", json={}).status_code for _ in range(9)}
        assert codes == {200}

    def test_but_other_clients_are(self, client, upstream, monkeypatch) -> None:
        monkeypatch.setattr(rate_limiter, "max_requests", 5)
        forwarded = {**ANTHROPIC, "x-forwarded-for": "203.0.113.9"}
        codes = [
            client.post("/v1/messages", json=_user("hi"), headers=forwarded).status_code
            for _ in range(8)
        ]
        assert codes.count(429) == 3
        assert client.get("/api/settings").status_code == 429


class TestTheClientsOwnRequest:
    def test_account_project_and_beta_headers_reach_the_provider(self, client, upstream) -> None:
        """Without the organisation header OpenAI bills the key's default one."""
        sent, _ = upstream
        extra = {
            "OpenAI-Organization": "org-1",
            "OpenAI-Project": "proj-1",
            "Idempotency-Key": "once",
            "User-Agent": "codex/1.2",
        }
        client.post("/v1/chat/completions", json=_user("hi"), headers={**OPENAI, **extra})
        for name, value in extra.items():
            assert sent[0].headers[name] == value

    def test_private_headers_do_not(self, client, upstream) -> None:
        sent, _ = upstream
        private = {"Cookie": "s=1", "X-Sensei-Client": "x", "X-Forwarded-For": "10.0.0.1"}
        client.post("/v1/messages", json=_user("hi"), headers={**ANTHROPIC, **private})
        assert not {k.lower() for k in private} & set(sent[0].headers)

    def test_the_query_string_is_kept(self, client, upstream) -> None:
        sent, _ = upstream
        client.post("/v1/messages?beta=true", json=_user("hi"), headers=ANTHROPIC)
        assert sent[0].url.query == b"beta=true"

    def test_the_fallback_gets_no_account_headers(self, client, upstream, monkeypatch) -> None:
        sent, handlers = upstream
        handlers["*"] = lambda r: httpx.Response(503)
        monkeypatch.setattr(settings, "fallback_enabled", True)
        monkeypatch.setattr(settings, "fallback_base_url", "http://local.test")
        headers = {**OPENAI, "OpenAI-Organization": "org-1"}
        client.post("/v1/chat/completions", json=_user("hi"), headers=headers)
        assert sent[-1].url.host == "local.test"
        assert "openai-organization" not in sent[-1].headers
        assert sent[-1].headers["authorization"] == "Bearer sensei-fallback"


class TestOtherEndpoints:
    def test_embeddings_are_relayed(self, client, upstream) -> None:
        sent, _ = upstream
        r = client.post("/v1/embeddings", json={"input": "x"}, headers=OPENAI)
        assert r.status_code == 200
        assert sent[0].url.path.endswith("/embeddings")
        assert sent[0].headers["authorization"] == "Bearer sk-client"

    def test_batches_go_to_anthropic(self, client, upstream) -> None:
        sent, _ = upstream
        client.get("/v1/messages/batches/msgbatch_1/results?limit=2", headers=ANTHROPIC)
        assert sent[0].url.host == "api.anthropic.com"
        assert sent[0].url.path.endswith("/messages/batches/msgbatch_1/results")
        assert sent[0].headers["x-api-key"] == "sk-ant-client"

    def test_an_error_status_is_kept(self, client, upstream) -> None:
        _, handlers = upstream
        handlers["*"] = lambda r: httpx.Response(418, json={"error": "teapot"})
        r = client.get("/v1/files", headers=OPENAI)
        assert (r.status_code, r.json()) == (418, {"error": "teapot"})

    def test_models_come_from_the_provider_when_the_client_has_a_key(
        self, client, upstream
    ) -> None:
        _, handlers = upstream
        handlers["*"] = lambda r: httpx.Response(200, json={"data": [{"id": "real"}]})
        assert client.get("/v1/models", headers=OPENAI).json()["data"][0]["id"] == "real"
        assert client.get("/v1/models").json()["data"][0]["owned_by"].startswith("sensei:")

    def test_models_survive_a_provider_that_has_no_list(self, client, upstream) -> None:
        _, handlers = upstream
        handlers["*"] = lambda r: httpx.Response(404)
        assert client.get("/v1/models", headers=OPENAI).json()["object"] == "list"

    def test_the_configured_key_is_not_lent_out(self, client, upstream, monkeypatch) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-server")
        sent, _ = upstream
        assert client.delete("/v1/messages/batches/b").status_code == 401
        assert not sent

    @pytest.mark.parametrize("path", ["organization/usage", "files/..%2Fadmin", ".hidden"])
    def test_unknown_or_odd_paths_are_refused(self, client, upstream, path) -> None:
        sent, _ = upstream
        assert client.get(f"/v1/{path}", headers=OPENAI).status_code in (404, 405)
        assert not sent or ".." not in str(sent[0].url)

    def test_redaction_covers_what_it_can_read_and_refuses_the_rest(
        self, client, upstream, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "redaction_enabled", True)
        sent, _ = upstream
        client.post("/v1/embeddings", json={"input": FAKE_KEY}, headers=OPENAI)
        assert b"AKIA" not in sent[0].content
        r = client.post("/v1/files", content=b"--binary", headers=OPENAI)
        assert r.status_code == 403
        assert len(sent) == 1


class TestNobodyElseGetsIn:
    EVIL = "https://evil.example"

    @pytest.mark.parametrize("origin", [EVIL, "null"])
    def test_a_web_page_cannot_spend_the_configured_key(
        self, client, upstream, monkeypatch, origin
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-server")
        sent, _ = upstream
        headers = {"origin": origin, "content-type": "text/plain"}
        r = client.post("/v1/messages", content=json.dumps(_user("hi")), headers=headers)
        assert r.status_code == 403
        assert not sent

    def test_desktop_apps_and_the_own_ui_still_can(self, client, upstream) -> None:
        for origin in ("vscode-file://vscode-app", "http://localhost:7000"):
            headers = {**ANTHROPIC, "origin": origin}
            r = client.post("/v1/messages", json=_user("hi"), headers=headers)
            assert r.status_code == 200, origin

    @pytest.mark.parametrize(
        ("host", "ok"),
        [
            ("127.0.0.1:7000", True),
            ("localhost:7000", True),
            ("[::1]:7000", True),
            ("192.168.1.20:7000", True),
            ("host.docker.internal:7000", True),
            ("", True),
            ("evil.example:7000", False),
            ("127.0.0.1.evil.example", False),
            ("localhost.evil.example:7000", False),
            ("evil.example.", False),
        ],
    )
    def test_which_names_are_answered(self, host, ok) -> None:
        assert host_allowed(host) is ok

    def test_dns_rebinding_is_refused(self, client) -> None:
        """Same origin as far as the browser can tell, so only Host gives it away."""
        rebound = {"host": "evil.example:7000", "origin": "http://evil.example:7000"}
        assert client.get("/api/settings", headers=rebound).status_code == 403
        assert client.put("/api/settings", json={}, headers=rebound).status_code == 403

    def test_a_public_name_can_be_allowed(self, client, monkeypatch) -> None:
        headers = {"host": "sensei.example.org"}
        assert client.get("/health", headers=headers).status_code == 403
        monkeypatch.setattr(settings, "allowed_hosts", "sensei.example.org")
        assert client.get("/health", headers=headers).status_code == 200

    def test_a_web_page_cannot_open_the_chat_socket(self, client) -> None:
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/api/chat/ws", headers={"origin": self.EVIL}),
        ):
            pass

    def test_nor_through_a_rebound_name(self, client) -> None:
        headers = {"host": "evil.example", "origin": "http://evil.example"}
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/api/chat/ws", headers=headers),
        ):
            pass

    def test_the_chat_socket_needs_the_token_too(self, client, monkeypatch) -> None:
        monkeypatch.setattr(settings, "auth_enabled", True)
        monkeypatch.setattr(settings, "auth_token", "secret")
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/chat/ws"):
            pass
        with client.websocket_connect("/api/chat/ws?token=secret") as ws:
            ws.close()


class TestSenseisOwnToken:
    @pytest.fixture(autouse=True)
    def _auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "auth_enabled", True)
        monkeypatch.setattr(settings, "auth_token", "sensei-secret")

    @pytest.mark.parametrize(
        "headers",
        [
            {"x-api-key": "sensei-secret"},
            {"authorization": "Bearer sensei-secret"},
            {"x-sensei-token": "sensei-secret"},
        ],
    )
    def test_it_never_reaches_the_provider(self, client, upstream, monkeypatch, headers) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-server")
        sent, _ = upstream
        r = client.post("/v1/messages?token=sensei-secret", json=_user("hi"), headers=headers)
        assert r.status_code == 200
        assert "sensei-secret" not in str(sent[0].headers) + str(sent[0].url)
        assert sent[0].headers["x-api-key"] == "sk-ant-server"

    def test_it_works_next_to_the_clients_own_key(self, client, upstream) -> None:
        sent, _ = upstream
        headers = {**OPENAI, "x-sensei-token": "sensei-secret"}
        client.post("/v1/chat/completions", json=_user("hi"), headers=headers)
        assert sent[0].headers["authorization"] == "Bearer sk-client"

    def test_a_token_with_an_umlaut_is_wrong_not_a_crash(self, client) -> None:
        assert client.get("/api/settings", params={"token": "schlüssel"}).status_code == 401


# ── through a real server: what TestClient cannot show ──────────────────────


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # not the main thread
        pass


@pytest.fixture
def base_url():
    server = _Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


class _Dies(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'event: message_start\ndata: {"type":"message_start","message":{"usage":{}}}\n\n'
        raise httpx.ReadError("gone")


@pytest.mark.parametrize("tools", [False, True], ids=["plain", "with-retrieve"])
def test_a_stream_that_breaks_off_looks_broken(base_url, upstream, tools, monkeypatch) -> None:
    """Half an answer must not end like a whole one: the client would keep it."""
    _, handlers = upstream
    handlers["*"] = lambda r: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=_Dies()
    )
    monkeypatch.setattr(settings, "gateway_retrieve_intercept", tools)
    body = _user("hi", stream=True)
    if tools:
        body["tools"] = [{"name": "Bash", "input_schema": {"type": "object"}}]
    with (
        pytest.raises(httpx.RemoteProtocolError),
        httpx.stream("POST", f"{base_url}/v1/messages", json=body, headers=ANTHROPIC) as r,
    ):
        assert r.status_code == 200
        r.read()


def test_a_slow_preparation_does_not_stop_everything_else(base_url, upstream, monkeypatch) -> None:
    real = pipeline.prepare

    def slow(*args: object, **kwargs: object):
        time.sleep(1.5)
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "prepare", slow)
    worker = threading.Thread(
        target=lambda: httpx.post(
            f"{base_url}/v1/messages", json=_user("hi"), headers=ANTHROPIC, timeout=20
        )
    )
    worker.start()
    time.sleep(0.3)
    started = time.perf_counter()
    assert httpx.get(f"{base_url}/health", timeout=20).status_code == 200
    took = time.perf_counter() - started
    worker.join()
    assert took < 0.8

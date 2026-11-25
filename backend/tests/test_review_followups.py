"""What an independent review of the first version of these changes found."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sensei import atomic
from sensei import config as config_mod
from sensei import savings as savings_mod
from sensei.audit import get_audit_log
from sensei.compression.ccr import CCRStore
from sensei.compression.router import ContentRouter
from sensei.config import settings
from sensei.gateway import extras
from sensei.gateway.session import live_zone
from sensei.main import app
from sensei.routers import gateway
from sensei.security import users
from sensei.security.crypto import LocalCrypto
from sensei.security.csrf import host_allowed
from sensei.security.local_secret import _read_or_create, local_secret

Handler = Callable[[httpx.Request], httpx.Response]
OPENAI = {"authorization": "Bearer sk-client"}
ANTHROPIC = {"x-api-key": "sk-ant-client", "anthropic-version": "2023-06-01"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    sent: list[httpx.Request] = []
    handlers: dict[str, Handler] = {}
    closed: list[httpx.Response] = []

    class Counting(httpx.AsyncByteStream):
        def __init__(self, body: bytes) -> None:
            self.body = body

        async def __aiter__(self):
            yield self.body

        async def aclose(self) -> None:
            closed.append(self)  # type: ignore[arg-type]

    def factory(base_url: str) -> httpx.AsyncClient:
        def dispatch(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            status = handlers["*"](request).status_code if "*" in handlers else 200
            return httpx.Response(
                status, headers={"content-type": "application/json"}, stream=Counting(b"{}")
            )

        return httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(dispatch))

    monkeypatch.setattr(gateway, "_pooled_client", factory)
    monkeypatch.setattr(settings, "savings_db", str(tmp_path / "savings.db"))
    monkeypatch.setattr(settings, "upstream_retries", 0)
    monkeypatch.setattr(savings_mod, "_tracker", None, raising=False)
    live_zone.clear()
    return sent, handlers, closed


class TestRelay:
    def test_a_failed_model_list_gives_its_connection_back(self, client, upstream) -> None:
        """100 polls with an expired key used up the pool, and then nothing worked."""
        sent, handlers, closed = upstream
        handlers["*"] = lambda r: httpx.Response(401)
        for _ in range(3):
            assert client.get("/v1/models", headers=OPENAI).status_code == 200
        assert len(sent) == len(closed) == 3

    @pytest.mark.parametrize(
        "body",
        [
            {"model": "claude-opus-5"},
            {"requests": [{"params": {"model": "ok"}}, {"params": {"model": "claude-opus-5"}}]},
        ],
    )
    def test_the_model_block_list_reaches_into_a_batch(
        self, client, upstream, monkeypatch, body
    ) -> None:
        monkeypatch.setattr(settings, "blocked_models", "opus")
        sent, _, _ = upstream
        r = client.post("/v1/messages/batches", json=body, headers=ANTHROPIC)
        assert r.status_code == 403
        assert not sent

    def test_budgets_and_the_audit_log_cover_it(
        self, client, upstream, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setattr(get_audit_log(), "path", tmp_path / "audit.jsonl")
        client.post("/v1/embeddings", json={"input": "secret text"}, headers=OPENAI)
        line = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert '"gateway.relay"' in line
        assert "secret text" not in line
        monkeypatch.setattr(settings, "gateway_tool_budgets", "*=1")
        monkeypatch.setattr(
            extras.budget_meter, "check", lambda tool: {"tool": tool, "message": "over"}
        )
        assert client.post("/v1/embeddings", json={}, headers=OPENAI).status_code == 429

    def test_an_api_key_alone_is_not_sent_as_an_empty_bearer(self, client, upstream) -> None:
        sent, _, _ = upstream
        r = client.post("/v1/embeddings", json={}, headers={"x-api-key": "k"})
        assert r.status_code == 401
        assert not sent

    def test_an_anthropic_key_never_goes_to_the_other_provider(
        self, client, upstream, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "auth_enabled", True)
        monkeypatch.setattr(settings, "auth_token", "sensei-secret")
        sent, _, _ = upstream
        headers = {"x-api-key": "sensei-secret", "authorization": "Bearer sk-ant-mine"}
        client.get("/v1/models", headers=headers)
        assert sent[0].url.host == "api.anthropic.com"

    def test_a_trailing_slash_still_redirects(self, client, upstream) -> None:
        r = client.post("/v1/chat/completions/", json={}, headers=OPENAI, follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"].endswith("/v1/chat/completions")


class TestForwardedHeaders:
    def test_an_umlaut_costs_the_header_not_the_request(self, client, upstream) -> None:
        sent, _, _ = upstream
        headers = [("authorization", "Bearer k"), ("x-title", "Müller".encode()), ("x-app", "cli")]
        body = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        r = client.post("/v1/chat/completions", json=body, headers=headers)
        assert r.status_code == 200
        assert "x-title" not in sent[0].headers
        assert sent[0].headers["x-app"] == "cli"

    def test_repeated_beta_headers_are_one_list(self, client, upstream) -> None:
        sent, _, _ = upstream
        headers = [*ANTHROPIC.items(), ("anthropic-beta", "a-1"), ("anthropic-beta", "b-2")]
        body = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        client.post("/v1/messages", json=body, headers=headers)
        assert sent[0].headers["anthropic-beta"] == "a-1,b-2"


class TestEveryByteOfWhatPeopleWrote:
    TEXTS = (
        "line one\r\nline two\r\n" * 30,
        "a note with \x1b[31mred\x1b[0m in it and more words after it, " * 5,
        f"zero{chr(0x200B)}width and a no{chr(0xA0)}break space, both meant, " * 6,
        "progress 10%\rprogress 90%\r and then the sentence goes on for a while " * 3,
        "here is the key material: " + "QUJDREVGR0hJSktMTU5PUA" * 200,
    )

    @pytest.mark.parametrize("text", TEXTS, ids=["crlf", "ansi", "invisible", "cr", "blob"])
    @pytest.mark.parametrize("path", ["/v1/messages", "/v1/chat/completions"])
    def test_user_text(self, client, upstream, path, text) -> None:
        sent, _, _ = upstream
        body = {"model": "m", "messages": [{"role": "user", "content": text}]}
        client.post(path, json=body, headers={**ANTHROPIC, **OPENAI})
        assert json.loads(sent[0].content)["messages"][0]["content"] == text

    @pytest.mark.parametrize("role", ["system", "developer", "critic"])
    def test_other_roles_inside_anthropic_messages(self, client, upstream, role) -> None:
        sent, _, _ = upstream
        text = "In order to help, it is very important to ask before you actually act. " * 12
        body = {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}, {"role": role, "content": text}],
        }
        client.post("/v1/messages", json=body, headers=ANTHROPIC)
        assert json.loads(sent[0].content)["messages"][1]["content"] == text

    def test_a_tool_result_still_loses_its_progress_bars(self) -> None:
        text = "\x1b[32mok\x1b[0m step\n" * 5 + "10%\r20%\r30%\r100% done\n" * 10
        result = ContentRouter(enable_caching=False).compress(text, edit_target=True)
        assert "\x1b" not in result.compressed


class TestStoreOfOriginals:
    def _age(self, store: CCRStore, ccr_id: str, seconds: float) -> None:
        store._hot[ccr_id]["stored_at"] -= seconds

    def test_an_old_copy_in_memory_does_not_delete_a_new_file(self, tmp_path: Path) -> None:
        a, b = CCRStore(tmp_path, ttl_hours=1), CCRStore(tmp_path, ttl_hours=1)
        a.store("text", "t", ccr_id="abc")
        self._age(a, "abc", 7200)
        b.store("text", "t", ccr_id="abc")
        assert a.retrieve("abc") == "text"
        assert b.retrieve("abc") == "text"

    def test_what_is_really_old_goes(self, tmp_path: Path) -> None:
        a = CCRStore(tmp_path, ttl_hours=1)
        a.store("text", "t", ccr_id="abc")
        path = tmp_path / "abc.json"
        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["stored_at"] -= 7200
        path.write_text(json.dumps(entry), encoding="utf-8")
        os.utime(path, (time.time() - 7200,) * 2)
        assert CCRStore(tmp_path, ttl_hours=1).retrieve("abc") is None
        assert not path.exists()


class TestInPlaceWholeOrNotAtAll:
    @pytest.fixture
    def home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        home = tmp_path / ".sensei"
        monkeypatch.setattr(config_mod, "SENSEI_HOME", home)
        _read_or_create.cache_clear()
        yield home
        _read_or_create.cache_clear()

    def test_publishing_never_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "x"
        assert atomic.publish_new(b"first", target)
        assert not atomic.publish_new(b"second", target)
        assert target.read_bytes() == b"first"
        assert [p.name for p in tmp_path.iterdir()] == ["x"]

    def test_a_directory_is_there_whole_or_not(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        old = tmp_path / "old" / ".sensei_memory"
        old.mkdir(parents=True)
        (old / "a").write_text("1", encoding="utf-8")
        monkeypatch.setattr(config_mod, "_former_homes", lambda: [tmp_path / "old"])

        def cut_off(*_: object, **__: object) -> None:
            raise OSError("no space left")

        real = atomic.shutil.copytree
        monkeypatch.setattr(atomic.shutil, "copytree", cut_off)
        config_mod.adopt(home / "memory", ".sensei_memory")
        assert not (home / "memory").exists()
        monkeypatch.setattr(atomic.shutil, "copytree", real)
        config_mod.adopt(home / "memory", ".sensei_memory")
        assert (home / "memory" / "a").exists(), "the next start tries again"

    def test_what_was_deleted_stays_deleted(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".sensei_users.json").write_text('{"a":{}}', encoding="utf-8")
        monkeypatch.setattr(config_mod, "_former_homes", lambda: [tmp_path])
        assert users._load_users() == {"a": {}}
        (home / "users.json").unlink()
        assert users._load_users() == {}

    def test_eight_processes_agree_on_one_secret(self, tmp_path: Path) -> None:
        code = "from sensei.security.local_secret import local_secret; print(local_secret('k'))"
        env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
        started = [
            subprocess.Popen(  # noqa: S603 - our own interpreter and code
                [sys.executable, "-c", code], stdout=subprocess.PIPE, env=env, text=True
            )
            for _ in range(8)
        ]
        values = {p.communicate(timeout=60)[0].strip() for p in started}
        assert len(values) == 1
        assert len(values.pop()) == 64

    @pytest.mark.parametrize("content", ["", "short", "zz" * 32])
    def test_a_damaged_key_is_not_used_and_nothing_is_lost(self, home: Path, content: str) -> None:
        home.mkdir()
        (home / "local-key").write_text(content, encoding="ascii")
        assert local_secret("local-key") is None
        blob = LocalCrypto().encrypt("x")
        _read_or_create.cache_clear()
        assert LocalCrypto().decrypt(blob) == "x", "a key that can be derived again"
        assert (home / "local-key").read_text(encoding="ascii") == content


@pytest.mark.parametrize(
    ("host", "local", "ok"),
    [
        ("foo", "127.0.0.1", False),
        ("evil.local:7000", "127.0.0.1", False),
        ("evil.local:7000", "::1", False),
        ("backend:7000", "172.18.0.3", True),
        ("desk.local:7000", "192.168.1.20", True),
        ("host.docker.internal:7000", "127.0.0.1", True),
        ("localhost:7000", "127.0.0.1", True),
        ("evil.example", "192.168.1.20", False),
    ],
)
def test_names_that_mean_nothing_on_loopback(host: str, local: str, ok: bool) -> None:
    """Whoever runs the Wi-Fi can answer for `http://foo/` and then say 127.0.0.1."""
    assert host_allowed(host, local) is ok


def test_a_follow_up_is_not_sent_under_the_same_idempotency_key(client, monkeypatch) -> None:
    """The gateway's own second request has another body than the client's first."""
    sent: list[httpx.Request] = []
    call = {"type": "tool_use", "id": "t", "name": "sensei_retrieve", "input": {"ccr": "0" * 16}}

    def dispatch(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        first = len(sent) == 1
        content = [call] if first else [{"type": "text", "text": "done"}]
        reason = "tool_use" if first else "end_turn"
        return httpx.Response(200, json={"content": content, "stop_reason": reason, "usage": {}})

    monkeypatch.setattr(
        gateway,
        "_pooled_client",
        lambda base: httpx.AsyncClient(base_url=base, transport=httpx.MockTransport(dispatch)),
    )
    monkeypatch.setattr(settings, "gateway_retrieve_intercept", True)
    live_zone.clear()
    body = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
    }
    client.post("/v1/messages", json=body, headers={**ANTHROPIC, "idempotency-key": "once"})
    assert [r.headers.get("idempotency-key") for r in sent] == ["once", None]

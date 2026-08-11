"""Reaching new providers, and getting a local model running.

Two failure modes this guards against, both of which had already happened:
a curated model list that ages into wrongness, and a local server gated behind
an API key it does not have.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from sensei.config import settings
from sensei.main import app
from sensei.routers import setup as setup_mod
from sensei.routers.settings import PROVIDER_CATALOG


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestNotPinningModelNames:
    def test_new_providers_ship_no_guessed_model(self) -> None:
        """A default model id is a guess with a shelf life. The catalog still
        offered gpt-4o and claude-3.5-sonnet long after both were superseded,
        and a stale id fails at request time with a message about the model
        rather than about the default."""
        for provider in ("moonshot", "dashscope", "xai", "cerebras", "deepinfra"):
            assert getattr(settings, f"{provider}_api_model") == ""
            assert urlparse(getattr(settings, f"{provider}_api_base_url")).scheme == "https"

    def test_they_are_all_listed_live(self) -> None:
        """Which is the other half: no pinned default is only workable if the
        real list can be fetched."""
        for provider in ("moonshot", "dashscope", "xai", "cerebras", "deepinfra"):
            assert provider in setup_mod._LIVE_MODEL_PROVIDERS
            assert provider in PROVIDER_CATALOG


class TestLocalServers:
    def test_a_local_server_is_not_gated_behind_an_api_key(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It runs on this machine. There is no account, so there is no key, and
        demanding one before showing the model list makes a working local server
        look unusable."""
        seen: dict[str, Any] = {}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json() -> dict[str, Any]:
                return {"data": [{"id": "some-local-model"}]}

        class FakeClient:
            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def get(self, url: str, headers: dict[str, str] | None = None) -> FakeResponse:
                seen["url"] = url
                seen["headers"] = headers or {}
                return FakeResponse()

        monkeypatch.setattr(setup_mod.httpx, "AsyncClient", lambda **_: FakeClient())

        body = client.get("/api/setup/provider-models/lmstudio").json()

        assert body["source"] == "live"
        assert body["models"] == ["some-local-model"]
        assert body["detail"] == ""
        # An empty bearer is worse than none: some servers reject the malformed
        # header, which reads as the server being down.
        assert "Authorization" not in seen["headers"]

    def test_a_local_server_that_is_not_running_says_so(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """These have no curated list to fall back on, by design. So the generic
        "showing a static list that may be out of date" appeared next to no list
        at all, and said nothing about the one thing that was wrong.
        """

        class FakeClient:
            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def get(self, *_: object, **__: object):
                raise setup_mod.httpx.ConnectError("nothing listening")

        monkeypatch.setattr(setup_mod.httpx, "AsyncClient", lambda **_: FakeClient())

        body = client.get("/api/setup/provider-models/lmstudio").json()

        # The whole sentence, not a substring of it. Two reasons: a `in` check
        # against a URL has the shape of an incomplete-sanitization bug even
        # when it is only an assertion, and the point here is that the message
        # is actionable — which is a property of the sentence, not of a
        # fragment appearing somewhere inside it.
        assert body["models"] == []
        assert body["detail"] == (
            f"Nothing answering at {settings.lmstudio_api_base_url} — "
            "start LM Studio, then reload this list."
        )

    def test_the_local_endpoints_stay_on_the_machine(self) -> None:
        """These must never point somewhere that could receive a prompt.

        Parsed rather than prefix-matched. `startswith("http://127.0.0.1:")`
        accepts `http://127.0.0.1:1234@elsewhere.example/v1`, which resolves to
        elsewhere.example — so the check that was supposed to prove "local"
        would have passed for a URL that is the opposite. CodeQL flagged it, and
        it was right to.
        """
        for provider in ("lmstudio", "llamacpp", "vllm"):
            parsed = urlparse(getattr(settings, f"{provider}_api_base_url"))
            assert parsed.scheme == "http"
            assert parsed.hostname in ("localhost", "127.0.0.1")


class TestPullingAModel:
    def test_an_empty_name_is_rejected_before_anything_is_started(self, client: TestClient) -> None:
        assert client.post("/api/setup/ollama/pull", json={"model": "  "}).status_code == 400

    def test_progress_is_streamed_rather_than_buffered(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """These downloads are gigabytes. A response that arrives only when the
        pull finishes is indistinguishable from one that has hung."""

        class FakeStream:
            status_code = 200

            async def aiter_lines(self):
                yield '{"status": "pulling manifest"}'
                yield '{"status": "downloading", "completed": 50, "total": 100}'
                yield '{"status": "success"}'

            async def __aenter__(self) -> FakeStream:
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

        class FakeClient:
            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            def stream(self, *_: object, **__: object) -> FakeStream:
                return FakeStream()

        monkeypatch.setattr(setup_mod.httpx, "AsyncClient", lambda **_: FakeClient())

        r = client.post("/api/setup/ollama/pull", json={"model": "qwen3:8b"})

        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        assert "pulling manifest" in r.text
        assert '"completed": 50' in r.text
        assert "success" in r.text

    def test_ollama_being_absent_says_what_to_do_about_it(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """This is the likeliest failure by far, and it used to surface as
        "ConnectError: All connection attempts failed" — true, and of no use to
        someone who does not know Ollama is a separate program. Seen exactly
        that way on a machine without it installed.

        Reported into the stream rather than raised, because the response has
        already started and raising would truncate it into a download that
        simply stopped.
        """

        class FakeClient:
            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            def stream(self, *_: object, **__: object):
                raise setup_mod.httpx.ConnectError("All connection attempts failed")

        monkeypatch.setattr(setup_mod.httpx, "AsyncClient", lambda **_: FakeClient())

        r = client.post("/api/setup/ollama/pull", json={"model": "qwen3:8b"})

        assert r.status_code == 200
        # The whole message. `"ollama.com" in r.text` reads as a domain check on
        # a URL, which is the shape of a real bug elsewhere in this file — and
        # the property under test is that the sentence is actionable, which the
        # sentence has to carry, not a fragment of it.
        assert json.loads(r.text.split("data: ", 1)[1]) == {
            "error": f"Nothing answering at {settings.ollama_host}. "
            "Ollama is a separate program — install it from https://ollama.com "
            "and start it, then try again."
        }
        assert "ConnectError" not in r.text

    def test_other_failures_still_reach_the_caller(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the connect case gets a hand-written message. Everything else
        keeps its own text, rather than being flattened into a friendly
        sentence that hides what went wrong."""

        class FakeClient:
            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            def stream(self, *_: object, **__: object):
                raise setup_mod.httpx.ReadTimeout("the disk gave up")

        monkeypatch.setattr(setup_mod.httpx, "AsyncClient", lambda **_: FakeClient())

        r = client.post("/api/setup/ollama/pull", json={"model": "qwen3:8b"})

        assert "the disk gave up" in r.text

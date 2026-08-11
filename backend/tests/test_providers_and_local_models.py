"""Reaching new providers, and getting a local model running.

Two failure modes this guards against, both of which had already happened:
a curated model list that ages into wrongness, and a local server gated behind
an API key it does not have.
"""

from __future__ import annotations

from typing import Any

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
            assert getattr(settings, f"{provider}_api_base_url").startswith("https://")

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
        # An empty bearer is worse than none: some servers reject the malformed
        # header, which reads as the server being down.
        assert "Authorization" not in seen["headers"]

    def test_the_local_endpoints_stay_on_the_machine(self) -> None:
        """These must never point somewhere that could receive a prompt."""
        for provider in ("lmstudio", "llamacpp", "vllm"):
            base = getattr(settings, f"{provider}_api_base_url")
            assert base.startswith(("http://localhost:", "http://127.0.0.1:"))


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

    def test_a_failure_is_reported_into_the_stream(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The response has already started by then, so raising would truncate
        it and the browser would see a download that simply stopped."""

        class FakeClient:
            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            def stream(self, *_: object, **__: object):
                raise setup_mod.httpx.ConnectError("ollama is not running")

        monkeypatch.setattr(setup_mod.httpx, "AsyncClient", lambda **_: FakeClient())

        r = client.post("/api/setup/ollama/pull", json={"model": "qwen3:8b"})

        assert r.status_code == 200
        assert "ollama is not running" in r.text

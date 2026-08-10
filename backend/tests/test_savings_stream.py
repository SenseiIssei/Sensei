"""The live savings stream, and who gets credited for a request.

The dashboard polled every fifteen seconds, so a page whose entire job is to
show what is happening could be a quarter of a minute out of date. These cover
the two ways the replacement can go wrong: never firing, and firing constantly.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sensei.main import app
from sensei.routers import stats as stats_router
from sensei.routers.stats import change_signature


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _first_event(raw: str) -> dict:
    """Pull the first `data:` payload out of an SSE body."""
    for line in raw.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"no SSE data frame in: {raw[:200]!r}")


class TestStream:
    """Driven with a one-tick cap rather than a live connection.

    A TestClient never reports a disconnect, so an uncapped stream loops
    forever and the test hangs on closing the response — which is how the cap
    came to exist in the first place.
    """

    @pytest.fixture(autouse=True)
    def one_tick(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(stats_router, "MAX_STREAM_TICKS", 1)

    def test_sends_the_current_totals_immediately(self, client: TestClient) -> None:
        """EventSource delivers nothing until the server speaks, so a stream
        that only sends on change leaves the page blank on open."""
        response = client.get("/api/stats/savings/stream")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        payload = _first_event(response.text)
        assert "lifetime" in payload
        assert "session" in payload

    def test_is_not_buffered_by_a_reverse_proxy(self, client: TestClient) -> None:
        """nginx buffers by default and would hold every event until the
        response ends, which for a stream is never."""
        response = client.get("/api/stats/savings/stream")
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["cache-control"] == "no-cache"

    def test_the_stream_ends_rather_than_running_forever(self, client: TestClient) -> None:
        """`is_disconnected()` is not guaranteed to fire on every transport,
        and a generator looping with nobody listening is a leak that shows up
        as slow memory growth days later."""
        response = client.get("/api/stats/savings/stream")
        assert response.text.count("event: savings") == 1


class TestChangeDetection:
    """`change_signature` decides what counts as a change worth pushing."""

    def test_an_idle_server_produces_no_change(self) -> None:
        """`since` is `time.time()` on an empty ledger — there is no first row
        to take a timestamp from. Comparing the raw payload therefore differs
        every second, and the stream fired continuously at a server doing
        nothing at all.
        """
        payload = {
            "lifetime": {"requests": 0, "tokens_saved": 0, "since": 1000.0},
            "session": {"requests": 0, "since": 1000.0},
            "daily": [],
        }
        later = {
            "lifetime": {"requests": 0, "tokens_saved": 0, "since": 2000.0},
            "session": {"requests": 0, "since": 2000.0},
            "daily": [],
        }
        assert change_signature(payload) == change_signature(later)

    def test_a_real_change_is_detected(self) -> None:
        before = {"lifetime": {"requests": 0, "since": 1.0}, "session": {}, "daily": []}
        after = {"lifetime": {"requests": 1, "since": 1.0}, "session": {}, "daily": []}
        assert change_signature(before) != change_signature(after)

    def test_since_still_reaches_the_client(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Excluded from the comparison, not from the payload."""
        monkeypatch.setattr(stats_router, "MAX_STREAM_TICKS", 1)
        payload = _first_event(client.get("/api/stats/savings/stream").text)
        assert "since" in payload["lifetime"]


class TestAttribution:
    """Who a request gets credited to on the dashboard.

    An unmatched client used to be recorded as "" and drawn as "unknown", which
    is a dead end: you cannot tell whether it was a tool worth adding to the
    table or a stray curl.
    """

    @staticmethod
    def _name(user_agent: str, explicit: str = "") -> str:
        from starlette.datastructures import Headers

        from sensei.routers.gateway import _client_name

        headers = {"user-agent": user_agent}
        if explicit:
            headers["x-sensei-client"] = explicit

        class _Req:
            def __init__(self) -> None:
                self.headers = Headers(headers)

        return _client_name(_Req())

    @pytest.mark.parametrize(
        ("agent", "expected"),
        [
            ("claude-cli/2.0.1 (external, cli)", "Claude Code"),
            ("Cursor/0.44.11 (darwin arm64)", "Cursor"),
            ("codex_cli_rs/0.5.0", "Codex"),
            ("aider/0.71.1", "Aider"),
        ],
    )
    def test_known_tools_are_named(self, agent: str, expected: str) -> None:
        assert self._name(agent) == expected

    def test_an_unknown_agent_reports_its_own_name(self) -> None:
        """A name tells you which tool to add to the table above. "unknown"
        does not."""
        assert self._name("acme-agent/0.9.2") == "acme-agent"

    def test_a_known_substring_still_wins_over_the_fallback(self) -> None:
        """`python-httpx/0.28` contains `httpx`, which is in the table — so it
        is labelled from the table rather than by its full product token. The
        table is the more specific answer and should keep priority."""
        assert self._name("python-httpx/0.28.1") == "httpx"

    def test_only_the_product_token_is_kept(self) -> None:
        """A UA carrying an OS build and a locale would otherwise become a
        chart label nobody can read, and two versions of one tool would not
        group together."""
        assert self._name("Mozilla/5.0 (Windows NT 10.0; Win64) PowerShell/7.4") == "Mozilla"

    def test_an_explicit_header_wins(self) -> None:
        assert self._name("claude-cli/2.0.1", explicit="My Harness") == "My Harness"

    def test_no_user_agent_at_all_is_still_blank(self) -> None:
        assert self._name("") == ""

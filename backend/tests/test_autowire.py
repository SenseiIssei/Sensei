"""The background scan that connects tools installed after Sensei was set up."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sensei import autowire, integrations


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake ~/.sensei, so the manifest under test is not the real one."""
    monkeypatch.setattr(integrations, "SENSEI_HOME", tmp_path)
    monkeypatch.setattr(integrations, "MANIFEST_PATH", tmp_path / "manifest.json")
    return tmp_path


def _fake_status(installed: set[str], wired: set[str]):
    """Stand in for integrations.status() without touching the machine."""

    class Stub:
        def __init__(self, tool_id: str) -> None:
            self.id = tool_id
            self.name = tool_id.title()

    def status() -> list[tuple[object, bool, bool]]:
        every = sorted(installed | wired | {"cursor", "zed", "aider"})
        return [(Stub(i), i in installed, i in wired) for i in every]

    return status


class TestNoticingNewTools:
    @pytest.mark.anyio
    async def test_connects_a_tool_that_appears_after_startup(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case this exists for: the installer ran, and Cursor was installed
        the following week."""
        calls: list[set[str]] = []
        monkeypatch.setattr(integrations, "status", _fake_status(installed=set(), wired=set()))
        monkeypatch.setattr(
            integrations,
            "apply_all",
            lambda **kw: calls.append(kw["only"]) or [],
        )

        watcher = autowire.Watcher(interval=0.01)
        await watcher.scan(first=True)
        assert calls == [], "nothing was installed, so nothing to do"

        monkeypatch.setattr(integrations, "status", _fake_status(installed={"cursor"}, wired=set()))
        await watcher.scan()
        assert calls == [{"cursor"}]

    @pytest.mark.anyio
    async def test_does_not_rewrite_a_tool_it_already_connected(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sixty writes an hour to a file that already says the right thing is
        not idempotence, it is mtime churn — and it would make every one of the
        user's config files look permanently modified."""
        calls: list[set[str]] = []
        monkeypatch.setattr(
            integrations, "status", _fake_status(installed={"cursor"}, wired={"cursor"})
        )
        monkeypatch.setattr(integrations, "apply_all", lambda **kw: calls.append(kw["only"]) or [])

        watcher = autowire.Watcher(interval=0.01)
        await watcher.scan(first=True)
        await watcher.scan()
        await watcher.scan()
        assert calls == []

    @pytest.mark.anyio
    async def test_a_failing_scan_does_not_end_the_loop(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The watcher is a convenience; the gateway is the product. An
        unreadable config file must not be able to take the server with it."""

        def boom() -> list[tuple[object, bool, bool]]:
            raise OSError("config file is on a disconnected network drive")

        monkeypatch.setattr(integrations, "status", boom)
        watcher = autowire.Watcher(interval=0.01)

        with pytest.raises(OSError):
            await watcher.scan(first=True)

        # …but run() swallows it and keeps its record of what went wrong.
        import asyncio

        task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.05)
        task.cancel()
        assert watcher.last_error is not None
        assert "network drive" in watcher.last_error


class TestDisconnectingMeansSomething:
    def test_undo_records_the_refusal(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Otherwise the watcher cannot tell "never wired" from "unwired on
        purpose", and reconnects it on the next tick."""
        target = home / "cursor.json"
        target.write_text("{}", encoding="utf-8")
        integrations._write_manifest(
            {
                "version": 1,
                "entries": [
                    {
                        "tool_id": "cursor",
                        "kind": "json",
                        "path": str(target),
                        "backup": None,
                        "hash_after": integrations._sha256(target),
                    }
                ],
            }
        )

        integrations.undo_all(only={"cursor"})
        assert "cursor" in integrations.declined()

    def test_the_watcher_leaves_a_declined_tool_alone(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        integrations._write_manifest({"version": 1, "entries": [], "declined": ["cursor"]})
        outcomes = integrations.apply_all(only={"cursor"}, automatic=True)
        assert [o.status for o in outcomes] == ["unchanged"]
        assert "by hand" in outcomes[0].detail

    def test_asking_for_it_by_hand_overrides_the_refusal(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Someone typing `sensei setup-tools` is stating what they want now.
        A decision from last week does not get to veto that."""
        integrations._write_manifest({"version": 1, "entries": [], "declined": ["cursor"]})

        outcomes = integrations.apply_all(only={"cursor"}, include_undetected=True)
        assert all(o.status != "unchanged" or "by hand" not in o.detail for o in outcomes)
        assert "cursor" not in integrations.declined()

    def test_a_manifest_without_the_key_is_not_an_error(self, home: Path) -> None:
        """Manifests written by older versions have no `declined` list at all."""
        integrations.MANIFEST_PATH.write_text(
            json.dumps({"version": 1, "entries": []}), encoding="utf-8"
        )
        assert integrations.declined() == set()

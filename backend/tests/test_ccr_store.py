"""The store of originals: shared between processes, bounded, and never wrong."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from sensei.compression import ccr as ccr_mod
from sensei.compression.ccr import CCRStore
from sensei.compression.router import ContentRouter
from sensei.config import settings


def test_an_entry_written_elsewhere_is_there_at_once(tmp_path: Path) -> None:
    """The hook mints the id in one process, the editor's MCP server is asked for it."""
    reader = CCRStore(tmp_path)
    CCRStore(tmp_path).store("original", "short", ccr_id="abc123")
    assert reader.retrieve("abc123") == "original"
    assert reader.retrieve_compressed("abc123") == "short"


def test_opening_reads_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    CCRStore(tmp_path).store("original", "short", ccr_id="abc123")

    def refuse(*_: object, **__: object) -> str:
        raise AssertionError("read while opening")

    monkeypatch.setattr(Path, "read_text", refuse)
    CCRStore(tmp_path)


def test_memory_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ccr_mod, "_HOT_BYTES", 10_000)
    store = CCRStore(tmp_path)
    ids = [store.store("x" * 1000, "y", ccr_id=f"id{i}") for i in range(100)]
    assert store._hot_bytes <= 10_000
    assert len(store._hot) < 11
    assert all(store.retrieve(i) == "x" * 1000 for i in ids), "the rest is on disk"


def test_the_directory_is_bounded_oldest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ccr_max_mb", 1)
    store = CCRStore(tmp_path)
    for i in range(6):
        store.store("x" * 300_000, "y", ccr_id=f"id{i}")
        stamp = time.time() - 100 + i
        os.utime(tmp_path / f"id{i}.json", (stamp, stamp))
    assert store.cleanup() == 3
    assert store.retrieve("id0") is None
    assert store.retrieve("id5") == "x" * 300_000


def test_expired_entries_go_without_a_server(tmp_path: Path) -> None:
    """`sensei mcp` on its own has no purge loop; the first write sweeps."""
    (tmp_path / "old.json").write_text("{}", encoding="utf-8")
    os.utime(tmp_path / "old.json", (1, 1))
    CCRStore(tmp_path).store("new", "n", ccr_id="new1")
    assert not (tmp_path / "old.json").exists()


@pytest.mark.parametrize("bad", ["../secret", "a/b", "", "a\\b", "x" * 200, None, 5])
def test_ids_from_a_model_never_leave_the_directory(tmp_path: Path, bad: object) -> None:
    (tmp_path / "secret.json").write_text(
        '{"original":"s","compressed":"s","stored_at":9e12}', encoding="utf-8"
    )
    cache = tmp_path / "cache"
    assert CCRStore(cache).retrieve(bad) is None  # type: ignore[arg-type]


def test_a_damaged_file_is_a_miss_not_a_crash(tmp_path: Path) -> None:
    (tmp_path / "half.json").write_text('{"original": "cut of', encoding="utf-8")
    (tmp_path / "list.json").write_text("[]", encoding="utf-8")
    store = CCRStore(tmp_path)
    assert store.retrieve("half") is None
    assert store.retrieve("list") is None


def test_half_an_emoji_round_trips(tmp_path: Path) -> None:
    text = "\ud83d cut\n" + "2026-11-25 12:00:00 INFO ok\n" * 200
    result = ContentRouter(ccr_store=CCRStore(tmp_path), enable_caching=True).compress(text)
    assert result.ccr_id is not None
    assert CCRStore(tmp_path).retrieve(result.ccr_id) == text


def test_stats_count_every_process_without_reading_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = CCRStore(tmp_path)
    store.store("0123456789", "01", ccr_id="a1")
    CCRStore(tmp_path).store("0123456789", "0", ccr_id="b1")
    monkeypatch.setattr(store, "_read", lambda _: pytest.fail("read a file"))
    stats = store.stats()
    assert (stats["total_entries"], stats["space_saved_bytes"]) == (2, 8)
    assert stats["disk_bytes"] > 20


def test_no_half_written_files_are_left(tmp_path: Path) -> None:
    store = CCRStore(tmp_path)
    for i in range(20):
        store.store("x" * 1000, "y", ccr_id=f"id{i % 4}")
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"id{i}.json" for i in range(4)]

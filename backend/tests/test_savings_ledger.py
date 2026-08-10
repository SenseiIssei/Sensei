"""Tests for the persistent savings ledger.

The ledger is on the gateway's hot path, so two properties matter more than the
arithmetic: it must never raise into the proxy, and it must never contain
anything that was in a prompt.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from sensei import savings as savings_mod
from sensei.savings import SavingsLedger, SavingsTracker


@pytest.fixture
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SavingsLedger:
    monkeypatch.setattr(savings_mod.settings, "savings_db", str(tmp_path / "savings.db"))
    monkeypatch.setattr(savings_mod.settings, "savings_persist", True)
    monkeypatch.setattr(savings_mod.settings, "usd_per_million_tokens", 3.0)
    return SavingsLedger()


def _event(before: int, after: int) -> dict[str, int]:
    return {
        "prompt_tokens_before": before,
        "prompt_tokens_after": after,
        "tokens_saved": before - after,
        "blocks_compressed": 1,
    }


def test_totals_add_up(ledger: SavingsLedger) -> None:
    ledger.append(_event(1000, 200), tool="Claude Code", provider="anthropic", model="opus")
    ledger.append(_event(500, 100), tool="Cursor", provider="openai", model="gpt-4o")

    totals = ledger.totals()
    assert totals["requests"] == 2
    assert totals["tokens_before"] == 1500
    assert totals["tokens_saved"] == 1200
    assert totals["percent_saved"] == 80.0
    # 1_200 tokens at $3 per million.
    assert totals["estimated_cost_saved_usd"] == pytest.approx(0.0036)


def test_history_survives_a_new_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point: closing the laptop must not zero the dashboard."""
    monkeypatch.setattr(savings_mod.settings, "savings_db", str(tmp_path / "savings.db"))
    monkeypatch.setattr(savings_mod.settings, "savings_persist", True)

    first = SavingsLedger()
    first.append(_event(900, 100))
    first.close()

    second = SavingsLedger()
    assert second.totals()["tokens_saved"] == 800


def test_persistence_can_be_turned_off(ledger: SavingsLedger, monkeypatch) -> None:
    monkeypatch.setattr(savings_mod.settings, "savings_persist", False)
    ledger.append(_event(1000, 100))
    assert ledger.totals()["requests"] == 0


def test_nothing_but_counters_is_stored(ledger: SavingsLedger) -> None:
    """A prompt must not be able to reach the database, whatever the caller does."""
    ledger.append(_event(100, 10), tool="Cursor", provider="openai", model="gpt-4o")
    conn = sqlite3.connect(ledger.path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    conn.close()
    # Every column is a counter, a timestamp, or a short identifier the user
    # chose to run. Adding one that could hold prompt or response text should
    # fail here and be argued for in a pull request, not slip in.
    assert columns == {
        "ts",
        "tool",
        "provider",
        "model",
        "before",
        "after",
        "saved",
        "blocks",
        "output_tokens",
        "shaped",
    }


def test_daily_fills_the_gaps(ledger: SavingsLedger) -> None:
    """A chart that skips idle days makes a quiet week look busy."""
    ledger.append(_event(1000, 100))
    daily = ledger.daily(days=7)
    assert len(daily) == 7
    assert [d["date"] for d in daily] == sorted(d["date"] for d in daily)
    assert sum(d["tokens_saved"] for d in daily) == 900
    assert sum(1 for d in daily if d["requests"] == 0) == 6


def test_breakdown_is_ordered_by_savings(ledger: SavingsLedger) -> None:
    ledger.append(_event(100, 90), tool="Cursor")
    ledger.append(_event(1000, 100), tool="Claude Code")

    rows = ledger.breakdown("tool")
    assert [r["key"] for r in rows] == ["Claude Code", "Cursor"]
    assert rows[0]["percent_saved"] == 90.0


def test_missing_tool_is_labelled_rather_than_blank(ledger: SavingsLedger) -> None:
    ledger.append(_event(100, 50))
    assert ledger.breakdown("tool")[0]["key"] == "unknown"


def test_breakdown_rejects_an_arbitrary_column(ledger: SavingsLedger) -> None:
    """The dimension is interpolated into SQL, so it has to be a closed set."""
    with pytest.raises(ValueError, match="not a groupable dimension"):
        ledger.breakdown("ts) --")


def test_prune_drops_old_rows_only(ledger: SavingsLedger, monkeypatch) -> None:
    monkeypatch.setattr(savings_mod.settings, "savings_retention_days", 30)
    ledger.append(_event(100, 10))
    conn = sqlite3.connect(ledger.path)
    conn.execute(
        "INSERT INTO events (ts, before, after, saved) VALUES (?, 500, 50, 450)",
        (time.time() - 400 * savings_mod.DAY,),
    )
    conn.commit()
    conn.close()

    assert ledger.totals()["requests"] == 2
    assert ledger.prune() == 1
    assert ledger.totals()["requests"] == 1


def test_a_broken_database_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A full disk must not turn into a 500 from the gateway."""
    broken = tmp_path / "not-a-database.db"
    broken.write_bytes(b"this is not sqlite, and never was")
    monkeypatch.setattr(savings_mod.settings, "savings_db", str(broken))
    monkeypatch.setattr(savings_mod.settings, "savings_persist", True)

    ledger = SavingsLedger()
    ledger.append(_event(100, 10))  # must not raise
    assert ledger.totals() == savings_mod._empty_totals() or ledger.totals()["requests"] == 0
    assert ledger.daily(days=3) == [] or all(d["requests"] == 0 for d in ledger.daily(days=3))


def test_tracker_separates_session_from_lifetime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(savings_mod.settings, "savings_db", str(tmp_path / "savings.db"))
    monkeypatch.setattr(savings_mod.settings, "savings_persist", True)

    old = SavingsTracker()
    old.record(_event(1000, 100))
    old.ledger.close()

    fresh = SavingsTracker()
    fresh.record(_event(200, 100))

    assert fresh.snapshot()["tokens_saved"] == 100
    assert fresh.lifetime()["tokens_saved"] == 1000
    assert fresh.lifetime()["requests"] == 2


def test_reset_keeps_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`reset` is for the session counters. Throwing away history needs `clear`."""
    monkeypatch.setattr(savings_mod.settings, "savings_db", str(tmp_path / "savings.db"))
    monkeypatch.setattr(savings_mod.settings, "savings_persist", True)

    tracker = SavingsTracker()
    tracker.record(_event(1000, 100))
    tracker.reset()

    assert tracker.snapshot()["tokens_saved"] == 0
    assert tracker.lifetime()["tokens_saved"] == 900

    tracker.ledger.clear()
    assert tracker.lifetime()["tokens_saved"] == 0

"""One ledger per machine, and everything that saves tokens writes to it.

Sensei is several processes: a tray server started from its install directory,
and a `sensei mcp` that an editor spawns in whatever project is open. While the
data paths were relative, each of those had its own ledger, and the dashboard
could only ever see one of them.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from sensei import config as config_mod


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config_mod, "SENSEI_HOME", tmp_path / ".sensei")
    return tmp_path


class TestOneLocationForTheWholeMachine:
    def test_the_default_ledger_does_not_depend_on_the_working_directory(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bug in one line: the tray server and an editor-spawned MCP server
        start in different directories, so they kept different books."""
        s = config_mod.Settings()

        first = tmp_path / "project-a"
        first.mkdir()
        monkeypatch.chdir(first)
        a = s.savings_db_path

        second = tmp_path / "project-b"
        second.mkdir()
        monkeypatch.chdir(second)
        b = s.savings_db_path

        assert a == b
        assert config_mod.SENSEI_HOME in a.parents

    def test_the_ccr_store_moves_with_it(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Otherwise a ccr_id handed out by one process cannot be retrieved by
        another, and `sensei_retrieve` is the thing that makes compression safe
        to accept in the first place."""
        assert config_mod.SENSEI_HOME in config_mod.Settings().ccr_cache_path.parents

    def test_an_explicit_path_is_honoured_verbatim(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Someone who configures a path means that path. Quietly relocating it
        would be the same class of surprise this change is fixing."""
        chosen = tmp_path / "somewhere" / "mine.db"
        monkeypatch.setenv("SENSEI_SAVINGS_DB", str(chosen))
        try:
            assert config_mod.Settings().savings_db_path == chosen
        finally:
            os.environ.pop("SENSEI_SAVINGS_DB", None)


class TestNotLosingWhatWasAlreadyCounted:
    def test_an_existing_ledger_is_carried_over(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An upgrade that resets the dashboard to zero has destroyed the one
        number the user installed this to watch."""
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.chdir(project)
        legacy = project / ".sensei_savings.db"
        con = sqlite3.connect(legacy)
        con.execute("create table events (ts real, saved int)")
        con.execute("insert into events values (1.0, 4711)")
        con.commit()
        con.close()

        target = config_mod.Settings().savings_db_path

        assert target.exists()
        con = sqlite3.connect(target)
        assert con.execute("select saved from events").fetchone()[0] == 4711
        con.close()

    def test_it_never_overwrites_a_ledger_that_already_has_data(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Copying over a populated destination would lose more than it saves."""
        config_mod.SENSEI_HOME.mkdir(parents=True, exist_ok=True)
        target = config_mod.SENSEI_HOME / "savings.db"
        target.write_bytes(b"the real one")

        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.chdir(project)
        (project / ".sensei_savings.db").write_bytes(b"the stale one")

        assert config_mod.Settings().savings_db_path.read_bytes() == b"the real one"

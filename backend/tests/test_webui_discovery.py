"""The web UI has to be findable in every way Sensei can be installed.

This is the bug a user hit within hours of the install instructions being
rewritten to recommend `pipx install sensei-gateway`: the wheel is built from
`backend/` and the UI lives in `frontend/`, so a pip install shipped no UI at
all. `sensei up` fell through to the Swagger page and printed

    The web UI isn't built — cd frontend && npm ci && npm run build

at somebody who had installed from PyPI and had no `frontend` directory to cd
into. The wheel now carries the built UI as package data at `sensei/webui`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sensei.cli import serve


@pytest.fixture
def no_real_ui(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the module somewhere empty so a developer's own build of the
    frontend cannot make these tests pass by accident."""
    fake = tmp_path / "pkg" / "sensei" / "cli" / "serve.py"
    fake.parent.mkdir(parents=True)
    fake.touch()
    monkeypatch.setattr(serve, "__file__", str(fake))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    return fake


def _with_index(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return directory


def test_finds_package_data_in_an_installed_wheel(no_real_ui: Path) -> None:
    """sensei/webui, next to the package — the pip and pipx case."""
    webui = _with_index(no_real_ui.parents[1] / "webui")
    assert serve._frontend_dist() == webui


def test_finds_the_source_checkout_build(no_real_ui: Path) -> None:
    """frontend/dist at the repo root — the contributor case."""
    dist = _with_index(no_real_ui.parents[3] / "frontend" / "dist")
    assert serve._frontend_dist() == dist


def test_a_frozen_bundle_wins(no_real_ui: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A PyInstaller build carries its own copy and should prefer it over
    whatever happens to be lying around the filesystem."""
    _with_index(no_real_ui.parents[1] / "webui")
    meipass = no_real_ui.parents[4] / "bundle"
    bundled = _with_index(meipass / "frontend" / "dist")
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    assert serve._frontend_dist() == bundled


def test_no_build_anywhere_is_reported_as_absent(no_real_ui: Path) -> None:
    assert serve._frontend_dist() is None


def test_doctor_agrees_with_what_actually_gets_served(no_real_ui: Path) -> None:
    """`doctor` used to look only for `frontend/dist` at the repo root.

    So the downloadable binary — which carries the UI inside the bundle and was
    serving it on the next port over — reported "the web UI isn't built, run
    npm ci" at someone with no frontend directory. Delegating to the same
    finder makes the two impossible to disagree.
    """
    from sensei.cli import doctor

    assert doctor._web_ui_built() is False
    _with_index(no_real_ui.parents[1] / "webui")
    assert doctor._web_ui_built() is True


def test_an_empty_directory_does_not_count(no_real_ui: Path) -> None:
    """`rm -rf dist/*` leaves the directory behind. Serving it would mount an
    empty StaticFiles and hand the user a blank page instead of the Swagger
    fallback, which is strictly worse than admitting there is no UI."""
    (no_real_ui.parents[1] / "webui").mkdir(parents=True)
    assert serve._frontend_dist() is None

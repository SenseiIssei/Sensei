"""Tests for the tray icon and the Windows installer script.

Neither can be fully exercised without a desktop session and Inno Setup, so
these cover the parts that are checkable and the mistakes that would ship
silently: an icon that renders as a blank square, and an installer that leaves
other programs pointing at a gateway it just deleted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="the tray extra is optional")

from sensei.cli import tray

ISS = Path(__file__).resolve().parents[2] / "packaging" / "sensei.iss"


class TestIcon:
    def test_renders_at_every_size_windows_asks_for(self) -> None:
        """16px in the tray, 256 for the file thumbnail. Drawing the bolt in
        fractions rather than pixels is what makes the small ones legible."""
        for size in (16, 32, 64, 256):
            image = tray._icon_image(size)
            assert image.size == (size, size)
            assert image.mode == "RGBA"

    def test_is_not_a_blank_square(self) -> None:
        """The failure this catches is an icon that builds, packages and ships
        as an empty box — visible only to whoever installs it."""
        image = tray._icon_image(64)
        colours = {image.getpixel((x, y)) for x in range(0, 64, 2) for y in range(0, 64, 2)}
        colours = {c for c in colours if c[3] > 0}
        assert tray._GREEN in colours, "the bolt is missing"
        assert tray._DARK in colours, "the tile is missing"

    def test_the_corners_are_transparent(self) -> None:
        """A rounded tile drawn on an opaque background looks like a sticker on
        a dark taskbar and like a black box on a light one."""
        image = tray._icon_image(64)
        assert image.getpixel((0, 0))[3] == 0


class TestUrl:
    def test_bind_address_maps_to_something_a_browser_can_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tray.settings, "host", "0.0.0.0")
        monkeypatch.setattr(tray.settings, "port", 7000)
        assert tray._url() == "http://localhost:7000/app/"

    def test_uses_the_configured_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tray.settings, "host", "127.0.0.1")
        monkeypatch.setattr(tray.settings, "port", 7123)
        assert tray._url("") == "http://127.0.0.1:7123"


class TestInstallerScript:
    """Read rather than run: Inno Setup is Windows-only and not a test
    dependency. What is checked here are the decisions, not the syntax."""

    @pytest.fixture
    def script(self) -> str:
        return ISS.read_text(encoding="utf-8")

    def test_asks_for_no_administrator_rights(self, script: str) -> None:
        """Sensei listens on loopback and edits files in the user's own home.
        Requesting elevation would be asking for a privilege in order not to
        use it."""
        assert "PrivilegesRequired=lowest" in script

    def test_unwires_the_other_tools_on_uninstall(self, script: str) -> None:
        """Sensei writes its address into Claude Code, Cursor and the rest.
        Removing the binary without putting those back leaves every one of them
        failing with a connection error that never mentions Sensei."""
        assert "setup-tools --undo" in script
        assert "[UninstallRun]" in script

    def test_the_undo_waits_for_the_files_to_still_be_there(self, script: str) -> None:
        """`waituntilterminated`, because after the binary is gone there is
        nothing left to run it with.

        Scoped to the [UninstallRun] section: the header comment mentions the
        same command, and matching that instead would make this test pass on a
        script that never runs it.
        """
        section = script.split("[UninstallRun]", 1)[1].split("\n[", 1)[0]
        assert "setup-tools --undo" in section
        assert "waituntilterminated" in section

    def test_the_shortcut_starts_the_tray_not_a_console(self, script: str) -> None:
        """Clicking "Sensei" in the Start menu should not open a terminal
        window that has to stay open.

        `Parameters: "tray"` used to be what carried this, and it was not
        enough: a console-subsystem binary allocates a window whichever verb it
        is given, so the shortcut opened a black rectangle and then sat in the
        tray behind it. What actually settles it is which binary the shortcut
        names, so that is what this asserts.
        """
        icons = script.split("[Icons]", 1)[1].split("[Run]", 1)[0]
        shortcuts = [
            line for line in icons.splitlines() if "Filename:" in line and "{app}\\" in line
        ]
        assert shortcuts, "no shortcuts point into the install directory at all"
        for line in shortcuts:
            assert "senseiw.exe" in line, f"shortcut opens a console: {line.strip()}"

    def test_wiring_the_tools_is_a_choice(self, script: str) -> None:
        """Editing other programs' configuration is not something an installer
        should do without being asked."""
        assert "Tasks: wiretools" in script
        assert 'Name: "wiretools"' in script

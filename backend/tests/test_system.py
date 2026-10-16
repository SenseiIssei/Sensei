"""`sensei autostart` and `sensei update`, without touching the real machine.

Each platform's autostart file is written into a temporary home directory, and
the platform itself is faked where the test is about another OS. The Windows
registry path is exercised for real only on Windows CI, against a value name
nobody else uses, and removed again.
"""

from __future__ import annotations

import hashlib
import io
import json
import platform
import plistlib
import sys
import tarfile
from pathlib import Path

import pytest

from sensei.cli import system


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(system, "_run", lambda argv: None)
    return tmp_path


class TestVersions:
    @pytest.mark.parametrize(
        ("candidate", "current", "newer"),
        [
            ("0.2.0", "0.1.19", True),
            ("v0.1.20", "0.1.19", True),
            ("0.1.19", "0.1.19", False),
            ("0.1.9", "0.1.19", False),
            ("1.0.0-rc1", "0.9.9", True),
        ],
    )
    def test_is_newer(self, candidate, current, newer):
        assert system.is_newer(candidate, current) is newer


class TestLaunchCommand:
    def test_source_install_runs_the_module(self):
        argv = system.launch_command(headless=True)
        assert argv[1:] == ["-m", "sensei.cli", "up", "--no-browser"]

    def test_frozen_install_prefers_the_windowed_binary(self, tmp_path, monkeypatch):
        exe = tmp_path / "sensei.exe"
        exe.write_bytes(b"")
        (tmp_path / "senseiw.exe").write_bytes(b"")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        assert system.launch_command()[0].endswith("senseiw.exe")
        assert system.launch_command()[1:] == ["tray", "--no-browser"]


class TestAutostartFiles:
    def test_macos_launch_agent(self, home, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(system.os, "getuid", lambda: 501, raising=False)
        state = system.autostart_enable()
        assert state.enabled
        plist = plistlib.loads(system._mac_plist().read_bytes())
        assert plist["Label"] == "dev.sensei.gateway"
        assert plist["RunAtLoad"] is True
        assert plist["KeepAlive"] == {"SuccessfulExit": False}
        assert "--no-browser" in plist["ProgramArguments"]
        assert not system.autostart_disable().enabled
        assert not system._mac_plist().exists()

    def test_linux_systemd_user_service(self, home, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.setattr(system, "_has_systemd", lambda: True)
        state = system.autostart_enable()
        assert state.enabled and state.mechanism == "systemd user service"
        unit = system._systemd_unit().read_text(encoding="utf-8")
        assert "ExecStart=" in unit and "up --no-browser" in unit
        assert "Restart=on-failure" in unit
        assert "WantedBy=default.target" in unit
        assert not system.autostart_disable().enabled

    def test_linux_without_systemd_uses_xdg(self, home, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.setattr(system, "_has_systemd", lambda: False)
        state = system.autostart_enable()
        assert state.mechanism == "XDG autostart"
        entry = system._xdg_entry().read_text(encoding="utf-8")
        assert entry.startswith("[Desktop Entry]") and "Exec=" in entry
        assert not system.autostart_disable().enabled

    @pytest.mark.skipif(sys.platform != "win32", reason="real registry, Windows only")
    def test_windows_run_key_round_trip(self):
        try:
            assert system.autostart_enable().enabled
            assert "--no-browser" in system.autostart_status().command
        finally:
            assert not system.autostart_disable().enabled


def _release(assets: dict[str, bytes], *, sums: dict[str, str] | None = None) -> tuple[dict, dict]:
    files = dict(assets)
    lines = sums or {name: hashlib.sha256(data).hexdigest() for name, data in assets.items()}
    files["SHA256SUMS"] = "".join(f"{h}  {n}\n" for n, h in lines.items()).encode()
    release = {
        "version": "9.9.9",
        "url": "https://github.com/SenseiIssei/Sensei/releases/tag/v9.9.9",
        "assets": {name: f"https://example.invalid/{name}" for name in files},
    }
    by_url = {f"https://example.invalid/{name}": data for name, data in files.items()}
    return release, by_url


class TestUpdate:
    def test_pip_install_gets_a_command_not_a_download(self, monkeypatch):
        monkeypatch.setattr(system, "install_kind", lambda: "pip")
        release, _ = _release({})
        message = system.apply_update(release)
        assert "pipx install --force" in message
        assert "/releases/download/v9.9.9/sensei_gateway-9.9.9-py3-none-any.whl" in message

    def test_up_to_date_does_nothing(self):
        release, _ = _release({})
        release["version"] = "0.0.1"
        assert "is the latest release" in system.apply_update(release)

    def test_binary_is_replaced_after_checksum(self, tmp_path, monkeypatch):
        current = tmp_path / "sensei"
        current.write_bytes(b"old")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("sensei")
            info.size = 3
            tar.addfile(info, io.BytesIO(b"new"))
        name = f"sensei-linux-{'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64'}.tar.gz"
        release, by_url = _release({name: buf.getvalue()})
        monkeypatch.setattr(system, "_get", lambda url: by_url[url])
        monkeypatch.setattr(system, "install_kind", lambda: "binary")
        monkeypatch.setattr(system, "_asset_name", lambda version: name)
        monkeypatch.setattr(sys, "executable", str(current))
        monkeypatch.delenv("APPIMAGE", raising=False)

        assert "Updated to Sensei 9.9.9" in system.apply_update(release)
        assert current.read_bytes() == b"new"

    def test_checksum_mismatch_installs_nothing(self, tmp_path, monkeypatch):
        current = tmp_path / "sensei"
        current.write_bytes(b"old")
        release, by_url = _release({"x.tar.gz": b"payload"}, sums={"x.tar.gz": "0" * 64})
        monkeypatch.setattr(system, "_get", lambda url: by_url[url])
        monkeypatch.setattr(system, "install_kind", lambda: "binary")
        monkeypatch.setattr(system, "_asset_name", lambda version: "x.tar.gz")
        monkeypatch.setattr(sys, "executable", str(current))
        with pytest.raises(RuntimeError, match="checksum mismatch"):
            system.apply_update(release)
        assert current.read_bytes() == b"old"

    def test_unlisted_asset_is_refused(self, tmp_path, monkeypatch):
        release, by_url = _release({"x.tar.gz": b"payload"}, sums={"other": "0" * 64})
        monkeypatch.setattr(system, "_get", lambda url: by_url[url])
        with pytest.raises(RuntimeError, match="does not list"):
            system._verified_download(release, "x.tar.gz", tmp_path)


def test_update_endpoint_makes_no_request_unless_asked(monkeypatch):
    from fastapi.testclient import TestClient

    from sensei.config import settings
    from sensei.main import app

    monkeypatch.setattr(settings, "update_check", False)

    def boom():
        raise AssertionError("must not reach GitHub")

    monkeypatch.setattr(system, "check", boom)
    body = TestClient(app).get("/api/maintenance/update").json()
    assert body["enabled"] is False

    monkeypatch.setattr(
        system,
        "check",
        lambda: {
            "current": "0.1.19",
            "latest": "9.9.9",
            "update_available": True,
            "url": "u",
            "checked_at": 0.0,
        },
    )
    forced = TestClient(app).get("/api/maintenance/update?force=true").json()
    assert forced["update_available"] is True
    assert json.dumps(forced)

"""`sensei autostart` and `sensei update` — the parts of an install that outlive it.

**Autostart.** A gateway helps only while it runs, and one you have to remember
to start is one that is not running when Claude Code opens. Each platform has
exactly one native, per-user, no-administrator way to start something at login,
and this uses it:

- Windows: a value under ``HKCU\\...\\CurrentVersion\\Run``.
- macOS: a LaunchAgent in ``~/Library/LaunchAgents``.
- Linux: a systemd user service when systemd is there, otherwise an XDG
  autostart entry.

Every one is a single file or value that ``sensei autostart off`` removes again.

**Updates.** ``sensei update --check`` asks GitHub for the latest release. That is
a network request to a third party, so it happens when you run it — or, with
``SENSEI_UPDATE_CHECK=true``, at most once a day from the running server — and
never otherwise. ``sensei update`` then does what fits the way Sensei was
installed: replaces the binary in place (after verifying it against the
release's ``SHA256SUMS``), runs the Windows installer, or prints the one command
for pip, pipx or a package manager.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from sensei import __version__

REPO = "SenseiIssei/Sensei"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_LABEL = "dev.sensei.gateway"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_TIMEOUT = 15


# ── how Sensei was started ───────────────────────────────────────────────────


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def launch_command(headless: bool = False) -> list[str]:
    """The argv that starts Sensei in the background, for this install.

    The tray when it can draw one, otherwise the plain server: a LaunchAgent or
    a systemd service has no desktop session to put an icon in.
    """
    args = ["up", "--no-browser"] if headless else ["tray", "--no-browser"]
    if frozen():
        exe = Path(sys.executable)
        # The windowed twin, so no console flashes up at every login.
        windowed = exe.with_name("senseiw.exe")
        return [str(windowed if windowed.exists() else exe), *args]
    python = Path(sys.executable)
    if os.name == "nt":
        pythonw = python.with_name("pythonw.exe")
        if pythonw.exists():
            python = pythonw
    return [str(python), "-m", "sensei.cli", *args]


def _tray_available() -> bool:
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
    except Exception:
        return False
    return True


# ── autostart ────────────────────────────────────────────────────────────────


@dataclass
class AutostartState:
    enabled: bool
    mechanism: str
    location: str
    command: str = ""


def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"


def _systemd_unit() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "sensei.service"


def _xdg_entry() -> Path:
    return Path.home() / ".config" / "autostart" / "sensei.desktop"


def _has_systemd() -> bool:
    return shutil.which("systemctl") is not None and Path("/run/systemd/system").exists()


def _quote(args: list[str]) -> str:
    """A Windows command line, for the Run key."""
    return subprocess.list2cmdline(args)


def _unit_quote(args: list[str]) -> str:
    """An ExecStart= line. systemd splits on whitespace, honours double quotes
    with backslash escapes, and expands `%` specifiers — so `%` is doubled."""

    def one(arg: str) -> str:
        escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
        return f'"{escaped}"'

    return " ".join(one(a) for a in args)


_DESKTOP_RESERVED = set(" \t\n\"'\\><~|&;$*?#()`")


def _desktop_quote(args: list[str]) -> str:
    """An Exec= value per the Desktop Entry spec: arguments with reserved
    characters go in double quotes with `"`, `` ` ``, `$` and `\\` escaped; `%`
    is a field code and doubles; and the string-level escape rule then doubles
    every backslash once more."""

    def one(arg: str) -> str:
        arg = arg.replace("%", "%%")
        if arg and not (set(arg) & _DESKTOP_RESERVED):
            return arg
        inner = "".join("\\" + c if c in '"`$\\' else c for c in arg)
        return f'"{inner}"'

    return " ".join(one(a) for a in args).replace("\\", "\\\\")


def autostart_status() -> AutostartState:
    system = platform.system()
    if system == "Windows":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, "Sensei")
            return AutostartState(True, "registry", rf"HKCU\{_RUN_KEY}\Sensei", value)
        except OSError:
            pass
        # The installer's own option is a Startup-folder shortcut.
        startup = Path(os.environ.get("APPDATA", "")) / (
            r"Microsoft\Windows\Start Menu\Programs\Startup\Sensei.lnk"
        )
        if startup.exists():
            return AutostartState(True, "startup folder", str(startup))
        return AutostartState(False, "registry", rf"HKCU\{_RUN_KEY}\Sensei")
    if system == "Darwin":
        plist = _mac_plist()
        return AutostartState(plist.exists(), "LaunchAgent", str(plist))
    if _systemd_unit().exists():
        return AutostartState(True, "systemd user service", str(_systemd_unit()))
    if _xdg_entry().exists():
        return AutostartState(True, "XDG autostart", str(_xdg_entry()))
    mechanism = "systemd user service" if _has_systemd() else "XDG autostart"
    location = _systemd_unit() if _has_systemd() else _xdg_entry()
    return AutostartState(False, mechanism, str(location))


def autostart_enable() -> AutostartState:
    system = platform.system()
    if system == "Windows":
        import winreg

        command = _quote(launch_command(headless=not _tray_available()))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, "Sensei", 0, winreg.REG_SZ, command)
        return autostart_status()

    if system == "Darwin":
        plist = _mac_plist()
        plist.parent.mkdir(parents=True, exist_ok=True)
        log_dir = Path.home() / "Library" / "Logs" / "Sensei"
        log_dir.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(
            plistlib.dumps(
                {
                    "Label": _LABEL,
                    "ProgramArguments": launch_command(headless=not _tray_available()),
                    "RunAtLoad": True,
                    # Restart after a crash, not after a deliberate quit.
                    "KeepAlive": {"SuccessfulExit": False},
                    "ProcessType": "Interactive",
                    "StandardOutPath": str(log_dir / "sensei.log"),
                    "StandardErrorPath": str(log_dir / "sensei.log"),
                }
            )
        )
        _run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)])
        return autostart_status()

    if _has_systemd():
        unit = _systemd_unit()
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(
            "[Unit]\n"
            "Description=Sensei — prompt-compressing AI gateway\n"
            "After=network-online.target\n\n"
            "[Service]\n"
            f"ExecStart={_unit_quote(launch_command(headless=True))}\n"
            "Restart=on-failure\n"
            "RestartSec=3\n\n"
            "[Install]\n"
            "WantedBy=default.target\n",
            encoding="utf-8",
        )
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", "--now", "sensei.service"])
        return autostart_status()

    entry = _xdg_entry()
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Sensei\n"
        "Comment=Prompt-compressing AI gateway\n"
        f"Exec={_desktop_quote(launch_command(headless=not _tray_available()))}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )
    return autostart_status()


def autostart_disable() -> AutostartState:
    system = platform.system()
    if system == "Windows":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "Sensei")
        except OSError:
            pass
        return autostart_status()
    if system == "Darwin":
        plist = _mac_plist()
        if plist.exists():
            _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)])
            plist.unlink()
        return autostart_status()
    if _systemd_unit().exists():
        _run(["systemctl", "--user", "disable", "--now", "sensei.service"])
        _systemd_unit().unlink()
        _run(["systemctl", "--user", "daemon-reload"])
    if _xdg_entry().exists():
        _xdg_entry().unlink()
    return autostart_status()


def _run(argv: list[str]) -> None:
    """Best effort: the file is what persists; loading it now is a bonus."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(argv, check=False, capture_output=True, timeout=20)  # noqa: S603


# ── updates ──────────────────────────────────────────────────────────────────


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = []
    for piece in text.strip().lstrip("v").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def _get(url: str) -> bytes:
    request = urllib.request.Request(  # noqa: S310 — fixed https URLs only
        url, headers={"User-Agent": f"sensei/{__version__}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:  # noqa: S310
        return resp.read()


def latest_release() -> dict:
    """The latest GitHub release: tag, notes URL and asset download URLs."""
    data = json.loads(_get(_API))
    return {
        "version": str(data.get("tag_name", "")).lstrip("v"),
        "url": data.get("html_url", f"https://github.com/{REPO}/releases/latest"),
        "published_at": data.get("published_at", ""),
        "assets": {a["name"]: a["browser_download_url"] for a in data.get("assets", [])},
    }


def check() -> dict:
    """Compare this install with the latest release."""
    release = latest_release()
    return {
        "current": __version__,
        "latest": release["version"],
        "update_available": is_newer(release["version"]),
        "url": release["url"],
        "install_kind": install_kind(),
        "checked_at": time.time(),
    }


def install_kind() -> str:
    """How this copy was installed, which decides how it updates."""
    if not frozen():
        return "pip"
    exe = Path(sys.executable).resolve()
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if platform.system() == "Windows":
        if (exe.parent / "unins000.exe").exists():
            return "windows-installer"
        return "windows-portable"
    if str(exe).startswith(("/usr/bin/", "/usr/lib/", "/opt/sensei/")):
        return "system-package"
    # Installed somewhere the user cannot write to without sudo — for example
    # SENSEI_INSTALL_DIR=/usr/local/bin. Replacing it in place would fail.
    if not os.access(exe.parent, os.W_OK):
        return "binary-readonly"
    return "binary"


def _asset_name(version: str) -> str | None:
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    system = platform.system()
    kind = install_kind()
    if system == "Windows":
        return (
            f"sensei-setup-{version}.exe"
            if kind == "windows-installer"
            else "sensei-windows-x64.zip"
        )
    if system == "Darwin":
        return f"sensei-macos-{arch}.tar.gz"
    if kind == "appimage":
        return f"sensei-linux-{arch}.AppImage"
    return f"sensei-linux-{arch}.tar.gz"


def _verified_download(release: dict, name: str, dest: Path) -> Path:
    """Download one asset and check it against the release's SHA256SUMS."""
    if name not in release["assets"]:
        raise RuntimeError(f"the release has no {name} for this platform")
    sums = _get(release["assets"]["SHA256SUMS"]).decode()
    expected = next(
        (line.split()[0] for line in sums.splitlines() if line.strip().endswith(name)), None
    )
    if not expected:
        raise RuntimeError(f"SHA256SUMS does not list {name}; refusing to install it")
    payload = _get(release["assets"][name])
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise RuntimeError(f"checksum mismatch for {name}: expected {expected}, got {actual}")
    target = dest / name
    target.write_bytes(payload)
    return target


def apply_update(release: dict | None = None) -> str:
    """Install the latest release over this one. Returns what happened."""
    release = release or latest_release()
    version = release["version"]
    if not is_newer(version):
        return f"Sensei {__version__} is the latest release."

    kind = install_kind()
    if kind == "pip":
        return (
            f"Sensei {version} is available (you have {__version__}). This copy was "
            "installed with pip, so update it the same way:\n"
            f"    pipx install --force {release['url'].replace('/tag/', '/download/')}/"
            f"sensei_gateway-{version}-py3-none-any.whl\n"
            "or, from a checkout:  git pull && pip install -e backend"
        )
    if kind == "binary-readonly":
        return (
            f"Sensei {version} is available, but {Path(sys.executable).parent} is not writable "
            "without administrator rights. Re-run the installer with the same "
            "SENSEI_INSTALL_DIR under sudo, or download it from " + release["url"]
        )
    if kind == "system-package":
        return (
            f"Sensei {version} is available. This copy came from a .deb or .rpm, so "
            f"install the new package from {release['url']}"
        )

    name = _asset_name(version)
    if name is None:
        return f"No build of {version} for this platform; see {release['url']}"
    workdir = Path(tempfile.mkdtemp(prefix="sensei-update-"))
    downloaded = _verified_download(release, name, workdir)

    if kind == "windows-installer":
        # The installer closes the running copy itself (Restart Manager) and
        # keeps the user's tasks — autostart, wired tools — as they were.
        subprocess.Popen(  # noqa: S603
            [str(downloaded), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            close_fds=True,
        )
        return f"Installing Sensei {version}; the installer takes it from here."

    current = Path(os.environ.get("APPIMAGE") or sys.executable).resolve()
    if kind == "windows-portable":
        return (
            f"Sensei {version} downloaded and verified: {downloaded}. Unzip it over "
            f"{current.parent} once Sensei has quit."
        )
    if name.endswith(".tar.gz"):
        with tarfile.open(downloaded) as archive:
            member = archive.getmember("sensei")
            if not member.isfile():
                raise RuntimeError("unexpected archive layout")
            archive.extract(member, workdir, filter="data")
        fresh = workdir / "sensei"
    else:
        fresh = downloaded
    fresh.chmod(0o755)
    # Replacing a running executable is fine on macOS and Linux: the running
    # process keeps its open inode, and the next start picks up the new file.
    staged = current.with_name(current.name + ".new")
    shutil.copy2(fresh, staged)
    os.replace(staged, current)
    return f"Updated to Sensei {version}. Restart it to use the new version."


# ── CLI ──────────────────────────────────────────────────────────────────────


def run_autostart(action: str) -> int:
    if action == "on":
        state = autostart_enable()
        print(f"Sensei will start at login ({state.mechanism}: {state.location}).")
        return 0 if state.enabled else 1
    if action == "off":
        state = autostart_disable()
        print(
            "Sensei will no longer start at login."
            if not state.enabled
            else f"Still enabled via {state.mechanism} ({state.location}) — remove that by hand."
        )
        return 0
    state = autostart_status()
    if state.enabled:
        print(f"on   ({state.mechanism}: {state.location})")
        if state.command:
            print(f"     {state.command}")
    else:
        print(f"off  (`sensei autostart on` would use {state.mechanism})")
    return 0


def run_update(check_only: bool) -> int:
    try:
        info = check()
    except Exception as exc:
        print(f"Could not reach GitHub to check for updates: {exc}")
        return 1
    if not info["update_available"]:
        print(f"Sensei {info['current']} is up to date.")
        return 0
    print(f"Sensei {info['latest']} is available (you have {info['current']}).")
    print(f"What's new: {info['url']}")
    if check_only:
        print("Run `sensei update` to install it.")
        return 0
    try:
        print(apply_update())
    except Exception as exc:
        print(f"Update failed: {exc}")
        return 1
    return 0

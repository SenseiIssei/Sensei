"""Single-binary entry point for Sensei.

PyInstaller bundles this as ``sensei.exe`` / ``sensei``; see ``sensei.spec``.

It is a thin shim over the ordinary CLI, and that is the whole design. It used
to be a second implementation of `sensei up` — it started uvicorn, mounted the
bundled web UI and opened a browser, and it never looked at ``sys.argv``. So the
downloadable binary had no command line at all: `sensei.exe doctor` started the
server, `sensei.exe --version` started the server, and `sensei.exe setup-tools`
— which the release notes tell people to run — started the server.

Nobody caught it because the release workflow had never run: the repository had
no tags until v0.1.0, so no binary had ever been produced, let alone executed.

`sensei.cli.serve` already finds a bundled web UI through ``sys._MEIPASS``, so
there is nothing here for the shim to do beyond choosing a default verb.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _windowed() -> bool:
    """Is this the console-less build?

    Same convention as `python.exe` / `pythonw.exe`: the trailing "w" is the
    whole signal. Checking the executable name rather than probing stdout,
    because a console build launched from a shortcut has a perfectly good
    stdout that nobody is looking at, and a windowed build under a debugger can
    have one attached.
    """
    stem = Path(sys.executable).stem.lower()
    return getattr(sys, "frozen", False) and stem.endswith("w")


def _attach_streams() -> Path | None:
    """Give a windowed process the stdout and stderr every library assumes.

    In a GUI-subsystem build there is no console, so `sys.stdout` and
    `sys.stderr` are `None`. Most code never notices; anything that asks a
    stream about itself crashes on the spot. uvicorn's log formatter calls
    `sys.stdout.isatty()` to decide whether to colourise, so the tray died
    before it drew anything, with the only symptom being that nothing happened.

    Pointing them at a file rather than at os.devnull, because a background app
    that fails invisibly is one you cannot debug — and this is the only place
    its output can go.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None

    # Both handles live as long as the process; there is nothing to close them
    # against, and closing them would put the streams back to None.
    log: Path | None = Path(sys.executable).with_name("sensei.log")
    try:
        handle = log.open("w", encoding="utf-8", buffering=1)
    except OSError:
        # A read-only install directory is not a reason to fail to start; it
        # only costs the log. devnull still has to be *assigned*, because the
        # whole point is that nothing downstream sees None.
        import os

        handle = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        log = None

    if sys.stdout is None:
        sys.stdout = handle
    if sys.stderr is None:
        sys.stderr = handle
    return log


def main() -> int:
    from sensei.cli import main as cli_main

    _attach_streams()
    argv = sys.argv[1:]

    if not argv:
        # Double-clicking should start the thing, not print usage into a window
        # that closes before anyone can read it. Which "start" means depends on
        # which binary this is: the windowed one has no console to hold a server
        # in and no way to be stopped except Task Manager, so it goes to the
        # tray. An explicit command always wins over both.
        argv = ["tray"] if _windowed() else ["up"]

    if _windowed():
        # Nothing printed here can be seen, and a traceback into a void is how a
        # tray app becomes "it just doesn't start". Errors go to a file beside
        # the executable instead.
        try:
            return cli_main(argv)
        except Exception:  # noqa: BLE001 — the last place anything can be seen
            import traceback

            log = Path(sys.executable).with_name("sensei-error.log")
            try:
                log.write_text(traceback.format_exc(), encoding="utf-8")
            except OSError:
                pass
            return 1

    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())

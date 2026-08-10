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


def main() -> int:
    from sensei.cli import main as cli_main

    argv = sys.argv[1:]

    # Double-clicking the binary passes no arguments, and the expected result of
    # double-clicking an app is that it starts — not that it prints usage into a
    # console window that closes immediately. An explicit command always wins.
    if not argv:
        argv = ["up"]

    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())

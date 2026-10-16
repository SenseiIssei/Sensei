"""`sensei tray` — run Sensei in the background with a system-tray icon.

The gateway is only useful while it is running, and a server you have to keep a
terminal window open for is a server people forget to start. This runs the same
uvicorn instance `sensei up` does, in a thread, behind a tray icon that can open
the dashboard, wire up tools and quit.

Deliberately not a GUI framework. PySide6 is already an optional extra and could
draw this, but it is roughly 150 MB to put one icon in a corner — which would
more than quintuple the size of a binary whose whole pitch is that it stays out
of your way. `pystray` plus Pillow is about 5 MB and does exactly this one job.

The icon is drawn in code rather than shipped as a file: it is a bolt on a
rounded square, it has to exist at three sizes for Windows to pick a sensible
one, and generating it avoids an asset that packaging has to remember to
include.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
import webbrowser
from typing import Any

from sensei import __version__
from sensei.config import settings

logger = logging.getLogger(__name__)

# The app logo: three lines narrowing on the dashboard's dark canvas, in its
# periwinkle accent, with the one gold dot that marks a saving.
_ACCENT = (166, 176, 242, 255)
_GOLD = (255, 212, 125, 255)
_DARK = (19, 22, 25, 255)


def _icon_image(size: int = 64) -> Any:
    """The logo, drawn rather than loaded (see frontend/public/sensei.svg)."""
    from PIL import Image, ImageDraw

    # Drawn at 4x and scaled down: Pillow's shapes have no anti-aliasing.
    big = size * 4
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def u(v: float) -> float:  # SVG units (0..100) to pixels
        return v * big / 100

    draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=u(22), fill=_DARK)
    stroke = u(8.5)
    for x0, x1, y in ((24, 76, 34), (32, 68, 51), (40, 60, 68)):
        draw.line([(u(x0), u(y)), (u(x1), u(y))], fill=_ACCENT, width=round(stroke))
        for x in (x0, x1):  # round caps
            draw.ellipse(
                [u(x) - stroke / 2, u(y) - stroke / 2, u(x) + stroke / 2, u(y) + stroke / 2],
                fill=_ACCENT,
            )
    draw.ellipse([u(72 - 5.5), u(68 - 5.5), u(72 + 5.5), u(68 + 5.5)], fill=_GOLD)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def _url(path: str = "/app/") -> str:
    host = settings.host
    if host in ("0.0.0.0", "::", ""):  # noqa: S104 — comparison, not a bind
        host = "localhost"
    return f"http://{host}:{settings.port}{path}"


def _already_running() -> bool:
    """Is a Sensei already answering on this port?

    The installer starts the tray after an update, and install.ps1 used to
    start a second one right behind it. The second could not bind the port,
    so its server thread died quietly — and left an icon in the tray whose
    menu drove nothing.
    """
    import urllib.request

    try:
        with urllib.request.urlopen(_url("/health"), timeout=1.0) as resp:  # noqa: S310
            return resp.status == 200 and b"version" in resp.read(512)
    except Exception:
        return False


def _summary(outcomes: list[Any], verb: str) -> str:
    changed = sorted({o.name for o in outcomes if o.status == "applied"})
    manual = sorted({o.name for o in outcomes if o.status == "manual"})
    if not changed and not manual:
        return f"Nothing to {verb} — everything already was."
    text = f"{verb.capitalize()}ed: {', '.join(changed)}." if changed else ""
    if manual:
        text += f" Needs a manual step: {', '.join(manual)} (see the dashboard)."
    if changed and verb == "connect":
        text += " Restart those tools to pick it up."
    return text.strip()


def run(port: int | None = None, open_browser: bool = True) -> int:
    """Serve in a background thread and hold the tray icon on the main one."""
    try:
        import pystray
    except ImportError:
        print("The tray needs the optional 'tray' extra:")
        print('    pip install -e "backend[tray]"   (the release binaries include it)')
        return 1

    import uvicorn

    from sensei.cli.serve import _frontend_dist
    from sensei.main import app

    if port:
        settings.port = port

    if _already_running():
        print(f"Sensei is already running at {_url('')}")
        if open_browser:
            webbrowser.open(_url())
        return 0

    dist = _frontend_dist()
    if dist:
        from fastapi.staticfiles import StaticFiles

        app.mount("/app", StaticFiles(directory=str(dist), html=True), name="webapp")

    # `Server` rather than `uvicorn.run` so the tray can ask it to stop. run()
    # installs signal handlers, which only works on the main thread — and the
    # main thread here belongs to the icon.
    config = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

    thread = threading.Thread(target=server.run, name="sensei-server", daemon=True)
    thread.start()

    # Wait for the port to answer before opening a browser at it, rather than
    # racing startup and showing the user a connection error.
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)

    def open_dashboard(*_: Any) -> None:
        webbrowser.open(_url())

    from sensei import autowire, integrations

    def connect_all(icon: Any, *_: Any) -> None:
        # In a thread: this touches the filesystem and can take a moment, and
        # blocking here freezes the menu.
        def work() -> None:
            try:
                icon.notify(_summary(integrations.connect_everything(), "connect"), "Sensei")
            except Exception as exc:
                icon.notify(f"Could not connect tools: {exc}", "Sensei")

        threading.Thread(target=work, daemon=True).start()

    def disconnect_all(icon: Any, *_: Any) -> None:
        def work() -> None:
            try:
                outcomes = integrations.disconnect_everything()
                icon.notify(
                    _summary(outcomes, "disconnect")
                    + " New tools will not be connected until you choose Connect everything.",
                    "Sensei",
                )
            except Exception as exc:
                icon.notify(f"Could not disconnect tools: {exc}", "Sensei")

        threading.Thread(target=work, daemon=True).start()

    def auto_connecting(*_: Any) -> bool:
        try:
            return integrations.auto_connect_allowed()
        except Exception:
            return False

    def toggle_auto(*_: Any) -> None:
        integrations.set_auto_connect(not auto_connecting())

    def open_connections(*_: Any) -> None:
        webbrowser.open(_url("/app/#/connections"))

    from sensei.cli import system

    def starts_at_login(*_: Any) -> bool:
        try:
            return system.autostart_status().enabled
        except Exception:
            return False

    def toggle_autostart(*_: Any) -> None:
        if starts_at_login():
            system.autostart_disable()
        else:
            system.autostart_enable()

    def check_updates(icon: Any, *_: Any) -> None:
        def work() -> None:
            try:
                info = system.check()
            except Exception as exc:
                icon.notify(f"Could not check for updates: {exc}", "Sensei")
                return
            if info["update_available"]:
                icon.notify(
                    f"Sensei {info['latest']} is available — run `sensei update`.", "Sensei"
                )
                webbrowser.open(info["url"])
            else:
                icon.notify(f"Sensei {info['current']} is up to date.", "Sensei")

        threading.Thread(target=work, daemon=True).start()

    def quit_sensei(icon: Any, *_: Any) -> None:
        server.should_exit = True
        icon.stop()

    icon = pystray.Icon(
        "sensei",
        _icon_image(),
        f"Sensei {__version__} — {_url('')}",
        menu=pystray.Menu(
            pystray.MenuItem("Open dashboard", open_dashboard, default=True),
            pystray.MenuItem("Connections…", open_connections),
            pystray.MenuItem("Connect everything", connect_all),
            pystray.MenuItem("Disconnect everything", disconnect_all),
            pystray.MenuItem(
                "Connect new tools automatically", toggle_auto, checked=auto_connecting
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start at login", toggle_autostart, checked=starts_at_login),
            pystray.MenuItem("Check for updates", check_updates),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Sensei", quit_sensei),
        ),
    )

    def tools_connected(names: list[str]) -> None:
        with contextlib.suppress(Exception):
            icon.notify(
                f"Connected {', '.join(names)} to Sensei. Restart "
                f"{'it' if len(names) == 1 else 'them'} to pick this up.",
                "Sensei",
            )

    autowire.subscribe(tools_connected)

    if open_browser:
        open_dashboard()

    print(f"Sensei {__version__} is running in the tray at {_url('')}")
    print("Right-click the tray icon to open the dashboard or quit.")

    icon.run()  # blocks until quit_sensei stops it

    server.should_exit = True
    thread.join(timeout=5)
    return 0

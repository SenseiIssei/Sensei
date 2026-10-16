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


def run(port: int | None = None, open_browser: bool = True) -> int:
    """Serve in a background thread and hold the tray icon on the main one."""
    try:
        import pystray
    except ImportError:
        print("The tray needs the optional 'tray' extra:")
        print('    pip install "sensei-gateway[tray]"')
        return 1

    import uvicorn

    from sensei.cli.serve import _frontend_dist
    from sensei.main import app

    if port:
        settings.port = port

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

    def wire_tools(*_: Any) -> None:
        from sensei.cli import setup_tools

        # In a thread: this touches the filesystem and can take a moment, and
        # blocking here freezes the menu.
        threading.Thread(target=setup_tools.run, daemon=True).start()

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
            pystray.MenuItem("Connect my AI tools", wire_tools),
            pystray.MenuItem("Start at login", toggle_autostart, checked=starts_at_login),
            pystray.MenuItem("Check for updates", check_updates),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Sensei", quit_sensei),
        ),
    )

    if open_browser:
        open_dashboard()

    print(f"Sensei {__version__} is running in the tray at {_url('')}")
    print("Right-click the tray icon to open the dashboard or quit.")

    icon.run()  # blocks until quit_sensei stops it

    server.should_exit = True
    thread.join(timeout=5)
    return 0

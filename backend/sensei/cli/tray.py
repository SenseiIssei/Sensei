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

# Matches the dashboard: Sensei green on the near-black the UI uses.
_GREEN = (34, 197, 94, 255)
_DARK = (10, 10, 15, 255)


def _icon_image(size: int = 64) -> Any:
    """A bolt on a rounded square, drawn rather than loaded."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    pad = size // 10
    radius = size // 5
    draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=radius, fill=_DARK)

    # A lightning bolt, in fractions of the icon so it scales cleanly.
    def point(fx: float, fy: float) -> tuple[float, float]:
        return (pad + fx * (size - 2 * pad), pad + fy * (size - 2 * pad))

    draw.polygon(
        [
            point(0.56, 0.10),
            point(0.28, 0.55),
            point(0.46, 0.55),
            point(0.40, 0.90),
            point(0.70, 0.42),
            point(0.51, 0.42),
        ],
        fill=_GREEN,
    )
    return image


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

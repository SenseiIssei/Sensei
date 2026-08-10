"""`sensei up` — start the server, serve the web UI, open a browser.

This is the front door. A first-time user should be able to install Sensei and
type one word.
"""

from __future__ import annotations

import contextlib
import threading
import time
import webbrowser
from pathlib import Path

from sensei import __version__
from sensei.config import settings


def _frontend_dist() -> Path | None:
    """Find a built web UI, in any of the four ways Sensei can be installed.

    The third candidate is the one that matters most and was missing until
    2026-08-10: a `pip install` shipped no web UI at all, because the wheel is
    built from `backend/` and the UI lives in `frontend/`. Every pip and pipx
    user therefore landed on the Swagger page instead of the dashboard, with
    "the web UI isn't built" telling them to run an npm command inside a
    repository they had never cloned. The wheel now carries the built UI as
    package data at `sensei/webui`.
    """
    import sys

    candidates = [
        # PyInstaller bundle.
        *(
            [Path(meipass) / "frontend" / "dist"]
            if (meipass := getattr(sys, "_MEIPASS", None))
            else []
        ),
        # Installed wheel: package data next to this module.
        Path(__file__).resolve().parents[1] / "webui",
        # Source checkout: backend/sensei/cli/serve.py -> repo root.
        Path(__file__).resolve().parents[3] / "frontend" / "dist",
    ]
    return next((c for c in candidates if c.exists() and any(c.iterdir())), None)


def run(
    port: int | None = None,
    expose: bool = False,
    open_browser: bool = True,
    reload: bool = False,
) -> int:
    import uvicorn

    from sensei.main import app

    port = port or settings.port
    host = "0.0.0.0" if expose else settings.host  # noqa: S104 — explicit opt-in

    url_path = "/docs"
    dist = _frontend_dist()
    if dist:
        from fastapi.staticfiles import StaticFiles

        app.mount("/app", StaticFiles(directory=str(dist), html=True), name="webapp")
        url_path = "/app"

    display_host = "localhost" if host in ("0.0.0.0", "::") else host  # noqa: S104
    url = f"http://{display_host}:{port}{url_path}"

    print(f"\n  Sensei v{__version__}")
    print(f"  Web UI    {url}")
    print(f"  Gateway   http://{display_host}:{port}/v1  (OpenAI-compatible)")
    print(f"            http://{display_host}:{port}     (Anthropic-compatible)")
    if not dist:
        print("\n  The web UI isn't built — serving the API only.")
        print("  Build it with: cd frontend && npm ci && npm run build")
    if expose:
        print("\n  \033[33mExposed on all interfaces.\033[0m Anyone who can reach this port")
        print("  can use your API keys. Enable auth and put TLS in front of it.")
    print("\n  Route a tool through it:  sensei wrap claude")
    print("  Diagnose problems:        sensei doctor")
    print("\n  Ctrl+C to stop.\n")

    if open_browser and dist:

        def _open() -> None:
            time.sleep(1.5)
            try:
                webbrowser.open(url)
            except Exception as exc:
                print(f"  (couldn't open a browser: {exc})")

        threading.Thread(target=_open, daemon=True).start()

    # Ctrl+C is how you stop a server, not an error.
    with contextlib.suppress(KeyboardInterrupt):
        uvicorn.run(
            "sensei.main:app" if reload else app,
            host=host,
            port=port,
            reload=reload,
            log_level="info",
        )
    return 0

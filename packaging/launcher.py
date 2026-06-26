"""Single-binary launcher for Sensei.

Starts the FastAPI backend (and serves the built web UI at /app when present),
then opens a browser. This is the entry point bundled into ``sensei.exe`` by
PyInstaller — see ``sensei.spec``.
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path


def _frontend_dist() -> Path | None:
    """Locate a built web UI, whether running from source or a PyInstaller bundle."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "frontend" / "dist")
    candidates.append(Path(__file__).resolve().parents[1] / "frontend" / "dist")
    for c in candidates:
        if c.exists():
            return c
    return None


def main() -> None:
    from sensei.config import settings
    from sensei.main import app

    url_path = "/docs"
    dist = _frontend_dist()
    if dist:
        from fastapi.staticfiles import StaticFiles

        app.mount("/app", StaticFiles(directory=str(dist), html=True), name="webapp")
        url_path = "/app"

    import uvicorn

    port = settings.port
    url = f"http://localhost:{port}{url_path}"

    def open_browser() -> None:
        time.sleep(1.5)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=open_browser, daemon=True).start()
    print(f"Sensei is starting at {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host=settings.host, port=port)


if __name__ == "__main__":
    main()

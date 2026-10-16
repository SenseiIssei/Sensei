"""Cross-site request forgery guard for the web API.

Sensei listens on loopback with auth off by default, and a web page the user
visits can send a "simple" cross-origin POST to it — `text/plain`, no
preflight — which the browser delivers without asking anyone. Before this
guard, `POST /api/setup/tools/connect` with `Origin: https://evil.example`
returned 200 and rewrote the configuration of every AI tool on the machine.

Browsers attach an `Origin` header to every cross-origin POST, PUT, PATCH and
DELETE. A state-changing `/api` request is let through only when its Origin is
absent (curl, scripts, the tray — nothing a web page can be), loopback, the
same origin as the request itself (`sensei up --expose` opened from a phone),
or listed in `SENSEI_CORS_ORIGINS`. Anything else is refused with 403 before
it reaches a route.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from sensei.config import settings

_UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def origin_allowed(origin: str, host_header: str) -> bool:
    """May a browser page at ``origin`` change state on this server?"""
    if not origin or origin == "null":
        return False
    parsed = urlparse(origin)
    hostname = (parsed.hostname or "").lower()
    if hostname in _LOOPBACK:
        return True
    if parsed.netloc.lower() == host_header.lower():
        return True
    return origin.rstrip("/") in {o.rstrip("/") for o in settings.cors_origin_list}


class OriginGuard:
    """ASGI middleware: refuse cross-site state changes on /api."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if (
            scope.get("type") == "http"
            and scope.get("method") in _UNSAFE
            and str(scope.get("path", "")).startswith("/api/")
        ):
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]
            }
            origin = headers.get("origin")
            if origin is not None and not origin_allowed(origin, headers.get("host", "")):
                body = json.dumps({"error": "cross-site request refused"}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)

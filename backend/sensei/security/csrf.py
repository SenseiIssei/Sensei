"""Keep web pages out: cross-site requests and DNS rebinding.

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

The same goes for `/v1`. A request without a key of its own is answered with
the one configured in Sensei, so a page that could POST there could spend it.
Desktop apps send origins such as `vscode-file://`; only `http`, `https` and
the opaque `null` can be a web page, so only those are refused on `/v1`.

Origin checks do not stop DNS rebinding: a page on `evil.example` whose name
suddenly resolves to 127.0.0.1 is *same origin* with what answers there, and
could read conversations and change settings. Its requests still say
`Host: evil.example`, though, so `HostGuard` answers only to names that cannot
belong to somebody else's page.

Both cover the chat WebSocket. Browsers open those across origins without
asking, and unlike a cross-origin fetch the page can read what comes back.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlparse

from sensei.config import settings
from sensei.security.urls import is_loopback

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


def _is_web_origin(origin: str) -> bool:
    return origin == "null" or urlparse(origin).scheme in ("http", "https")


def _headers(scope: Any) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}


async def _refuse(scope: Any, send: Any, status: int, message: str) -> None:
    if scope["type"] == "websocket":
        # Closed before it is accepted: the browser sees a failed handshake.
        await send({"type": "websocket.close", "code": 1008, "reason": message})
        return
    body = json.dumps({"error": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


# How a container reaches the machine it runs on; Docker Desktop delivers that
# on loopback.
_CONTAINER_NAMES = frozenset(
    {"host.docker.internal", "gateway.docker.internal", "host.containers.internal"}
)
# Names only a local resolver answers for.
_PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa")


def host_allowed(host_header: str, local_address: str = "127.0.0.1") -> bool:
    """Can a request for this host not have come from a rebound name?

    An IP address or "localhost" cannot be rebound. A single-label or private
    name (a compose service, `desk.local`) cannot by anybody on the internet, but
    can by whoever runs the Wi-Fi, and then it arrives on loopback: there these
    names mean nothing anyway, so they count only when the connection
    (``local_address`` is our end of it) came in over a network.
    """
    host = host_header.strip().lower()
    if not host:
        return True
    if host.startswith("["):  # [::1]:7000
        return True
    host = host.rsplit(":", 1)[0] if ":" in host else host
    host = host.rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host in _CONTAINER_NAMES:
        return True
    if not is_loopback(local_address) and ("." not in host or host.endswith(_PRIVATE_SUFFIXES)):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    allowed = {h.strip().lower() for h in settings.allowed_hosts.split(",") if h.strip()}
    if "*" in allowed or host in allowed:
        return True
    return host in {(urlparse(o).hostname or "").lower() for o in settings.cors_origin_list}


class HostGuard:
    """ASGI middleware: refuse requests that reached us through a foreign name.

    Only without auth. With a token required, a page that got here through a
    rebound name has nothing to present, and a public hostname is expected.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") in ("http", "websocket") and not settings.auth_enabled:
            host = _headers(scope).get("host", "")
            local = (scope.get("server") or ("127.0.0.1", None))[0]
            if not host_allowed(host, str(local)):
                await _refuse(
                    scope,
                    send,
                    403,
                    "host not allowed: add it to SENSEI_ALLOWED_HOSTS, or turn on "
                    "SENSEI_AUTH_ENABLED",
                )
                return
        await self.app(scope, receive, send)


class OriginGuard:
    """ASGI middleware: refuse cross-site state changes on /api and /v1."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        kind = scope.get("type")
        if (kind == "websocket" or (kind == "http" and scope.get("method") in _UNSAFE)) and (
            path := str(scope.get("path", ""))
        ).startswith(("/api/", "/v1/")):
            headers = _headers(scope)
            origin = headers.get("origin")
            if (
                origin is not None
                and (path.startswith("/api/") or _is_web_origin(origin))
                and not origin_allowed(origin, headers.get("host", ""))
            ):
                await _refuse(scope, send, 403, "cross-site request refused")
                return
        await self.app(scope, receive, send)

"""Small questions about addresses, asked in more than one place."""

from __future__ import annotations

import ipaddress


def is_loopback(host: str | None) -> bool:
    """Is this peer address this machine? (``testclient`` is Starlette's.)"""
    if not host:
        return False
    if host in ("localhost", "testclient"):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False

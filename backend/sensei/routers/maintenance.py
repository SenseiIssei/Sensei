from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from sensei.purge import purge_expired
from sensei.security.rbac import require_admin

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.post("/purge")
async def trigger_purge(_admin=Depends(require_admin)) -> dict[str, Any]:
    """Run data purge now (expired sessions/CCR + old audit entries)."""
    return purge_expired()


# One GitHub request per day at most, shared by the dashboard and the tray.
_update_cache: dict[str, Any] = {}
_UPDATE_TTL = 24 * 3600


@router.get("/update")
async def update_status(force: bool = False) -> dict[str, Any]:
    """Is a newer release out?

    With ``SENSEI_UPDATE_CHECK`` off (the default) this makes no network request
    unless ``force=true`` — which is what the dashboard's "Check now" button
    sends, so the request only ever happens because someone asked for it.
    """
    import asyncio
    import time

    from sensei import __version__
    from sensei.cli import system
    from sensei.config import settings

    if not (settings.update_check or force):
        return {"current": __version__, "enabled": False}
    cached = _update_cache.get("result")
    if cached and not force and time.time() - cached["checked_at"] < _UPDATE_TTL:
        return {**cached, "enabled": True}
    try:
        result = await asyncio.to_thread(system.check)
    except Exception as exc:
        return {"current": __version__, "enabled": True, "error": str(exc)}
    _update_cache["result"] = result
    return {**result, "enabled": True}

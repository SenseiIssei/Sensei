from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from sensei.watch import check_watches, get_watch_store

router = APIRouter(prefix="/watch", tags=["watch"])


class WatchIn(BaseModel):
    url: str
    interval_minutes: int = 60
    notify_url: str = ""


@router.get("")
async def list_watches() -> dict[str, Any]:
    return {"watches": get_watch_store().list()}


@router.post("")
async def add_watch(w: WatchIn) -> dict[str, Any]:
    wid = get_watch_store().add(w.url, w.interval_minutes, w.notify_url)
    return {"id": wid, "url": w.url}


@router.delete("/{wid}")
async def remove_watch(wid: str) -> dict[str, bool]:
    return {"removed": get_watch_store().remove(wid)}


@router.post("/check")
async def check_now() -> dict[str, Any]:
    """Force-check all watches now; returns detected changes."""
    return {"changes": await check_watches(force=True)}

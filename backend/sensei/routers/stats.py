from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from sensei.compression.ccr import CCRStore
from sensei.config import settings
from sensei.savings import get_savings_tracker

router = APIRouter(prefix="/stats", tags=["stats"])

_ccr_store: CCRStore | None = None


def init_stats_deps(ccr_store: CCRStore) -> None:
    global _ccr_store
    _ccr_store = ccr_store


def _get_ccr_store() -> CCRStore:
    """Return the wired CCR store, lazily creating one if startup hasn't run."""
    global _ccr_store
    if _ccr_store is None:
        _ccr_store = CCRStore()
    return _ccr_store


@router.get("")
async def get_stats() -> dict[str, Any]:
    """Get compression and cache statistics."""
    store = _get_ccr_store()
    ccr_stats = store.stats()
    evicted = store.cleanup()

    return {
        "compression_enabled": settings.compression_enabled,
        "ccr": ccr_stats,
        "evicted_entries": evicted,
        "cache_ttl_hours": settings.ccr_ttl_hours,
        "savings": get_savings_tracker().snapshot(),
    }


@router.get("/savings")
async def get_savings() -> dict[str, Any]:
    """Everything the dashboard needs, in one request.

    Deliberately one endpoint rather than four: the page draws a single
    coherent picture, and four independent fetches would let it render a
    lifetime total next to a daily series computed a second later.
    """
    return await _savings_payload()


async def _savings_payload() -> dict[str, Any]:
    """Shared by the one-shot endpoint and the stream, so the two cannot drift."""
    tracker = get_savings_tracker()
    ledger = tracker.ledger
    return {
        "session": tracker.snapshot(),
        "lifetime": ledger.totals(),
        "daily": ledger.daily(days=30),
        "by_tool": ledger.breakdown("tool"),
        "by_provider": ledger.breakdown("provider"),
        "by_model": ledger.breakdown("model"),
        "persisted": settings.savings_persist,
        "price_per_million_usd": settings.usd_per_million_tokens,
        # Output shaping reports a difference against its own control arm, or
        # says it does not have enough data. It never reports a point estimate
        # on its own.
        "output_effect": tracker.output_effect(),
    }


# One tick a second, so this is an hour. A stream is not meant to be immortal:
# `is_disconnected()` is the primary way a dropped client is noticed, but it is
# not guaranteed to fire on every transport, and a generator that loops forever
# with nobody listening is a leak that only shows up as slow memory growth days
# later. EventSource reconnects by itself, so the client sees nothing.
MAX_STREAM_TICKS = 3600


def change_signature(payload: dict[str, Any]) -> str:
    """What counts as a change worth pushing to a connected dashboard.

    `since` on an empty ledger is `time.time()` — there is no first row to take
    a timestamp from — so a raw comparison of the payload differs every second
    and the stream fires continuously at a server doing nothing at all. The one
    field that moves on its own is excluded from the *comparison*, not from the
    payload: the client still receives it.
    """
    trimmed = {k: v for k, v in payload.items() if k not in ("session", "lifetime")}
    for key in ("session", "lifetime"):
        block = dict(payload.get(key) or {})
        block.pop("since", None)
        trimmed[key] = block
    return json.dumps(trimmed, sort_keys=True)


@router.get("/savings/stream")
async def stream_savings(request: Request) -> StreamingResponse:
    """Push the savings payload as it changes, over Server-Sent Events.

    The dashboard used to poll every fifteen seconds, which meant a number that
    could be a quarter of a minute stale on a page whose whole job is to show
    you what is happening. SSE rather than a WebSocket because the data only
    travels one way and SSE reconnects on its own — a websocket here would be
    hand-rolling that for nothing.

    The server still polls its own ledger internally, once a second; there is
    no change notification to hook into and a one-second SQLite count on an
    indexed table is not worth the machinery of one. What the client gets is a
    push, which is the part that matters.
    """

    async def events():
        last: str | None = None
        # A heartbeat keeps intermediaries from closing an idle connection, and
        # tells the client the stream is alive rather than merely quiet.
        beat = 0
        ticks = 0
        while ticks < MAX_STREAM_TICKS:
            ticks += 1
            if await request.is_disconnected():
                break
            data = await _savings_payload()
            payload = json.dumps(data)
            current = change_signature(data)
            if current != last:
                last = current
                beat = 0
                yield f"event: savings\ndata: {payload}\n\n"
            elif beat >= 15:
                beat = 0
                yield ": keep-alive\n\n"
            else:
                beat += 1
            await asyncio.sleep(1.0)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx buffers by default and would hold every event until the
            # response ends, which for a stream is never. deploy/nginx.conf
            # sets this too; the header makes it work behind one that doesn't.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/savings/daily")
async def get_savings_daily(days: int = 30) -> dict[str, Any]:
    """The time series on its own, for a longer window than the page loads."""
    return {"daily": get_savings_tracker().ledger.daily(days=days)}


@router.post("/savings/forget")
async def forget_savings() -> dict[str, Any]:
    """Delete the local history. There is no copy of it anywhere else."""
    tracker = get_savings_tracker()
    tracker.ledger.clear()
    tracker.reset()
    return {"ok": True, "message": "Savings history deleted."}


@router.get("/ccr/{ccr_id}")
async def get_ccr_info(ccr_id: str) -> dict[str, Any]:
    """Get info about a specific CCR entry."""
    info = _get_ccr_store().get_info(ccr_id)
    if info is None:
        return {"error": "CCR entry not found or expired"}
    return info


@router.get("/ccr/{ccr_id}/original")
async def retrieve_original(ccr_id: str) -> dict[str, Any]:
    """Retrieve the original uncompressed content for a CCR entry."""
    original = _get_ccr_store().retrieve(ccr_id)
    if original is None:
        return {"error": "CCR entry not found or expired"}
    return {"content": original}

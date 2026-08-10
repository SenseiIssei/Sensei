from __future__ import annotations

from typing import Any

from fastapi import APIRouter

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
    }


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

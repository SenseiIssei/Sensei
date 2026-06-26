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

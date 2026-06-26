from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from sensei.purge import purge_expired

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.post("/purge")
async def trigger_purge() -> dict[str, Any]:
    """Run data purge now (expired sessions/CCR + old audit entries)."""
    return purge_expired()

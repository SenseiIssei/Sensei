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

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from sensei.audit import get_audit_log
from sensei.security.rbac import require_admin

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def get_audit(limit: int = 100, _admin=Depends(require_admin)) -> dict[str, Any]:
    """Return the most recent audit events (metadata only)."""
    return {"events": get_audit_log().tail(limit)}

"""Role-based access control dependency.

When ``rbac_enabled`` is off (default) this is a no-op, so local/self-hosted use
needs no auth. When on, admin-only endpoints require a user JWT (bearer token
from /api/auth login) whose role is ``admin``.
"""
from __future__ import annotations

from fastapi import Header, HTTPException

from sensei.config import settings
from sensei.security.users import verify_token


async def require_admin(authorization: str = Header(default="")) -> dict | None:
    if not settings.rbac_enabled:
        return None
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    payload = verify_token(token) if token else None
    if not payload:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    return payload

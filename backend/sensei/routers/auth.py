"""Auth API routes for public Sensei chat — registration, login, OIDC SSO, verify."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from sensei.config import settings
from sensei.security.users import (
    UserLogin,
    UserRegister,
    TokenResponse,
    get_user_from_token,
    login_user,
    provision_sso_user,
    register_user,
)

router = APIRouter(tags=["auth"])


class OIDCExchange(BaseModel):
    id_token: str


@router.post("/auth/register", response_model=TokenResponse)
async def register(body: UserRegister) -> TokenResponse:
    token, error = register_user(body.email, body.password, body.name)
    if error:
        raise HTTPException(status_code=409, detail=error)
    return token


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: UserLogin) -> TokenResponse:
    token, error = login_user(body.email, body.password)
    if error:
        raise HTTPException(status_code=401, detail=error)
    return token


@router.get("/auth/oidc/config")
async def oidc_config() -> dict:
    """Public config the frontend needs to start the OIDC flow."""
    return {
        "enabled": settings.oidc_enabled,
        "issuer": settings.oidc_issuer,
        "client_id": settings.oidc_client_id,
    }


@router.post("/auth/oidc", response_model=TokenResponse)
async def oidc_exchange(body: OIDCExchange) -> TokenResponse:
    """Exchange an IdP-issued OIDC ID token for a Sensei session token."""
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="OIDC SSO is not enabled")
    from sensei.security.oidc import OIDCError, verify_id_token

    try:
        claims = verify_id_token(body.id_token)
    except OIDCError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return provision_sso_user(claims["email"], claims.get("name") or claims["email"])


@router.get("/auth/me")
async def me(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization[7:]
    user = get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user
